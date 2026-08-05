from __future__ import annotations

import csv
import ctypes
import errno
import fcntl
import json
import math
import os
import re
import shutil
import signal
import stat
import statistics
import subprocess
import sys
import uuid
from collections import Counter
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

from .models import (
    BenchmarkFailure,
    CONCURRENT_CANCEL_WORKLOAD,
    LIVE_REPORT_SCHEMA_VERSION,
    LatencySummary,
    LiveBenchmarkReport,
)
from .results import assert_report_is_sanitized, summarize_ns, write_report


DETAIL_START = "<!-- live-exchange-benchmark:detail:start -->"
DETAIL_END = "<!-- live-exchange-benchmark:detail:end -->"
OVERALL_START = "<!-- live-exchange-benchmark:overall:start -->"
OVERALL_END = "<!-- live-exchange-benchmark:overall:end -->"
FIGURE_FILENAMES = (
    "cancel-id-latency.png",
    "cancel-id-latency.svg",
    "providers-latency.png",
    "providers-latency.svg",
)
_PUBLISH_FIGURE_FILENAMES = FIGURE_FILENAMES[:2]
_PROVIDERS = ("async-hyperliquid", "sdk", "ccxt")
_PUBLISH_ENVIRONMENT_FIELDS = ("network", "python", "platform")
_PUBLISH_VERSION_FIELDS = ("async-hyperliquid", "sdk", "ccxt")
_TOP_LEVEL_FIELDS = frozenset(
    {
        "schema_version",
        "valid",
        "failure_reason",
        "cleanup_ok",
        "started_at",
        "completed_at",
        "config",
        "environment",
        "versions",
        "git",
        "samples",
        "summaries",
    }
)
_CONFIG_FIELDS = frozenset(
    {
        "workload",
        "rounds",
        "warmups",
        "interval_ns",
        "coin",
        "target_notional",
        "buy_multiplier",
        "sell_multiplier",
    }
)
_SUMMARY_FIELDS = frozenset(
    {"count", "median_ns", "mad_ns", "p95_ns", "min_ns", "max_ns"}
)
_SAFE_SCALAR = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+()-]{0,99}\Z")
_CANONICAL_UTC = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z\Z")
_CSV_FIELDS = (
    "suite",
    "provider",
    "operation",
    "round_index",
    "provider_order",
    "duration_ns",
)
_PUBLICATION_LOCK_FILENAME = "benchmark-publication.lock"
_PUBLICATION_REPOSITORY_FAILURE = "benchmark publication repository is not publishable"
_PUBLICATION_LOCKED_FAILURE = "benchmark publication is already in progress"
_PUBLICATION_FAILURE = "benchmark publication failed"


@dataclass(frozen=True, slots=True)
class _PathIdentity:
    device: int
    inode: int
    mode: int


@dataclass(frozen=True, slots=True)
class _OwnedPath:
    path: Path
    identity: _PathIdentity


@dataclass(slots=True)
class _AtomicTextChange:
    path: Path
    snapshot: str
    snapshot_identity: _PathIdentity
    replacement: str
    replacement_identity: _PathIdentity | None = None


@dataclass(slots=True)
class _CleanupOutcome:
    ordinary: list[Exception] = field(default_factory=list)
    control_flow: BaseException | None = None

    def capture(self, error: BaseException, message: str) -> None:
        if isinstance(error, Exception):
            self.ordinary.append(RuntimeError(message))
        else:
            self.control_flow = error


def figure_series(
    report: LiveBenchmarkReport, suite: str
) -> dict[str, dict[str, list[int]]]:
    series: dict[str, dict[str, list[int]]] = {}
    for sample in report["samples"]:
        if sample["suite"] != suite:
            continue
        series.setdefault(sample["operation"], {}).setdefault(
            sample["provider"], []
        ).append(sample["duration_ns"])
    if not series:
        raise BenchmarkFailure("report has no samples for the requested figure")
    return series


def _identity_from_stat(value: os.stat_result) -> _PathIdentity:
    return _PathIdentity(device=value.st_dev, inode=value.st_ino, mode=value.st_mode)


def _lexical_identity(path: Path) -> _PathIdentity | None:
    try:
        return _identity_from_stat(path.lstat())
    except FileNotFoundError:
        return None
    except OSError:
        raise BenchmarkFailure(_PUBLICATION_REPOSITORY_FAILURE) from None


def _matches_identity(path: Path, identity: _PathIdentity) -> bool:
    try:
        current = _identity_from_stat(path.lstat())
    except OSError:
        return False
    return current == identity


def _rename_noreplace_at(
    source_fd: int, source_name: str, destination_fd: int, destination_name: str
) -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    source_bytes = os.fsencode(source_name)
    destination_bytes = os.fsencode(destination_name)
    if sys.platform == "darwin":
        rename = libc.renameatx_np
        rename.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        rename.restype = ctypes.c_int
        result = rename(
            source_fd, source_bytes, destination_fd, destination_bytes, 0x00000004
        )
    elif sys.platform.startswith("linux") and hasattr(libc, "renameat2"):
        rename = libc.renameat2
        rename.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        rename.restype = ctypes.c_int
        result = rename(
            source_fd, source_bytes, destination_fd, destination_bytes, 0x00000001
        )
    else:
        raise OSError(errno.ENOTSUP, "atomic no-replace rename is unavailable")
    if result == 0:
        return
    error_number = ctypes.get_errno()
    if error_number in {errno.EEXIST, errno.ENOTEMPTY}:
        raise FileExistsError(error_number, "destination already exists")
    raise OSError(error_number, "atomic no-replace rename failed")


def _open_pinned_directory(
    path: Path, expected_identity: _PathIdentity | None
) -> tuple[int, _PathIdentity]:
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW
    try:
        fd = os.open(path, flags)
    except OSError:
        raise BenchmarkFailure(_PUBLICATION_REPOSITORY_FAILURE) from None
    try:
        identity = _identity_from_stat(os.fstat(fd))
        if (
            not stat.S_ISDIR(identity.mode)
            or (expected_identity is not None and identity != expected_identity)
            or not _matches_identity(path, identity)
        ):
            raise BenchmarkFailure(_PUBLICATION_REPOSITORY_FAILURE)
    except BaseException as error:
        cleanup = _CleanupOutcome()
        _capture_cleanup(
            cleanup, lambda: os.close(fd), "pinned directory descriptor cleanup failed"
        )
        _raise_with_cleanup(
            error, cleanup, primary_message="pinned directory validation failed"
        )
        raise AssertionError("unreachable")
    return fd, identity


def _atomic_move_noreplace(
    source: Path,
    destination: Path,
    *,
    source_parent_identity: _PathIdentity | None = None,
    destination_parent_identity: _PathIdentity | None = None,
) -> None:
    source_fd: int | None = None
    destination_fd: int | None = None
    primary: BaseException | None = None
    cleanup = _CleanupOutcome()
    try:
        source_fd, source_parent = _open_pinned_directory(
            source.parent, source_parent_identity
        )
        if source.parent == destination.parent:
            if (
                destination_parent_identity is not None
                and source_parent != destination_parent_identity
            ):
                raise BenchmarkFailure(_PUBLICATION_REPOSITORY_FAILURE)
            destination_fd = source_fd
        else:
            destination_fd, _ = _open_pinned_directory(
                destination.parent, destination_parent_identity
            )
        _rename_noreplace_at(source_fd, source.name, destination_fd, destination.name)
    except BaseException as error:
        primary = error
    descriptors = {fd for fd in (source_fd, destination_fd) if fd is not None}
    for fd in descriptors:
        _capture_cleanup(
            cleanup,
            lambda fd=fd: os.close(fd),
            "atomic rename descriptor cleanup failed",
        )
    if primary is not None:
        _raise_with_cleanup(
            primary, cleanup, primary_message="atomic no-replace rename failed"
        )
    if cleanup.control_flow is not None:
        raise cleanup.control_flow from _safe_exception_group(
            "atomic rename cleanup failures", cleanup.ordinary
        )
    if cleanup.ordinary:
        raise OSError("atomic rename descriptor cleanup failed") from (
            _safe_exception_group("atomic rename cleanup failures", cleanup.ordinary)
        )


def _require_kind(path: Path, *, directory: bool) -> _PathIdentity:
    identity = _lexical_identity(path)
    expected = stat.S_ISDIR if directory else stat.S_ISREG
    if identity is None or not expected(identity.mode):
        raise BenchmarkFailure(_PUBLICATION_REPOSITORY_FAILURE)
    return identity


def _read_pinned_text(path: Path, identity: _PathIdentity) -> str:
    if not stat.S_ISREG(identity.mode) or not _matches_identity(path, identity):
        raise BenchmarkFailure(_PUBLICATION_FAILURE)
    try:
        value = path.read_text()
    except (OSError, UnicodeError):
        raise BenchmarkFailure(_PUBLICATION_FAILURE) from None
    if not _matches_identity(path, identity):
        raise BenchmarkFailure(_PUBLICATION_FAILURE)
    return value


def _create_owned_directory(
    path: Path, registry: list[_OwnedPath] | None = None
) -> _OwnedPath:
    if _lexical_identity(path) is not None:
        raise FileExistsError
    created = False
    with _defer_directory_creation_signals():
        try:
            os.mkdir(path)
            created = True
            _after_directory_create(path)
            return _register_owned_directory(path, registry)
        except BaseException as error:
            if not created:
                raise
            cleanup = _CleanupOutcome()
            try:
                _register_owned_directory(path, registry)
            except BaseException as handoff_error:
                cleanup.capture(handoff_error, "directory ownership handoff failed")
            _raise_with_cleanup(
                error, cleanup, primary_message="directory creation handoff interrupted"
            )
            raise AssertionError("unreachable")


def _after_directory_create(path: Path) -> None:
    del path


@contextmanager
def _defer_directory_creation_signals() -> Iterator[None]:
    blocked = {signal.SIGINT}
    previous = signal.pthread_sigmask(signal.SIG_BLOCK, blocked)
    try:
        yield
    finally:
        signal.pthread_sigmask(signal.SIG_SETMASK, previous)


def _register_owned_directory(
    path: Path, registry: list[_OwnedPath] | None
) -> _OwnedPath:
    owned = _OwnedPath(path=path, identity=_require_kind(path, directory=True))
    if registry is not None and owned not in registry:
        registry.append(owned)
    return owned


def _restore_foreign_quarantine(quarantine: Path, original: Path) -> None:
    try:
        _atomic_move_noreplace(quarantine, original)
    except BaseException as error:
        if not isinstance(error, Exception):
            raise


def _quarantine_owned(owned: _OwnedPath) -> _OwnedPath | None:
    if not _matches_identity(owned.path, owned.identity):
        return None
    quarantine = owned.path.with_name(f".{owned.path.name}.{uuid.uuid4().hex}.cleanup")
    try:
        _atomic_move_noreplace(owned.path, quarantine)
    except FileNotFoundError:
        return None
    moved_identity = _lexical_identity(quarantine)
    if moved_identity != owned.identity:
        _restore_foreign_quarantine(quarantine, owned.path)
        return None
    return _OwnedPath(quarantine, owned.identity)


def _remove_owned_directory(owned: _OwnedPath) -> None:
    quarantined = _quarantine_owned(owned)
    if quarantined is None:
        return
    shutil.rmtree(quarantined.path)


def _remove_owned_empty_directory(owned: _OwnedPath) -> None:
    quarantined = _quarantine_owned(owned)
    if quarantined is None:
        return
    try:
        if any(quarantined.path.iterdir()):
            _restore_foreign_quarantine(quarantined.path, owned.path)
            return
        os.rmdir(quarantined.path)
    except OSError:
        _restore_foreign_quarantine(quarantined.path, owned.path)
        raise


def _remove_owned_file(owned: _OwnedPath) -> None:
    quarantined = _quarantine_owned(owned)
    if quarantined is None:
        return
    os.unlink(quarantined.path)


def _capture_cleanup(outcome: _CleanupOutcome, operation: Any, message: str) -> None:
    try:
        operation()
    except BaseException as error:
        outcome.capture(error, message)


def _safe_exception_group(
    message: str, ordinary: Sequence[Exception]
) -> ExceptionGroup:
    return ExceptionGroup(message, list(ordinary))


def _raise_with_cleanup(
    primary: BaseException, cleanup: _CleanupOutcome, *, primary_message: str
) -> None:
    safe_failures = [RuntimeError(primary_message), *cleanup.ordinary]
    control_flow = cleanup.control_flow
    if control_flow is None and not isinstance(primary, Exception):
        control_flow = primary
    if control_flow is not None:
        if safe_failures:
            raise control_flow from _safe_exception_group(
                "cleanup failures", safe_failures
            )
        raise control_flow
    raise primary from _safe_exception_group("cleanup failures", safe_failures)


def _prepare_atomic_text(change: _AtomicTextChange) -> _OwnedPath:
    temporary = change.path.with_name(f".{change.path.name}.{uuid.uuid4().hex}.tmp")
    handle: Any | None = None
    owned: _OwnedPath | None = None
    primary: BaseException | None = None
    cleanup = _CleanupOutcome()
    try:
        handle = temporary.open("x")
        owned = _OwnedPath(
            path=temporary, identity=_identity_from_stat(os.fstat(handle.fileno()))
        )
        handle.write(change.replacement)
        handle.flush()
        os.fsync(handle.fileno())
    except BaseException as error:
        primary = error
    if handle is not None:
        try:
            handle.close()
        except BaseException as error:
            if primary is None:
                primary = error
            else:
                cleanup.capture(error, "atomic temporary close failed")
    if primary is not None:
        if owned is not None:
            _capture_cleanup(
                cleanup,
                lambda: _remove_owned_file(owned),
                "atomic temporary cleanup failed",
            )
        _raise_with_cleanup(
            primary, cleanup, primary_message="atomic text preparation failed"
        )
        raise AssertionError("unreachable")
    if owned is None:
        raise AssertionError("atomic temporary was not created")
    return owned


def _atomic_text_if_unchanged(change: _AtomicTextChange) -> None:
    temporary = _prepare_atomic_text(change)
    change.replacement_identity = temporary.identity
    try:
        current = _read_pinned_text(change.path, change.snapshot_identity)
        if current != change.snapshot:
            raise BenchmarkFailure(_PUBLICATION_FAILURE)
        os.replace(temporary.path, change.path)
    except BaseException as error:
        cleanup = _CleanupOutcome()
        _capture_cleanup(
            cleanup,
            lambda: _remove_owned_file(temporary),
            "atomic temporary cleanup failed",
        )
        _raise_with_cleanup(
            error, cleanup, primary_message="atomic text replacement failed"
        )


def _atomic_text(path: Path, content: str) -> None:
    identity = _require_kind(path, directory=False)
    change = _AtomicTextChange(
        path=path,
        snapshot=_read_pinned_text(path, identity),
        snapshot_identity=identity,
        replacement=content,
    )
    _atomic_text_if_unchanged(change)


def _git_output(repository_root: Path, *arguments: str) -> str:
    try:
        completed = subprocess.run(
            ("git", *arguments),
            cwd=repository_root,
            check=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except (OSError, UnicodeError):
        raise BenchmarkFailure(_PUBLICATION_REPOSITORY_FAILURE) from None
    if completed.returncode != 0:
        raise BenchmarkFailure(_PUBLICATION_REPOSITORY_FAILURE) from None
    return completed.stdout.rstrip("\n")


def _resolve_repository_root(repository_root: Path) -> tuple[Path, Path]:
    try:
        resolved_root = repository_root.resolve(strict=True)
    except OSError:
        raise BenchmarkFailure(_PUBLICATION_REPOSITORY_FAILURE) from None
    git_dir_text = _git_output(resolved_root, "rev-parse", "--absolute-git-dir")
    try:
        git_dir = Path(git_dir_text).resolve(strict=True)
    except OSError:
        raise BenchmarkFailure(_PUBLICATION_REPOSITORY_FAILURE) from None
    if not git_dir.is_dir():
        raise BenchmarkFailure(_PUBLICATION_REPOSITORY_FAILURE)
    return resolved_root, git_dir


def _close_lock(fd: int, primary: BaseException | None) -> None:
    try:
        os.close(fd)
    except BaseException as error:
        if primary is None:
            if isinstance(error, Exception):
                raise BenchmarkFailure(_PUBLICATION_REPOSITORY_FAILURE) from (
                    _safe_exception_group(
                        "lock release failures",
                        [RuntimeError("publication lock release failed")],
                    )
                )
            raise
        cleanup = _CleanupOutcome()
        cleanup.capture(error, "publication lock release failed")
        _raise_with_cleanup(
            primary, cleanup, primary_message="publication operation failed"
        )


@contextmanager
def _publication_lock(
    repository_root: Path,
    on_success_release_error: Callable[[BaseException], None] | None = None,
) -> Iterator[tuple[Path, Path]]:
    resolved_root, git_dir = _resolve_repository_root(repository_root)
    lock_path = git_dir / _PUBLICATION_LOCK_FILENAME
    flags = os.O_RDWR | os.O_CREAT | os.O_CLOEXEC | os.O_NOFOLLOW
    try:
        lock_fd = os.open(lock_path, flags, 0o600)
    except OSError:
        raise BenchmarkFailure(_PUBLICATION_REPOSITORY_FAILURE) from None
    try:
        try:
            lock_stat = os.fstat(lock_fd)
        except OSError:
            raise BenchmarkFailure(_PUBLICATION_REPOSITORY_FAILURE) from None
        if not stat.S_ISREG(lock_stat.st_mode):
            raise BenchmarkFailure(_PUBLICATION_REPOSITORY_FAILURE)
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            if error.errno in {errno.EACCES, errno.EAGAIN}:
                raise BenchmarkFailure(_PUBLICATION_LOCKED_FAILURE) from None
            raise BenchmarkFailure(_PUBLICATION_REPOSITORY_FAILURE) from None
        yield resolved_root, git_dir
    except BaseException as error:
        _close_lock(lock_fd, error)
        raise
    else:
        try:
            _close_lock(lock_fd, None)
        except BaseException as error:
            if on_success_release_error is not None:
                on_success_release_error(error)
            raise


def _verify_repository(
    repository_root: Path,
    git_dir: Path,
    report: LiveBenchmarkReport,
    *,
    allowed_status: frozenset[str] = frozenset(),
) -> None:
    current_root, current_git_dir = _resolve_repository_root(repository_root)
    inside_worktree = _git_output(repository_root, "rev-parse", "--is-inside-work-tree")
    top_level_text = _git_output(repository_root, "rev-parse", "--show-toplevel")
    status_before = _git_output(
        repository_root, "status", "--porcelain=v1", "--untracked-files=all"
    )
    head_before = _git_output(repository_root, "rev-parse", "--verify", "HEAD")
    status_after = _git_output(
        repository_root, "status", "--porcelain=v1", "--untracked-files=all"
    )
    head_after = _git_output(repository_root, "rev-parse", "--verify", "HEAD")
    try:
        top_level = Path(top_level_text).resolve(strict=True)
    except OSError:
        raise BenchmarkFailure(_PUBLICATION_REPOSITORY_FAILURE) from None
    if (
        inside_worktree != "true"
        or current_root != repository_root
        or current_git_dir != git_dir
        or top_level != repository_root
        or frozenset(status_before.splitlines()) != allowed_status
        or frozenset(status_after.splitlines()) != allowed_status
        or report["git"]["dirty"] is not False
        or head_before != report["git"]["revision"]
        or head_after != report["git"]["revision"]
    ):
        raise BenchmarkFailure(_PUBLICATION_REPOSITORY_FAILURE)


def write_csv(report: LiveBenchmarkReport, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    destination = output_dir / "samples.csv"
    temporary = output_dir / ".samples.csv.tmp"
    try:
        with temporary.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=_CSV_FIELDS, lineterminator="\n")
            writer.writeheader()
            writer.writerows(report["samples"])
        temporary.replace(destination)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return destination


def _milliseconds(values: Sequence[int]) -> list[float]:
    return [value / 1_000_000 for value in values]


def _distribution_panel(
    axis: Any, values: Sequence[Sequence[int]], labels: Sequence[str], *, title: str
) -> None:
    milliseconds = [_milliseconds(samples) for samples in values]
    axis.boxplot(milliseconds, tick_labels=labels, showfliers=False)
    for position, samples in enumerate(milliseconds, start=1):
        offsets = [((index % 7) - 3) * 0.018 for index in range(len(samples))]
        axis.scatter(
            [position + offset for offset in offsets],
            samples,
            alpha=0.55,
            s=16,
            zorder=3,
        )
    axis.set_title(title)
    axis.set_ylabel("Latency (ms)")
    axis.grid(axis="y", alpha=0.25)


def _percentile(values: Sequence[int], fraction: float) -> float:
    ordered = sorted(values)
    index = max(0, math.ceil(fraction * len(ordered)) - 1)
    return ordered[index] / 1_000_000


def chart_statistics(values: Sequence[int]) -> tuple[float, float]:
    if not values:
        raise BenchmarkFailure("chart series must not be empty")
    return statistics.median(values) / 1_000_000, _percentile(values, 0.95)


def _comparison_panel(
    axis: Any, values: Sequence[Sequence[int]], labels: Sequence[str], *, title: str
) -> None:
    statistics_by_series = [chart_statistics(samples) for samples in values]
    medians = [summary[0] for summary in statistics_by_series]
    p95s = [summary[1] for summary in statistics_by_series]
    positions = list(range(len(labels)))
    median_bars = axis.bar(
        [position - 0.19 for position in positions], medians, width=0.38, label="median"
    )
    p95_bars = axis.bar(
        [position + 0.19 for position in positions], p95s, width=0.38, label="p95"
    )
    axis.bar_label(median_bars, fmt="%.2f", fontsize=8, padding=2)
    axis.bar_label(p95_bars, fmt="%.2f", fontsize=8, padding=2)
    axis.set_xticks(positions, labels)
    axis.set_title(title)
    axis.set_ylabel("Latency (ms)")
    axis.legend()
    axis.grid(axis="y", alpha=0.25)


def _write_figure(figure: Any, path: Path) -> None:
    figure.savefig(path, dpi=160 if path.suffix == ".png" else None)
    if path.suffix == ".svg":
        normalized = "\n".join(line.rstrip() for line in path.read_text().splitlines())
        path.write_text(f"{normalized}\n")


def write_figures(report: LiveBenchmarkReport, output_dir: Path) -> tuple[Path, ...]:
    import matplotlib

    matplotlib.use("Agg")
    from matplotlib import pyplot as plt

    output_dir.mkdir(parents=True, exist_ok=True)
    suites = {sample["suite"] for sample in report["samples"]}
    paths: list[Path] = []

    if "cancel-id" in suites:
        cancel = figure_series(report, "cancel-id")
        cancel_operations = ("cancel_by_oid", "cancel_by_cloid")
        cancel_values = [
            cancel[operation]["async-hyperliquid"] for operation in cancel_operations
        ]
        round_max_values = _round_max_values(report)
        cancel_round_max_values = [
            round_max_values[operation] for operation in cancel_operations
        ]
        cancel_labels = ("OID", "CLOID")
        cancel_figure, cancel_axes = plt.subplots(2, 2, figsize=(12, 10))
        _distribution_panel(
            cancel_axes[0][0],
            cancel_values,
            cancel_labels,
            title="Individual cancel request distribution",
        )
        _comparison_panel(
            cancel_axes[0][1],
            cancel_values,
            cancel_labels,
            title="Individual request median and p95",
        )
        _distribution_panel(
            cancel_axes[1][0],
            cancel_round_max_values,
            cancel_labels,
            title="Per-round method maximum distribution",
        )
        _comparison_panel(
            cancel_axes[1][1],
            cancel_round_max_values,
            cancel_labels,
            title="Per-round maximum median and p95",
        )
        cancel_figure.tight_layout()
        cancel_paths = tuple(output_dir / filename for filename in FIGURE_FILENAMES[:2])
        for path in cancel_paths:
            _write_figure(cancel_figure, path)
        plt.close(cancel_figure)
        paths.extend(cancel_paths)

    if "providers" in suites:
        providers = figure_series(report, "providers")
        operations = ("place_batch_2", "cancel_batch_2_by_oid")
        titles = ("Place two ALO orders", "Cancel two orders by OID")
        provider_figure, provider_axes = plt.subplots(2, 2, figsize=(14, 10))
        for row, (operation, title) in enumerate(zip(operations, titles, strict=True)):
            operation_values = [providers[operation][name] for name in _PROVIDERS]
            _distribution_panel(
                provider_axes[row][0],
                operation_values,
                _PROVIDERS,
                title=f"{title}: distribution",
            )
            _comparison_panel(
                provider_axes[row][1],
                operation_values,
                _PROVIDERS,
                title=f"{title}: median and p95",
            )
        provider_figure.tight_layout()
        provider_paths = tuple(
            output_dir / filename for filename in FIGURE_FILENAMES[2:]
        )
        for path in provider_paths:
            _write_figure(provider_figure, path)
        plt.close(provider_figure)
        paths.extend(provider_paths)

    if not paths:
        raise BenchmarkFailure("report has no supported figure samples")
    return tuple(paths)


def _expected_counts() -> Counter[tuple[str, str, str]]:
    return Counter(
        {
            ("cancel-id", "async-hyperliquid", "cancel_by_oid"): 300,
            ("cancel-id", "async-hyperliquid", "cancel_by_cloid"): 300,
        }
    )


def _is_git_revision(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 40
        and all(character in "0123456789abcdef" for character in value)
    )


def _is_safe_scalar(value: object) -> bool:
    return isinstance(value, str) and _SAFE_SCALAR.fullmatch(value) is not None


def _parse_canonical_utc(value: object) -> datetime | None:
    if not isinstance(value, str) or _CANONICAL_UTC.fullmatch(value) is None:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError:
        return None


def _is_exact_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_exact_float(value: object) -> bool:
    return isinstance(value, float) and math.isfinite(value)


def _has_exact_keys(value: object, keys: frozenset[str]) -> bool:
    return isinstance(value, Mapping) and set(value) == keys


def _has_exact_summary_shape(summaries: object) -> bool:
    if not isinstance(summaries, Mapping):
        return False
    summaries = cast(Mapping[Any, object], summaries)
    if set(summaries) != {"cancel-id"}:
        return False
    suite = summaries.get("cancel-id")
    if not isinstance(suite, Mapping) or set(suite) != {
        "cancel_by_oid",
        "cancel_by_cloid",
    }:
        return False
    suite = cast(Mapping[str, object], suite)
    for operation in ("cancel_by_oid", "cancel_by_cloid"):
        providers = suite.get(operation)
        if not isinstance(providers, Mapping) or set(providers) != {
            "async-hyperliquid"
        }:
            return False
        providers = cast(Mapping[str, object], providers)
        summary = providers.get("async-hyperliquid")
        if not isinstance(summary, Mapping) or not _has_exact_keys(
            summary, _SUMMARY_FIELDS
        ):
            return False
        summary = cast(Mapping[Any, object], summary)
        if (
            not _is_exact_int(summary.get("count"))
            or not _is_exact_float(summary.get("median_ns"))
            or not _is_exact_float(summary.get("mad_ns"))
            or not _is_exact_float(summary.get("p95_ns"))
            or not _is_exact_int(summary.get("min_ns"))
            or not _is_exact_int(summary.get("max_ns"))
        ):
            return False
    return True


def validate_publishable(report: LiveBenchmarkReport) -> None:
    try:
        if not isinstance(report, Mapping):
            raise BenchmarkFailure("report schema is not publishable")
        if not _has_exact_keys(report, _TOP_LEVEL_FIELDS):
            raise BenchmarkFailure("report schema is not publishable")
        config = report["config"]
        versions = report["versions"]
        git = report["git"]
        environment = report["environment"]
        samples = report["samples"]
        summaries = report["summaries"]
        if (
            not isinstance(config, Mapping)
            or not isinstance(versions, Mapping)
            or not isinstance(git, Mapping)
            or not isinstance(environment, Mapping)
            or not isinstance(samples, list)
            or not isinstance(summaries, Mapping)
            or not all(isinstance(sample, Mapping) for sample in samples)
            or isinstance(report["schema_version"], bool)
            or not isinstance(report["schema_version"], int)
            or not isinstance(report["valid"], bool)
            or not isinstance(report["cleanup_ok"], bool)
            or not isinstance(report["started_at"], str)
            or not isinstance(report["completed_at"], str)
            or (
                report["failure_reason"] is not None
                and not isinstance(report["failure_reason"], str)
            )
        ):
            raise BenchmarkFailure("report schema is not publishable")
        if report["schema_version"] != LIVE_REPORT_SCHEMA_VERSION:
            raise BenchmarkFailure("report is not publishable")
        started_at = _parse_canonical_utc(report["started_at"])
        completed_at = _parse_canonical_utc(report["completed_at"])
        if (
            started_at is None
            or completed_at is None
            or started_at > completed_at
            or not _has_exact_keys(config, _CONFIG_FIELDS)
            or set(versions) != set(_PUBLISH_VERSION_FIELDS)
            or set(git) != {"revision", "dirty"}
            or set(environment) != set(_PUBLISH_ENVIRONMENT_FIELDS)
            or not _has_exact_summary_shape(summaries)
        ):
            raise BenchmarkFailure("report schema is not publishable")
        if (
            not report["valid"]
            or report["failure_reason"] is not None
            or not report["cleanup_ok"]
            or config.get("workload") != CONCURRENT_CANCEL_WORKLOAD
            or not _is_exact_int(config.get("rounds"))
            or config.get("rounds") != 30
            or not _is_exact_int(config.get("warmups"))
            or config.get("warmups") != 3
            or not _is_exact_int(config.get("interval_ns"))
            or config.get("interval_ns") != 250_000_000
            or config.get("coin") != "BTC"
            or not _is_exact_float(config.get("target_notional"))
            or config.get("target_notional") != 11.0
            or not _is_exact_float(config.get("buy_multiplier"))
            or config.get("buy_multiplier") != 0.9
            or not _is_exact_float(config.get("sell_multiplier"))
            or config.get("sell_multiplier") != 1.1
            or tuple(versions.get(key) for key in _PUBLISH_VERSION_FIELDS)
            != ("1.0.0rc1", "0.24.0", "4.5.71")
            or not all(_is_safe_scalar(value) for value in versions.values())
            or not all(_is_safe_scalar(value) for value in environment.values())
            or environment.get("network") != "testnet"
            or git.get("dirty") is not False
            or not _is_git_revision(git.get("revision"))
        ):
            raise BenchmarkFailure("report is not publishable")
        grouped: dict[tuple[str, str, str], list[int]] = {}
        round_samples: dict[int, dict[str, list[dict[str, object]]]] = {}
        for sample in samples:
            if set(sample) != set(_CSV_FIELDS):
                raise BenchmarkFailure("report sample schema is not publishable")
            suite = sample["suite"]
            provider = sample["provider"]
            operation = sample["operation"]
            round_index = sample["round_index"]
            provider_order = sample["provider_order"]
            duration_ns = sample["duration_ns"]
            if (
                suite != "cancel-id"
                or provider != "async-hyperliquid"
                or operation not in {"cancel_by_oid", "cancel_by_cloid"}
                or isinstance(round_index, bool)
                or not isinstance(round_index, int)
                or isinstance(provider_order, bool)
                or not isinstance(provider_order, int)
                or provider_order < 0
                or provider_order > 19
                or isinstance(duration_ns, bool)
                or not isinstance(duration_ns, int)
                or duration_ns < 1
            ):
                raise BenchmarkFailure("report sample values are not publishable")
            key = (suite, provider, operation)
            grouped.setdefault(key, []).append(duration_ns)
            round_samples.setdefault(round_index, {}).setdefault(operation, []).append(
                cast(dict[str, object], sample)
            )

        actual = Counter(
            (sample["suite"], sample["provider"], sample["operation"])
            for sample in samples
        )
        if actual != _expected_counts():
            raise BenchmarkFailure("report sample shape is not publishable")

        expected_rounds = set(range(config["rounds"]))
        if set(round_samples) != expected_rounds:
            raise BenchmarkFailure("report measured rounds are not publishable")
        warmups = config["warmups"]
        for round_index, operations in round_samples.items():
            expected_oid_even = (warmups + round_index) % 2 == 0
            slots: set[int] = set()
            for operation in ("cancel_by_oid", "cancel_by_cloid"):
                samples = operations.get(operation, [])
                if len(samples) != 10:
                    raise BenchmarkFailure("report sample shape is not publishable")
                for sample in samples:
                    slot = cast(int, sample["provider_order"])
                    if slot in slots:
                        raise BenchmarkFailure("report sample shape is not publishable")
                    slots.add(slot)
                    expected_even = (
                        expected_oid_even
                        if operation == "cancel_by_oid"
                        else not expected_oid_even
                    )
                    if (slot % 2 == 0) != expected_even:
                        raise BenchmarkFailure(
                            "report sample values are not publishable"
                        )
            if set(operations) != {"cancel_by_oid", "cancel_by_cloid"} or slots != set(
                range(20)
            ):
                raise BenchmarkFailure("report sample shape is not publishable")

        rebuilt: dict[str, dict[str, dict[str, LatencySummary]]] = {}
        for (suite, provider, operation), values in grouped.items():
            rebuilt.setdefault(suite, {}).setdefault(operation, {})[provider] = (
                summarize_ns(values)
            )
        if summaries != rebuilt:
            raise BenchmarkFailure("report summaries are not publishable")
        assert_report_is_sanitized(
            cast(Mapping[str, object], report), forbidden_values=()
        )
    except (KeyError, TypeError, ValueError) as error:
        raise BenchmarkFailure("report schema is not publishable") from error


def _summary(
    report: LiveBenchmarkReport, suite: str, operation: str, provider: str
) -> LatencySummary:
    try:
        return report["summaries"][suite][operation][provider]
    except KeyError as error:
        raise BenchmarkFailure("report summaries are not publishable") from error


def _ms(value: float | int) -> str:
    return f"{value / 1_000_000:.2f}"


def _round_max_values(report: LiveBenchmarkReport) -> dict[str, list[int]]:
    grouped: dict[str, dict[int, list[int]]] = {}
    for sample in report["samples"]:
        if sample["suite"] != "cancel-id" or sample["provider"] != "async-hyperliquid":
            continue
        grouped.setdefault(sample["operation"], {}).setdefault(
            sample["round_index"], []
        ).append(sample["duration_ns"])
    return {
        operation: [max(values) for _, values in sorted(rounds.items())]
        for operation, rounds in grouped.items()
    }


def round_max_summaries(report: LiveBenchmarkReport) -> dict[str, LatencySummary]:
    return {
        operation: summarize_ns(values)
        for operation, values in _round_max_values(report).items()
    }


def _detail_markdown(report: LiveBenchmarkReport, artifact_dir: str) -> str:
    round_maximums = round_max_summaries(report)
    lines = [
        "## Published live Exchange benchmark",
        "",
        f"Validated testnet run completed `{report['completed_at']}`. The runner used",
        "three warmup rounds, 30 measured rounds, and a maximum controlled rate of",
        "240 weight/minute. Initialization, market metadata, mid lookup, pacing, and",
        "cleanup are excluded from measured latency. Each measured round uses",
        "concurrency=20 (10 OID + 10 CLOID) single-order cancellation requests.",
        "",
        "| Environment | Value |",
        "|---|---|",
    ]
    for key in _PUBLISH_ENVIRONMENT_FIELDS:
        value = report["environment"][key]
        lines.append(f"| {key} | {value} |")
    for key in _PUBLISH_VERSION_FIELDS:
        value = report["versions"][key]
        lines.append(f"| {key} | {value} |")
    lines.extend(
        [
            "",
            "### OID versus CLOID cancellation",
            "",
            "All 300 individual request latencies per identifier are shown below.",
            "",
            "| Identifier | Median (ms) | MAD (ms) | p95 (ms) | Min (ms) | Max (ms) |",
            "|---|---:|---:|---:|---:|---:|",
        ]
    )
    for operation, label in (("cancel_by_oid", "OID"), ("cancel_by_cloid", "CLOID")):
        summary = _summary(report, "cancel-id", operation, "async-hyperliquid")
        lines.append(
            f"| {label} | {_ms(summary['median_ns'])} | {_ms(summary['mad_ns'])} | "
            f"{_ms(summary['p95_ns'])} | {_ms(summary['min_ns'])} | {_ms(summary['max_ns'])} |"
        )
    lines.extend(
        [
            "",
            "### Per-round method maxima",
            "",
            "Each value is the slowest of that method's ten requests in one measured round.",
            "",
            "| Identifier | Rounds | Median (ms) | p95 (ms) |",
            "|---|---:|---:|---:|",
        ]
    )
    for operation, label in (("cancel_by_oid", "OID"), ("cancel_by_cloid", "CLOID")):
        summary = round_maximums[operation]
        lines.append(
            f"| {label} | {summary['count']} | {_ms(summary['median_ns'])} | "
            f"{_ms(summary['p95_ns'])} |"
        )
    lines.extend(
        [
            "",
            f"![OID and CLOID latency](results/{artifact_dir}/cancel-id-latency.svg)",
            "Artifacts: [sanitized JSON](results/"
            f"{artifact_dir}/report.json), [sample CSV](results/{artifact_dir}/samples.csv).",
            "",
            "These measurements describe one testnet run, not exchange capacity. Shared-IP traffic, "
            "geography, testnet load, dependency versions, and network conditions can change results.",
        ]
    )
    return "\n".join(lines)


def _overall_markdown(report: LiveBenchmarkReport) -> str:
    round_maximums = round_max_summaries(report)
    lines = [
        "#### Published live Exchange result",
        "",
        "The validated testnet run uses concurrency=20 (10 OID + 10 CLOID) single-order "
        "cancellation requests per measured round.",
        "",
        "| Identifier | Individual median (ms) | Individual p95 (ms) | Round-max median (ms) | Round-max p95 (ms) |",
        "|---|---:|---:|---:|---:|",
    ]
    for operation, label in (("cancel_by_oid", "OID"), ("cancel_by_cloid", "CLOID")):
        individual = _summary(report, "cancel-id", operation, "async-hyperliquid")
        maximum = round_maximums[operation]
        lines.append(
            f"| {label} | {_ms(individual['median_ns'])} | {_ms(individual['p95_ns'])} | "
            f"{_ms(maximum['median_ns'])} | {_ms(maximum['p95_ns'])} |"
        )
    lines.extend(
        [
            "",
            "See the [detailed methodology, distributions, and artifacts](benchmarks/README.md#published-live-exchange-benchmark).",
        ]
    )
    return "\n".join(lines)


def _replace_marker(text: str, start: str, end: str, body: str) -> str:
    if text.count(start) != 1 or text.count(end) != 1:
        raise BenchmarkFailure("README marker pair must occur exactly once")
    start_index = text.index(start) + len(start)
    end_index = text.index(end)
    if start_index >= end_index:
        raise BenchmarkFailure("README marker pair is out of order")
    return f"{text[:start_index]}\n{body.rstrip()}\n{text[end_index:]}"


def _load_report(path: Path) -> LiveBenchmarkReport:
    try:
        decoded = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise BenchmarkFailure("benchmark report is not publishable") from error
    if not isinstance(decoded, dict):
        raise BenchmarkFailure("benchmark report is not publishable")
    return cast(LiveBenchmarkReport, decoded)


def _artifact_timestamp(completed_at: str) -> str:
    try:
        parsed = datetime.fromisoformat(completed_at.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("completion time must include a timezone")
        return parsed.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    except (ValueError, OverflowError) as error:
        raise BenchmarkFailure("report completion time is not publishable") from error


def _compensate_publication(
    *,
    root_change: _AtomicTextChange,
    benchmark_change: _AtomicTextChange,
    staging: _OwnedPath | None,
    destination: Path,
    results: _OwnedPath | None,
) -> _CleanupOutcome:
    outcome = _CleanupOutcome()
    for change, failure_message in (
        (root_change, "root README rollback failed"),
        (benchmark_change, "benchmark README rollback failed"),
    ):
        replacement_identity = change.replacement_identity
        if replacement_identity is None or not _matches_identity(
            change.path, replacement_identity
        ):
            continue
        _capture_cleanup(
            outcome,
            lambda change=change: _atomic_text(change.path, change.snapshot),
            failure_message,
        )

    if staging is not None and _matches_identity(destination, staging.identity):
        _capture_cleanup(
            outcome,
            lambda: _remove_owned_directory(_OwnedPath(destination, staging.identity)),
            "final artifact cleanup failed",
        )
    if staging is not None and _matches_identity(staging.path, staging.identity):
        _capture_cleanup(
            outcome,
            lambda: _remove_owned_directory(staging),
            "staging artifact cleanup failed",
        )
    if results is not None:
        _capture_cleanup(
            outcome,
            lambda: _remove_owned_empty_directory(results),
            "results directory cleanup failed",
        )
    return outcome


def _raise_publication_failure(error: BaseException, cleanup: _CleanupOutcome) -> None:
    control_flow = cleanup.control_flow
    if control_flow is None and not isinstance(error, Exception):
        control_flow = error
    safe_failures = [RuntimeError("publication operation failed"), *cleanup.ordinary]
    if control_flow is not None:
        raise control_flow from _safe_exception_group(
            "publication failures", safe_failures
        )
    if isinstance(error, BenchmarkFailure) and str(error) in {
        _PUBLICATION_REPOSITORY_FAILURE,
        "published benchmark timestamp already exists",
    }:
        raise error from _safe_exception_group("publication failures", safe_failures)
    raise BenchmarkFailure(_PUBLICATION_FAILURE) from _safe_exception_group(
        "publication failures", safe_failures
    )


def _require_publication_namespace(
    *,
    benchmarks_dir: _OwnedPath,
    results_dir: _OwnedPath,
    staging: _OwnedPath,
    destination: Path,
) -> None:
    if (
        not _matches_identity(benchmarks_dir.path, benchmarks_dir.identity)
        or not _matches_identity(results_dir.path, results_dir.identity)
        or not _matches_identity(staging.path, staging.identity)
    ):
        raise BenchmarkFailure(_PUBLICATION_FAILURE)
    if _lexical_identity(destination) is not None:
        raise BenchmarkFailure("published benchmark timestamp already exists")


def publish_report(report_path: Path, repository_root: Path) -> Path:
    """Publish with catchable-interruption compensation.

    SIGKILL or power loss between the two README replacements remains a residual
    limitation because two independent files cannot form one atomic transaction.
    """
    report = _load_report(report_path)
    validate_publishable(report)
    source_dir = report_path.parent
    required = {"report.json", "samples.csv", *_PUBLISH_FIGURE_FILENAMES}
    if any(not (source_dir / filename).is_file() for filename in required):
        raise BenchmarkFailure("benchmark artifacts are not publishable")
    timestamp = _artifact_timestamp(report["completed_at"])
    root_change: _AtomicTextChange | None = None
    benchmark_change: _AtomicTextChange | None = None
    destination: Path | None = None
    results_owned: _OwnedPath | None = None
    staging: _OwnedPath | None = None
    results_registry: list[_OwnedPath] = []
    staging_registry: list[_OwnedPath] = []

    def compensate_successful_release(error: BaseException) -> None:
        assert root_change is not None
        assert benchmark_change is not None
        assert destination is not None
        cleanup = _compensate_publication(
            root_change=root_change,
            benchmark_change=benchmark_change,
            staging=staging or next(iter(staging_registry), None),
            destination=destination,
            results=results_owned or next(iter(results_registry), None),
        )
        _raise_publication_failure(error, cleanup)

    with _publication_lock(repository_root, compensate_successful_release) as (
        locked_root,
        git_dir,
    ):
        _verify_repository(locked_root, git_dir, report)
        git_dir_identity = _require_kind(git_dir, directory=True)
        benchmarks_dir_path = locked_root / "benchmarks"
        benchmarks_dir = _OwnedPath(
            benchmarks_dir_path, _require_kind(benchmarks_dir_path, directory=True)
        )
        root_readme = locked_root / "README.md"
        benchmark_readme = benchmarks_dir.path / "README.md"
        root_identity = _require_kind(root_readme, directory=False)
        benchmark_identity = _require_kind(benchmark_readme, directory=False)
        root_text = _read_pinned_text(root_readme, root_identity)
        benchmark_text = _read_pinned_text(benchmark_readme, benchmark_identity)

        rendered_root = _replace_marker(
            root_text, OVERALL_START, OVERALL_END, _overall_markdown(report)
        )
        rendered_benchmark = _replace_marker(
            benchmark_text,
            DETAIL_START,
            DETAIL_END,
            _detail_markdown(report, timestamp),
        )
        root_change = _AtomicTextChange(
            root_readme, root_text, root_identity, rendered_root
        )
        benchmark_change = _AtomicTextChange(
            benchmark_readme, benchmark_text, benchmark_identity, rendered_benchmark
        )
        results_path = benchmarks_dir.path / "results"
        results_identity = _lexical_identity(results_path)
        if results_identity is not None and not stat.S_ISDIR(results_identity.mode):
            raise BenchmarkFailure(_PUBLICATION_REPOSITORY_FAILURE)
        destination = results_path / timestamp
        if _lexical_identity(destination) is not None:
            raise BenchmarkFailure("published benchmark timestamp already exists")

        try:
            if results_identity is None:
                results_owned = _create_owned_directory(results_path, results_registry)
                results_dir = results_owned
            else:
                results_dir = _OwnedPath(results_path, results_identity)
            staging_path = git_dir / (
                f"benchmark-publication.{timestamp}.{uuid.uuid4().hex}.staging"
            )
            staging = _create_owned_directory(staging_path, staging_registry)
            if staging.identity.device != results_dir.identity.device:
                raise BenchmarkFailure(_PUBLICATION_FAILURE)

            write_report(report, staging.path, forbidden_values=())
            write_csv(report, staging.path)
            write_figures(report, staging.path)
            if not _matches_identity(staging.path, staging.identity):
                raise BenchmarkFailure(_PUBLICATION_FAILURE)
            if {path.name for path in staging.path.iterdir()} != required:
                raise BenchmarkFailure(_PUBLICATION_FAILURE)

            _require_publication_namespace(
                benchmarks_dir=benchmarks_dir,
                results_dir=results_dir,
                staging=staging,
                destination=destination,
            )
            _verify_repository(locked_root, git_dir, report)
            _atomic_text_if_unchanged(benchmark_change)

            _verify_repository(
                locked_root,
                git_dir,
                report,
                allowed_status=frozenset({" M benchmarks/README.md"}),
            )
            if not _matches_identity(
                benchmark_readme,
                cast(_PathIdentity, benchmark_change.replacement_identity),
            ):
                raise BenchmarkFailure(_PUBLICATION_FAILURE)
            _atomic_text_if_unchanged(root_change)

            _require_publication_namespace(
                benchmarks_dir=benchmarks_dir,
                results_dir=results_dir,
                staging=staging,
                destination=destination,
            )
            if not _matches_identity(
                root_readme, cast(_PathIdentity, root_change.replacement_identity)
            ) or not _matches_identity(
                benchmark_readme,
                cast(_PathIdentity, benchmark_change.replacement_identity),
            ):
                raise BenchmarkFailure(_PUBLICATION_FAILURE)
            _verify_repository(
                locked_root,
                git_dir,
                report,
                allowed_status=frozenset({" M README.md", " M benchmarks/README.md"}),
            )
            try:
                _atomic_move_noreplace(
                    staging.path,
                    destination,
                    source_parent_identity=git_dir_identity,
                    destination_parent_identity=results_dir.identity,
                )
            except FileExistsError:
                raise BenchmarkFailure(
                    "published benchmark timestamp already exists"
                ) from None
        except BaseException as error:
            cleanup = _compensate_publication(
                root_change=root_change,
                benchmark_change=benchmark_change,
                staging=staging or next(iter(staging_registry), None),
                destination=destination,
                results=results_owned or next(iter(results_registry), None),
            )
            _raise_publication_failure(error, cleanup)
        return destination
