import asyncio
import csv
import errno
import fcntl
import os
import signal
import subprocess
from pathlib import Path
from collections.abc import Callable
from typing import Any, cast

import pytest

import benchmarks.live.reporting as reporting
from benchmarks.live.models import (
    BenchmarkConfig,
    BenchmarkFailure,
    CONCURRENT_CANCEL_WORKLOAD,
    GitMetadata,
    LatencySample,
    LiveBenchmarkReport,
)
from benchmarks.live.reporting import (
    DETAIL_END,
    DETAIL_START,
    FIGURE_FILENAMES,
    OVERALL_END,
    OVERALL_START,
    chart_statistics,
    figure_series,
    publish_report,
    round_max_summaries,
    validate_publishable,
    write_csv,
    write_figures,
)
from benchmarks.live.results import SampleRecorder, write_report


PROVIDERS = ("ccxt", "sdk", "async-hyperliquid")


def _valid_report(*, revision: str = "a" * 40) -> LiveBenchmarkReport:
    config = BenchmarkConfig()
    recorder = SampleRecorder(
        config=config,
        environment={
            "network": "testnet",
            "python": "3.12.13",
            "platform": "darwin-arm64",
        },
        versions={"async-hyperliquid": "1.0.0rc1", "sdk": "0.24.0", "ccxt": "4.5.71"},
        git=GitMetadata(revision=revision, dirty=False),
        workload=CONCURRENT_CANCEL_WORKLOAD,
    )
    for round_index in range(30):
        oid_is_even = (round_index + 3) % 2 == 0
        for launch_slot in range(20):
            oid = launch_slot % 2 == 0 if oid_is_even else launch_slot % 2 == 1
            recorder.record(
                LatencySample(
                    suite="cancel-id",
                    provider="async-hyperliquid",
                    operation="cancel_by_oid" if oid else "cancel_by_cloid",
                    round_index=round_index,
                    provider_order=launch_slot,
                    duration_ns=(10_000_000 if oid else 20_000_000)
                    + round_index * 100
                    + launch_slot,
                )
            )
    return recorder.build_report(
        valid=True,
        failure_reason=None,
        cleanup_ok=True,
        started_at="2026-08-05T00:00:00Z",
        completed_at="2026-08-05T00:01:00Z",
    )


def _git(repository: Path, *args: str) -> str:
    completed = subprocess.run(
        ("git", *args), cwd=repository, check=True, capture_output=True, text=True
    )
    return completed.stdout.strip()


def _prepare_publish_repository(
    tmp_path: Path, *, collision: bool = False
) -> tuple[Path, Path, str, str]:
    repository = tmp_path / "repository"
    benchmarks = repository / "benchmarks"
    benchmarks.mkdir(parents=True)
    original_root = f"root\n{OVERALL_START}\nold overall\n{OVERALL_END}\n"
    original_detail = f"detail\n{DETAIL_START}\nold detail\n{DETAIL_END}\n"
    (repository / "README.md").write_text(original_root)
    (benchmarks / "README.md").write_text(original_detail)
    (repository / "notes.txt").write_text("tracked publication note\n")
    _git(repository, "init", "--quiet")
    _git(repository, "config", "user.email", "benchmark-tests@example.invalid")
    _git(repository, "config", "user.name", "Benchmark Tests")
    _git(repository, "add", "README.md", "benchmarks/README.md", "notes.txt")
    _git(repository, "commit", "--quiet", "-m", "initial publication state")
    if collision:
        destination = benchmarks / "results" / "20260805T000100Z"
        destination.mkdir(parents=True)
        (destination / ".keep").write_text("existing publication\n")
        _git(repository, "add", "benchmarks/results/20260805T000100Z/.keep")
        _git(repository, "commit", "--quiet", "-m", "existing publication")

    revision = _git(repository, "rev-parse", "HEAD")
    source = tmp_path / "source"
    source.mkdir()
    report = _valid_report(revision=revision)
    report_path = write_report(report, source, forbidden_values=())
    write_csv(report, source)
    for filename in FIGURE_FILENAMES[:2]:
        (source / filename).write_bytes(b"source figure")
    return repository, report_path, original_root, original_detail


def _write_fake_publish_figures(
    report: LiveBenchmarkReport, output_dir: Path
) -> tuple[Path, ...]:
    del report
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = tuple(output_dir / filename for filename in FIGURE_FILENAMES[:2])
    for path in paths:
        path.write_bytes(b"safe generated figure")
    return paths


def _assert_no_publication_debris(repository: Path) -> None:
    results = repository / "benchmarks" / "results"
    assert not results.exists() or list(results.iterdir()) == []


def _test_tombstone(base: Path) -> reporting._OwnedPath:
    private_root = base / ".git-private-test"
    private_root.mkdir(exist_ok=True)
    path = private_root / f"benchmark-publication.{os.urandom(16).hex()}.tombstone"
    path.mkdir(mode=0o700)
    return reporting._OwnedPath(path, reporting._require_kind(path, directory=True))


def test_figure_series_keeps_operations_and_providers_separate() -> None:
    series = figure_series(_valid_report(), "cancel-id")

    assert set(series) == {"cancel_by_oid", "cancel_by_cloid"}
    assert set(series["cancel_by_oid"]) == {"async-hyperliquid"}
    assert series["cancel_by_oid"]["async-hyperliquid"][0] == 10_000_001
    assert series["cancel_by_cloid"]["async-hyperliquid"][0] == 20_000_000


def test_chart_statistics_match_report_median_and_nearest_rank_p95() -> None:
    median_ms, p95_ms = chart_statistics([1, 2, 100, 200])

    assert median_ms == 51 / 1_000_000
    assert p95_ms == 200 / 1_000_000


def test_csv_contains_only_safe_sample_columns(tmp_path: Path) -> None:
    path = write_csv(_valid_report(), tmp_path)

    with path.open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert tuple(rows[0]) == (
        "suite",
        "provider",
        "operation",
        "round_index",
        "provider_order",
        "duration_ns",
    )
    assert len(rows) == 600
    assert not ({"oid", "cloid", "address", "signature"} & rows[0].keys())
    assert b"\r\n" not in path.read_bytes()


def test_live_report_declares_v2_concurrent_workload_contract() -> None:
    report = _valid_report()

    assert report["schema_version"] == 2
    assert report["failure_context"] is None
    assert report["config"]["workload"] == (
        "cancel-id-concurrent-batch20-singles20-10-per-method-v1"
    )
    validate_publishable(report)


def test_publication_rejects_non_null_failure_context() -> None:
    report = _valid_report()
    cast(dict[str, object], report)["failure_context"] = {
        "phase": "cancel_id",
        "logical_round": 0,
        "measured_round": 0,
        "operation": "cancel_by_oid",
        "launch_slot": 0,
        "category": "timeout",
        "failed_count": 1,
        "successful_count": 19,
        "recovery_attempted": True,
        "recovery_count": 1,
        "recovery_ok": True,
    }

    with pytest.raises(BenchmarkFailure, match="^report is not publishable$"):
        validate_publishable(report)


def test_publication_rejects_legacy_v1_report() -> None:
    report = _valid_report()
    report["schema_version"] = 1
    cast(dict[str, object], report["config"]).pop("workload", None)

    with pytest.raises(BenchmarkFailure, match="^report is not publishable$"):
        validate_publishable(report)


@pytest.mark.parametrize(
    "mutation",
    [
        pytest.param(
            lambda report: report.update(
                note="<!-- live-exchange-benchmark:detail:end -->"
            ),
            id="top-level-readme-marker",
        ),
        pytest.param(
            lambda report: cast(dict[str, str], report["versions"]).update(
                api_key="credential-shaped-extra"
            ),
            id="version-credential-extra",
        ),
        pytest.param(
            lambda report: cast(dict[str, object], report["git"]).update(
                branch="main\n<!-- injected -->"
            ),
            id="git-newline-extra",
        ),
    ],
)
def test_publication_rejects_undeclared_fields_with_sanitized_failure(
    mutation: Callable[[dict[str, Any]], None],
) -> None:
    report = _valid_report()
    mutation(cast(dict[str, Any], report))

    with pytest.raises(
        BenchmarkFailure, match="^report schema is not publishable$"
    ) as raised:
        validate_publishable(report)

    assert "credential" not in str(raised.value)
    assert "<!--" not in str(raised.value)


@pytest.mark.parametrize(
    "mutation",
    [
        pytest.param(
            lambda report: cast(dict[str, object], report["config"]).update(
                credential="extra"
            ),
            id="config-extra",
        ),
        pytest.param(
            lambda report: cast(dict[str, str], report["environment"]).update(
                credential="extra"
            ),
            id="environment-extra",
        ),
        pytest.param(
            lambda report: cast(dict[str, Any], report["summaries"]).update(
                credential={}
            ),
            id="summary-suite-extra",
        ),
        pytest.param(
            lambda report: cast(
                dict[str, Any], report["summaries"]["cancel-id"]
            ).update(credential={}),
            id="summary-operation-extra",
        ),
        pytest.param(
            lambda report: cast(
                dict[str, Any], report["summaries"]["cancel-id"]["cancel_by_oid"]
            ).update(credential={}),
            id="summary-provider-extra",
        ),
        pytest.param(
            lambda report: cast(
                dict[str, Any],
                report["summaries"]["cancel-id"]["cancel_by_oid"]["async-hyperliquid"],
            ).update(credential="extra"),
            id="summary-value-extra",
        ),
    ],
)
def test_publication_requires_exact_config_and_summary_key_levels(
    mutation: Callable[[dict[str, Any]], None],
) -> None:
    report = _valid_report()
    mutation(cast(dict[str, Any], report))

    with pytest.raises(BenchmarkFailure, match="^report schema is not publishable$"):
        validate_publishable(report)


@pytest.mark.parametrize(
    "mutation",
    [
        pytest.param(
            lambda report: cast(dict[str, str], report["environment"]).update(
                python="3.12.13\n<!-- injected -->"
            ),
            id="python-newline",
        ),
        pytest.param(
            lambda report: cast(dict[str, str], report["environment"]).update(
                platform="darwin|marker"
            ),
            id="platform-table-marker",
        ),
        pytest.param(
            lambda report: cast(dict[str, str], report["versions"]).update(
                sdk="0.24.0\ncredential"
            ),
            id="version-newline",
        ),
        pytest.param(
            lambda report: cast(dict[str, object], report["git"]).update(
                revision="A" * 40
            ),
            id="uppercase-revision",
        ),
        pytest.param(
            lambda report: cast(dict[str, object], report["config"]).update(
                workload="cancel-id\n<!-- injected -->"
            ),
            id="unknown-workload",
        ),
    ],
)
def test_publication_rejects_noncanonical_persisted_metadata(
    mutation: Callable[[dict[str, Any]], None],
) -> None:
    report = _valid_report()
    mutation(cast(dict[str, Any], report))

    with pytest.raises(BenchmarkFailure, match="^report is not publishable$") as raised:
        validate_publishable(report)

    assert "credential" not in str(raised.value)
    assert "<!--" not in str(raised.value)


@pytest.mark.parametrize(
    ("started_at", "completed_at"),
    [
        pytest.param(
            "2026-08-05T00:00:00+00:00", "2026-08-05T00:01:00Z", id="offset-not-z"
        ),
        pytest.param(
            "2026-08-05T00:00:00.000Z", "2026-08-05T00:01:00Z", id="fractional-seconds"
        ),
        pytest.param("2026-08-05T00:02:00Z", "2026-08-05T00:01:00Z", id="reversed"),
        pytest.param(
            "2026-08-05T00:00:00Z\n<!-- injected -->",
            "2026-08-05T00:01:00Z",
            id="newline-marker",
        ),
    ],
)
def test_publication_rejects_noncanonical_or_reversed_timestamps(
    started_at: str, completed_at: str
) -> None:
    report = _valid_report()
    report["started_at"] = started_at
    report["completed_at"] = completed_at

    with pytest.raises(
        BenchmarkFailure, match="^report schema is not publishable$"
    ) as raised:
        validate_publishable(report)

    assert "injected" not in str(raised.value)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda report: report.update(valid=False),
        lambda report: report.update(cleanup_ok=False),
        lambda report: report.update(schema_version=1),
        lambda report: cast(dict[str, str], report["environment"]).update(
            network="mainnet"
        ),
        lambda report: cast(dict[str, str], report["environment"]).update(
            note="| injected\nREADME text"
        ),
        lambda report: cast(dict[str, Any], report["git"]).update(dirty=True),
        lambda report: cast(dict[str, Any], report["git"]).update(revision="unknown"),
        lambda report: cast(dict[str, object], report["config"]).update(rounds=29),
        lambda report: cast(dict[str, str], report["versions"]).update(ccxt="new"),
        lambda report: cast(dict[str, Any], report["samples"][0]).update(
            provider="sdk"
        ),
        lambda report: cast(list[object], report["samples"]).pop(),
        lambda report: cast(
            dict[str, Any],
            report["summaries"]["cancel-id"]["cancel_by_oid"]["async-hyperliquid"],
        ).update(median_ns=1),
    ],
)
def test_publication_rejects_invalid_or_non_default_reports(
    mutation: Callable[[dict[str, Any]], None],
) -> None:
    report = _valid_report()
    mutation(cast(dict[str, Any], report))

    with pytest.raises(BenchmarkFailure, match="publish"):
        validate_publishable(report)


def test_publication_rejects_duplicate_measured_rounds() -> None:
    report = _valid_report()
    report["samples"][20]["round_index"] = 0

    with pytest.raises(BenchmarkFailure, match="publish"):
        validate_publishable(report)


@pytest.mark.parametrize(
    "mutation",
    [
        pytest.param(lambda report: report.update(config=[]), id="config-list"),
        pytest.param(lambda report: report.update(versions=[]), id="versions-list"),
        pytest.param(lambda report: report.update(git=[]), id="git-list"),
        pytest.param(
            lambda report: report.update(environment=[]), id="environment-list"
        ),
        pytest.param(
            lambda report: report.update(started_at=0), id="started-at-integer"
        ),
        pytest.param(
            lambda report: report.update(completed_at=None), id="completed-at-null"
        ),
        pytest.param(lambda report: report.update(samples={}), id="samples-mapping"),
        pytest.param(lambda report: report.update(summaries=[]), id="summaries-list"),
    ],
)
def test_publication_sanitizes_malformed_schema_containers_and_scalars(
    mutation: Callable[[dict[str, Any]], None],
) -> None:
    report = _valid_report()
    mutation(cast(dict[str, Any], report))

    with pytest.raises(BenchmarkFailure, match="^report schema is not publishable$"):
        validate_publishable(report)


@pytest.mark.parametrize("report", [[], "not-a-report"])
def test_publication_sanitizes_non_mapping_top_level_report(report: object) -> None:
    with pytest.raises(BenchmarkFailure, match="^report schema is not publishable$"):
        validate_publishable(cast(LiveBenchmarkReport, report))


def test_publication_requires_concurrent_cancel_shape() -> None:
    report = _valid_report()

    validate_publishable(report)

    assert len(report["samples"]) == 600
    report["samples"].pop()
    with pytest.raises(BenchmarkFailure, match="sample shape"):
        validate_publishable(report)


@pytest.mark.parametrize(
    "mutation",
    [
        pytest.param(
            lambda report: report["samples"].__setitem__(
                1, {**report["samples"][1], "provider_order": 0}
            ),
            id="duplicate-launch-slot",
        ),
        pytest.param(
            lambda report: report["samples"].__setitem__(
                0, {**report["samples"][0], "provider_order": 1}
            ),
            id="wrong-oid-slot-parity",
        ),
        pytest.param(
            lambda report: report["samples"].__setitem__(
                0, {**report["samples"][0], "operation": "cancel_by_oid"}
            ),
            id="eleven-nine-method-split",
        ),
        pytest.param(
            lambda report: report["samples"].__setitem__(
                0, {**report["samples"][0], "provider": "sdk"}
            ),
            id="provider-sample",
        ),
        pytest.param(
            lambda report: report["samples"].__setitem__(
                0, {**report["samples"][0], "suite": "all"}
            ),
            id="all-report",
        ),
        pytest.param(
            lambda report: report["samples"].__setitem__(
                0,
                {
                    **report["samples"][0],
                    "operation": "cancel_by_oid\n<!-- injected -->",
                },
            ),
            id="operation-newline",
        ),
    ],
)
def test_publication_rejects_invalid_concurrent_cancel_slots(
    mutation: Callable[[dict[str, Any]], None],
) -> None:
    report = _valid_report()
    mutation(cast(dict[str, Any], report))

    with pytest.raises(BenchmarkFailure, match="publish"):
        validate_publishable(report)


def _small_concurrent_report(
    oid_rounds: tuple[tuple[int, ...], ...], cloid_rounds: tuple[tuple[int, ...], ...]
) -> LiveBenchmarkReport:
    samples = []
    for operation, rounds in (
        ("cancel_by_oid", oid_rounds),
        ("cancel_by_cloid", cloid_rounds),
    ):
        for round_index, durations in enumerate(rounds):
            for launch_slot, duration_ns in enumerate(durations):
                samples.append(
                    {
                        "suite": "cancel-id",
                        "provider": "async-hyperliquid",
                        "operation": operation,
                        "round_index": round_index,
                        "provider_order": launch_slot,
                        "duration_ns": duration_ns,
                    }
                )
    return cast(LiveBenchmarkReport, {"samples": samples})


def test_round_max_summaries_use_the_slowest_request_per_method_round() -> None:
    report = _small_concurrent_report(
        oid_rounds=((1, 2, 9), (3, 4, 8)), cloid_rounds=((5, 6, 7), (2, 10, 11))
    )

    summaries = round_max_summaries(report)

    assert summaries["cancel_by_oid"]["median_ns"] == 8.5
    assert summaries["cancel_by_cloid"]["median_ns"] == 9.0


def test_figures_are_written_as_png_and_svg(tmp_path: Path) -> None:
    pytest.importorskip("matplotlib")

    paths = write_figures(_valid_report(), tmp_path)

    assert {path.name for path in paths} == set(FIGURE_FILENAMES[:2])
    for path in paths:
        assert path.stat().st_size > 100
    assert (tmp_path / "cancel-id-latency.png").read_bytes().startswith(b"\x89PNG")
    cancel_svg = tmp_path / "cancel-id-latency.svg"
    assert b"<svg" in cancel_svg.read_bytes()[:1000]
    assert all(line == line.rstrip() for line in cancel_svg.read_text().splitlines())


def test_figures_render_cancel_request_and_round_maximum_views(tmp_path: Path) -> None:
    pytest.importorskip("matplotlib")
    paths = write_figures(_valid_report(), tmp_path)

    assert {path.name for path in paths} == {
        "cancel-id-latency.png",
        "cancel-id-latency.svg",
    }


def test_publish_updates_detailed_and_overall_markers_from_one_report(
    tmp_path: Path,
) -> None:
    repository, report_path, _, _ = _prepare_publish_repository(tmp_path)
    source = report_path.parent
    (source / "samples.csv").write_text("tampered source CSV\n")
    for filename in FIGURE_FILENAMES[:2]:
        (source / filename).write_bytes(b"safe benchmark figure")

    published = publish_report(report_path, repository)

    assert published.name == "20260805T000100Z"
    assert sorted(path.name for path in published.iterdir()) == sorted(
        ("report.json", "samples.csv", *FIGURE_FILENAMES[:2])
    )
    assert (
        (published / "samples.csv")
        .read_text()
        .startswith("suite,provider,operation,round_index,provider_order,duration_ns\n")
    )
    assert (published / "cancel-id-latency.png").read_bytes().startswith(b"\x89PNG")
    root_readme = (repository / "README.md").read_text()
    detail_readme = (repository / "benchmarks" / "README.md").read_text()
    assert root_readme.startswith("root\n")
    assert "old overall" not in root_readme
    assert "#### Published live Exchange result" in root_readme
    assert "OID" in root_readme
    assert "concurrency=20 (10 OID + 10 CLOID)" in root_readme
    assert "Overall equal-weight ranking" not in root_readme
    assert detail_readme.startswith("detail\n")
    assert "old detail" not in detail_readme
    assert "240 weight/minute" in detail_readme
    assert "Per-round method maxima" in detail_readme
    assert "Provider comparison" not in detail_readme
    async_index = detail_readme.index("| async-hyperliquid |")
    sdk_index = detail_readme.index("| sdk |")
    ccxt_index = detail_readme.index("| ccxt |")
    assert async_index < sdk_index < ccxt_index
    assert all(line == line.rstrip() for line in detail_readme.splitlines())


def test_publish_requires_exactly_one_marker_pair(tmp_path: Path) -> None:
    repository, report_path, _, _ = _prepare_publish_repository(tmp_path)
    (repository / "README.md").write_text("missing markers\n")
    _git(repository, "add", "README.md")
    _git(repository, "commit", "--quiet", "-m", "missing root markers")
    report = _valid_report(revision=_git(repository, "rev-parse", "HEAD"))
    report_path = write_report(report, report_path.parent, forbidden_values=())

    with pytest.raises(BenchmarkFailure, match="README marker"):
        publish_report(report_path, repository)

    assert (repository / "README.md").read_text() == "missing markers\n"


def test_publish_rejects_noncanonical_completion_timestamp_before_mutation(
    tmp_path: Path,
) -> None:
    repository, report_path, original_root, original_detail = (
        _prepare_publish_repository(tmp_path)
    )
    report = _valid_report(revision=_git(repository, "rev-parse", "HEAD"))
    report["completed_at"] = "0001-01-01T00:00:00+23:59"
    report_path = write_report(report, report_path.parent, forbidden_values=())

    with pytest.raises(BenchmarkFailure, match="^report schema is not publishable$"):
        publish_report(report_path, repository)

    assert (repository / "README.md").read_text() == original_root
    assert (repository / "benchmarks" / "README.md").read_text() == original_detail
    assert not (repository / "benchmarks" / "results").exists()


def test_publish_rolls_back_both_readmes_and_artifacts_on_second_replace_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    repository, report_path, original_root, original_detail = (
        _prepare_publish_repository(tmp_path)
    )
    benchmark_readme = repository / "benchmarks" / "README.md"
    monkeypatch.setattr(reporting, "write_figures", _write_fake_publish_figures)
    real_atomic_change = reporting._atomic_text_if_unchanged
    calls = 0

    def fail_second_replace(change: Any) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("simulated second replacement failure")
        real_atomic_change(change)

    monkeypatch.setattr(reporting, "_atomic_text_if_unchanged", fail_second_replace)

    with pytest.raises(BenchmarkFailure, match="publication failed"):
        publish_report(report_path, repository)

    assert (repository / "README.md").read_text() == original_root
    assert benchmark_readme.read_text() == original_detail
    _assert_no_publication_debris(repository)


def test_publish_rejects_stale_report_revision_before_mutation(tmp_path: Path) -> None:
    repository, report_path, original_root, original_detail = (
        _prepare_publish_repository(tmp_path)
    )
    report = _valid_report(revision="b" * 40)
    report_path = write_report(report, report_path.parent, forbidden_values=())

    with pytest.raises(
        BenchmarkFailure, match="^benchmark publication repository is not publishable$"
    ):
        publish_report(report_path, repository)

    assert (repository / "README.md").read_text() == original_root
    assert (repository / "benchmarks" / "README.md").read_text() == original_detail
    assert not (repository / "benchmarks" / "results").exists()


@pytest.mark.parametrize("dirty_kind", ["tracked", "untracked"])
def test_publish_rejects_dirty_or_untracked_repository_with_sanitized_failure(
    tmp_path: Path, dirty_kind: str
) -> None:
    repository, report_path, original_root, original_detail = (
        _prepare_publish_repository(tmp_path)
    )
    if dirty_kind == "tracked":
        (repository / "README.md").write_text(f"{original_root}private tracked text\n")
    else:
        (repository / "private-untracked.txt").write_text("private untracked text\n")

    with pytest.raises(
        BenchmarkFailure, match="^benchmark publication repository is not publishable$"
    ) as raised:
        publish_report(report_path, repository)

    assert "private" not in str(raised.value)
    assert (repository / "benchmarks" / "README.md").read_text() == original_detail
    assert not (repository / "benchmarks" / "results").exists()


def test_publish_rejects_non_repository_root_without_path_details(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "not-a-repository"
    repository.mkdir()
    source = tmp_path / "source"
    source.mkdir()
    report = _valid_report()
    report_path = write_report(report, source, forbidden_values=())
    write_csv(report, source)
    for filename in FIGURE_FILENAMES[:2]:
        (source / filename).write_bytes(b"source figure")

    with pytest.raises(
        BenchmarkFailure, match="^benchmark publication repository is not publishable$"
    ) as raised:
        publish_report(report_path, repository)

    assert str(repository) not in str(raised.value)
    assert list(repository.iterdir()) == []


def test_publish_fails_immediately_when_repository_lock_is_held(tmp_path: Path) -> None:
    repository, report_path, original_root, original_detail = (
        _prepare_publish_repository(tmp_path)
    )
    git_dir = Path(_git(repository, "rev-parse", "--absolute-git-dir"))
    lock_path = git_dir / "benchmark-publication.lock"

    with lock_path.open("a+b") as held_lock:
        fcntl.flock(held_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(
            BenchmarkFailure, match="^benchmark publication is already in progress$"
        ):
            publish_report(report_path, repository)

    assert (repository / "README.md").read_text() == original_root
    assert (repository / "benchmarks" / "README.md").read_text() == original_detail
    assert not (repository / "benchmarks" / "results").exists()


def test_publish_detects_readme_compare_conflict_without_overwriting_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    repository, report_path, original_root, _ = _prepare_publish_repository(tmp_path)
    benchmark_readme = repository / "benchmarks" / "README.md"
    conflicting_detail = (
        f"external update\n{DETAIL_START}\nother detail\n{DETAIL_END}\n"
    )

    def generate_then_conflict(
        report: LiveBenchmarkReport, output_dir: Path
    ) -> tuple[Path, ...]:
        paths = _write_fake_publish_figures(report, output_dir)
        benchmark_readme.write_text(conflicting_detail)
        return paths

    monkeypatch.setattr(reporting, "write_figures", generate_then_conflict)

    with pytest.raises(
        BenchmarkFailure, match="^benchmark publication repository is not publishable$"
    ) as raised:
        publish_report(report_path, repository)

    assert "external" not in str(raised.value)
    assert benchmark_readme.read_text() == conflicting_detail
    assert (repository / "README.md").read_text() == original_root
    _assert_no_publication_debris(repository)


def test_keyboard_interrupt_during_second_replace_fully_compensates_and_retries(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    repository, report_path, original_root, original_detail = (
        _prepare_publish_repository(tmp_path)
    )
    destination = repository / "benchmarks" / "results" / "20260805T000100Z"
    real_atomic_change = reporting._atomic_text_if_unchanged
    calls = 0

    def interrupt_after_second_replace(change: Any) -> None:
        nonlocal calls
        calls += 1
        real_atomic_change(change)
        if calls == 2:
            assert not destination.exists()
            raise KeyboardInterrupt

    monkeypatch.setattr(reporting, "write_figures", _write_fake_publish_figures)
    monkeypatch.setattr(
        reporting, "_atomic_text_if_unchanged", interrupt_after_second_replace
    )

    with pytest.raises(KeyboardInterrupt):
        publish_report(report_path, repository)

    assert (repository / "README.md").read_text() == original_root
    assert (repository / "benchmarks" / "README.md").read_text() == original_detail
    _assert_no_publication_debris(repository)
    assert _git(repository, "status", "--porcelain=v1", "--untracked-files=all") == ""

    monkeypatch.setattr(reporting, "_atomic_text_if_unchanged", real_atomic_change)
    published = publish_report(report_path, repository)

    assert published == destination
    assert sorted(path.name for path in published.iterdir()) == sorted(
        ("report.json", "samples.csv", *FIGURE_FILENAMES[:2])
    )


def test_artifact_generation_failure_removes_unique_staging_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    repository, report_path, original_root, original_detail = (
        _prepare_publish_repository(tmp_path)
    )

    def fail_generation(
        report: LiveBenchmarkReport, output_dir: Path
    ) -> tuple[Path, ...]:
        del report
        (output_dir / "partial-secret-path.png").write_bytes(b"partial")
        raise OSError("sensitive artifact generator detail")

    monkeypatch.setattr(reporting, "write_figures", fail_generation)

    with pytest.raises(
        BenchmarkFailure, match="^benchmark publication failed$"
    ) as raised:
        publish_report(report_path, repository)

    assert "sensitive" not in str(raised.value)
    assert (repository / "README.md").read_text() == original_root
    assert (repository / "benchmarks" / "README.md").read_text() == original_detail
    _assert_no_publication_debris(repository)


def test_interrupt_immediately_after_staging_creation_leaves_no_orphan(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    repository, report_path, original_root, original_detail = (
        _prepare_publish_repository(tmp_path)
    )
    real_create_owned = reporting._create_owned_directory

    def create_then_interrupt(path: Path, registry: list[Any] | None = None) -> Any:
        owned = real_create_owned(path, registry)
        if path.name.endswith(".staging"):
            raise KeyboardInterrupt
        return owned

    monkeypatch.setattr(reporting, "_create_owned_directory", create_then_interrupt)
    monkeypatch.setattr(reporting, "write_figures", _write_fake_publish_figures)

    with pytest.raises(KeyboardInterrupt):
        publish_report(report_path, repository)

    assert (repository / "README.md").read_text() == original_root
    assert (repository / "benchmarks" / "README.md").read_text() == original_detail
    _assert_no_publication_debris(repository)
    assert _git(repository, "status", "--porcelain=v1", "--untracked-files=all") == ""


def test_sigterm_during_created_directory_fstat_keeps_retained_candidate_empty(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    repository, report_path, original_root, original_detail = (
        _prepare_publish_repository(tmp_path)
    )
    git_dir = Path(_git(repository, "rev-parse", "--absolute-git-dir"))
    real_open = os.open
    real_fstat = os.fstat
    created_fd: int | None = None
    delivered: list[int] = []
    sent = False

    def raises_system_exit(signum: int, frame: object) -> None:
        del frame
        delivered.append(signum)
        raise SystemExit(18)

    def record_created_open(
        path: str | os.PathLike[str],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        nonlocal created_fd
        fd = real_open(path, flags, mode, dir_fd=dir_fd)
        if isinstance(path, str) and path.endswith(".staging") and dir_fd is not None:
            created_fd = fd
        return fd

    def fstat_then_sigterm(fd: int) -> os.stat_result:
        nonlocal sent
        value = real_fstat(fd)
        if fd == created_fd and not sent:
            sent = True
            os.kill(os.getpid(), signal.SIGTERM)
        return value

    previous_handler = signal.signal(signal.SIGTERM, raises_system_exit)
    monkeypatch.setattr(os, "open", record_created_open)
    monkeypatch.setattr(os, "fstat", fstat_then_sigterm)
    try:
        with pytest.raises(SystemExit) as raised:
            publish_report(report_path, repository)
    finally:
        signal.signal(signal.SIGTERM, previous_handler)

    assert raised.value.code == 18
    assert sent
    assert delivered == [signal.SIGTERM]
    candidates = list(git_dir.glob("benchmark-publication.*.staging"))
    assert len(candidates) <= 1
    for candidate in candidates:
        assert candidate.is_dir()
        assert list(candidate.iterdir()) == []
    assert (repository / "README.md").read_text() == original_root
    assert (repository / "benchmarks" / "README.md").read_text() == original_detail
    _assert_no_publication_debris(repository)


@pytest.mark.parametrize("directory_kind", ["results", "staging"])
def test_sigterm_after_real_mkdir_keeps_retained_private_candidate_empty(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, directory_kind: str
) -> None:
    repository, report_path, original_root, original_detail = (
        _prepare_publish_repository(tmp_path)
    )
    git_dir = Path(_git(repository, "rev-parse", "--absolute-git-dir"))
    real_mkdir = os.mkdir
    delivered: list[int] = []
    sent = False

    def raises_system_exit(signum: int, frame: object) -> None:
        del frame
        delivered.append(signum)
        raise SystemExit(15)

    def mkdir_then_sigterm(
        path: str | os.PathLike[str], mode: int = 0o777, *, dir_fd: int | None = None
    ) -> None:
        nonlocal sent
        real_mkdir(path, mode, dir_fd=dir_fd)
        candidate = Path(path)
        matches = (
            candidate.name.endswith(".results.creation")
            if directory_kind == "results"
            else candidate.name.endswith(".staging")
        )
        if matches and not sent:
            sent = True
            os.kill(os.getpid(), signal.SIGTERM)

    previous_handler = signal.signal(signal.SIGTERM, raises_system_exit)
    monkeypatch.setattr(os, "mkdir", mkdir_then_sigterm)
    try:
        with pytest.raises(SystemExit) as raised:
            publish_report(report_path, repository)
    finally:
        signal.signal(signal.SIGTERM, previous_handler)

    assert raised.value.code == 15
    assert sent
    assert delivered == [signal.SIGTERM]
    suffix = "results.creation" if directory_kind == "results" else "staging"
    candidates = list(git_dir.glob(f"benchmark-publication.*.{suffix}"))
    assert len(candidates) <= 1
    for candidate in candidates:
        assert candidate.is_dir()
        assert list(candidate.iterdir()) == []
    assert (repository / "README.md").read_text() == original_root
    assert (repository / "benchmarks" / "README.md").read_text() == original_detail
    _assert_no_publication_debris(repository)
    assert not (repository / "benchmarks" / "results").exists()


@pytest.mark.parametrize("directory_kind", ["results", "staging"])
@pytest.mark.parametrize("handler_kind", ["ordinary", "control-flow"])
def test_pending_sigterm_after_post_mkdir_swap_never_claims_replacement(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    directory_kind: str,
    handler_kind: str,
) -> None:
    repository, report_path, original_root, original_detail = (
        _prepare_publish_repository(tmp_path)
    )
    git_dir = Path(_git(repository, "rev-parse", "--absolute-git-dir"))
    real_mkdir = os.mkdir
    real_open = os.open
    delivered: list[int] = []
    swapped: list[tuple[Path, Path]] = []
    replacement_fds: list[int] = []
    sent = False

    def raises_from_sigterm(signum: int, frame: object) -> None:
        del frame
        delivered.append(signum)
        if handler_kind == "ordinary":
            raise RuntimeError("sensitive signal-handler detail")
        raise SystemExit(31)

    def mkdir_swap_then_sigterm(
        path: str | os.PathLike[str], mode: int = 0o777, *, dir_fd: int | None = None
    ) -> None:
        nonlocal sent
        real_mkdir(path, mode, dir_fd=dir_fd)
        candidate = git_dir / os.fsdecode(os.fspath(path))
        matches = (
            candidate.name.endswith(".results.creation")
            if directory_kind == "results"
            else candidate.name.endswith(".staging")
        )
        if matches and not sent:
            sent = True
            moved = candidate.with_name(f"{candidate.name}.ambiguous-owned")
            candidate.rename(moved)
            real_mkdir(candidate, 0o711)
            (candidate / "foreign.txt").write_text("foreign namespace\n")
            candidate.chmod(0o711)
            swapped.append((candidate, moved))
            os.kill(os.getpid(), signal.SIGTERM)

    def record_replacement_open(
        path: str | os.PathLike[str],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        fd = real_open(path, flags, mode, dir_fd=dir_fd)
        if (
            swapped
            and dir_fd is not None
            and os.fsdecode(os.fspath(path)) == swapped[0][0].name
        ):
            replacement_fds.append(fd)
        return fd

    previous_handler = signal.signal(signal.SIGTERM, raises_from_sigterm)
    monkeypatch.setattr(os, "mkdir", mkdir_swap_then_sigterm)
    monkeypatch.setattr(os, "open", record_replacement_open)
    try:
        if handler_kind == "ordinary":
            with pytest.raises(
                BenchmarkFailure, match="^benchmark publication failed$"
            ) as raised:
                publish_report(report_path, repository)
            assert "sensitive" not in str(raised.value)
        else:
            with pytest.raises(SystemExit) as raised:
                publish_report(report_path, repository)
            assert raised.value.code == 31
    finally:
        signal.signal(signal.SIGTERM, previous_handler)

    assert sent
    assert delivered == [signal.SIGTERM]
    assert replacement_fds
    for replacement_fd in replacement_fds:
        with pytest.raises(OSError):
            os.fstat(replacement_fd)
    assert len(swapped) == 1
    replacement, moved = swapped[0]
    assert replacement.parent == git_dir
    assert replacement.stat().st_mode & 0o777 == 0o711
    assert (replacement / "foreign.txt").read_text() == "foreign namespace\n"
    assert moved.is_dir()
    assert (repository / "README.md").read_text() == original_root
    assert (repository / "benchmarks" / "README.md").read_text() == original_detail
    assert _git(repository, "status", "--porcelain=v1", "--untracked-files=all") == ""
    assert not (repository / "benchmarks" / "results").exists()

    observed_replacement_fds = tuple(replacement_fds)
    monkeypatch.setattr(reporting, "write_figures", _write_fake_publish_figures)
    destination = publish_report(report_path, repository)

    assert destination.is_dir()
    assert tuple(replacement_fds) == observed_replacement_fds
    assert replacement.stat().st_mode & 0o777 == 0o711
    assert (replacement / "foreign.txt").read_text() == "foreign namespace\n"


@pytest.mark.parametrize("directory_kind", ["results", "staging"])
@pytest.mark.parametrize("control_flow", [KeyboardInterrupt(), SystemExit(23)])
def test_injected_control_flow_after_real_mkdir_leaves_git_private_orphan(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    directory_kind: str,
    control_flow: BaseException,
) -> None:
    repository, report_path, original_root, original_detail = (
        _prepare_publish_repository(tmp_path)
    )
    git_dir = Path(_git(repository, "rev-parse", "--absolute-git-dir"))
    real_mkdir = os.mkdir
    injected = False
    ambiguous: list[Path] = []

    def mkdir_then_interrupt(
        path: str | os.PathLike[str], mode: int = 0o777, *, dir_fd: int | None = None
    ) -> None:
        nonlocal injected
        real_mkdir(path, mode, dir_fd=dir_fd)
        candidate = Path(path)
        matches = (
            candidate.name.endswith(".results.creation")
            if directory_kind == "results"
            else candidate.name.endswith(".staging")
        )
        if matches and not injected:
            injected = True
            ambiguous.append(git_dir / candidate.name)
            raise control_flow

    monkeypatch.setattr(os, "mkdir", mkdir_then_interrupt)

    with pytest.raises(type(control_flow)) as raised:
        publish_report(report_path, repository)

    assert raised.value is control_flow
    assert injected
    assert len(ambiguous) == 1
    assert ambiguous[0].is_dir()
    assert ambiguous[0].parent == git_dir
    assert (repository / "README.md").read_text() == original_root
    assert (repository / "benchmarks" / "README.md").read_text() == original_detail
    _assert_no_publication_debris(repository)
    assert not (repository / "benchmarks" / "results").exists()


@pytest.mark.parametrize("directory_kind", ["results", "staging"])
@pytest.mark.parametrize("control_flow", [KeyboardInterrupt(), SystemExit(29)])
def test_ambiguous_post_mkdir_swap_is_never_claimed_and_retry_succeeds(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    directory_kind: str,
    control_flow: BaseException,
) -> None:
    repository, report_path, original_root, original_detail = (
        _prepare_publish_repository(tmp_path)
    )
    git_dir = Path(_git(repository, "rev-parse", "--absolute-git-dir"))
    results_dir = repository / "benchmarks" / "results"
    real_mkdir = os.mkdir
    injected = False
    swapped: list[tuple[Path, Path]] = []

    def mkdir_swap_then_interrupt(
        path: str | os.PathLike[str], mode: int = 0o777, *, dir_fd: int | None = None
    ) -> None:
        nonlocal injected
        real_mkdir(path, mode, dir_fd=dir_fd)
        candidate = (
            Path(path) if dir_fd is None else git_dir / os.fsdecode(os.fspath(path))
        )
        matches = (
            candidate == results_dir or candidate.name.endswith(".results.creation")
            if directory_kind == "results"
            else candidate.name.endswith(".staging")
        )
        if matches and not injected:
            injected = True
            moved = candidate.with_name(f"{candidate.name}.ambiguous-owned")
            candidate.rename(moved)
            real_mkdir(candidate, mode)
            (candidate / "foreign.txt").write_text("foreign namespace\n")
            swapped.append((candidate, moved))
            raise control_flow

    monkeypatch.setattr(os, "mkdir", mkdir_swap_then_interrupt)

    with pytest.raises(type(control_flow)) as raised:
        publish_report(report_path, repository)

    assert raised.value is control_flow
    assert injected
    assert len(swapped) == 1
    replacement, moved = swapped[0]
    assert replacement.parent == git_dir
    assert (replacement / "foreign.txt").read_text() == "foreign namespace\n"
    assert moved.is_dir()
    assert (repository / "README.md").read_text() == original_root
    assert (repository / "benchmarks" / "README.md").read_text() == original_detail
    assert _git(repository, "status", "--porcelain=v1", "--untracked-files=all") == ""
    first_invocation_names = [
        path
        for path in git_dir.glob("benchmark-publication.*")
        if path.name != reporting._PUBLICATION_LOCK_FILENAME
    ]
    assert len(first_invocation_names) <= 3

    monkeypatch.setattr(reporting, "write_figures", _write_fake_publish_figures)
    destination = publish_report(report_path, repository)

    assert destination.is_dir()
    assert (replacement / "foreign.txt").read_text() == "foreign namespace\n"


def test_final_destination_collision_fails_before_readme_mutation(
    tmp_path: Path,
) -> None:
    repository, report_path, original_root, original_detail = (
        _prepare_publish_repository(tmp_path, collision=True)
    )
    destination = repository / "benchmarks" / "results" / "20260805T000100Z"

    with pytest.raises(
        BenchmarkFailure, match="^published benchmark timestamp already exists$"
    ):
        publish_report(report_path, repository)

    assert (repository / "README.md").read_text() == original_root
    assert (repository / "benchmarks" / "README.md").read_text() == original_detail
    assert sorted(path.name for path in destination.iterdir()) == [".keep"]
    assert sorted(path.name for path in destination.parent.iterdir()) == [
        "20260805T000100Z"
    ]


def test_results_creation_collision_is_not_deleted(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    repository, report_path, original_root, original_detail = (
        _prepare_publish_repository(tmp_path)
    )
    git_dir = Path(_git(repository, "rev-parse", "--absolute-git-dir"))
    results_dir = repository / "benchmarks" / "results"
    real_mkdir = os.mkdir
    collision: list[Path] = []

    def collide(
        path: str | os.PathLike[str], mode: int = 0o777, *, dir_fd: int | None = None
    ) -> None:
        candidate = Path(path)
        real_mkdir(path, mode, dir_fd=dir_fd)
        if candidate.name.endswith(".results.creation"):
            collision.append(git_dir / candidate.name)
            raise FileExistsError("simulated namespace winner")

    monkeypatch.setattr(os, "mkdir", collide)

    with pytest.raises(BenchmarkFailure, match="^benchmark publication failed$"):
        publish_report(report_path, repository)

    assert not results_dir.exists()
    assert len(collision) == 1
    assert collision[0].is_dir()
    assert collision[0].parent == git_dir
    assert (repository / "README.md").read_text() == original_root
    assert (repository / "benchmarks" / "README.md").read_text() == original_detail


def test_staging_creation_collision_is_not_deleted(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    repository, report_path, original_root, original_detail = (
        _prepare_publish_repository(tmp_path)
    )
    git_dir = Path(_git(repository, "rev-parse", "--absolute-git-dir"))
    collision: list[Path] = []
    real_mkdir = os.mkdir

    def collide(
        path: str | os.PathLike[str], mode: int = 0o777, *, dir_fd: int | None = None
    ) -> None:
        candidate = Path(path)
        real_mkdir(path, mode, dir_fd=dir_fd)
        if candidate.name.endswith(".staging"):
            collision.append(git_dir / candidate.name)
            raise FileExistsError("simulated namespace winner")

    monkeypatch.setattr(os, "mkdir", collide)

    with pytest.raises(BenchmarkFailure, match="^benchmark publication failed$"):
        publish_report(report_path, repository)

    assert len(collision) == 1
    assert collision[0].is_dir()
    assert (repository / "README.md").read_text() == original_root
    assert (repository / "benchmarks" / "README.md").read_text() == original_detail


def test_staging_namespace_swap_is_rejected_without_deleting_replacement(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    repository, report_path, original_root, original_detail = (
        _prepare_publish_repository(tmp_path)
    )
    swapped: list[tuple[Path, Path]] = []

    def generate_then_swap(
        report: LiveBenchmarkReport, output_dir: Path
    ) -> tuple[Path, ...]:
        paths = _write_fake_publish_figures(report, output_dir)
        moved = output_dir.with_name(f"{output_dir.name}.moved")
        output_dir.rename(moved)
        output_dir.mkdir()
        (output_dir / "belongs-to-another-process").write_text("keep\n")
        swapped.append((output_dir, moved))
        return paths

    monkeypatch.setattr(reporting, "write_figures", generate_then_swap)

    with pytest.raises(BenchmarkFailure, match="^benchmark publication failed$"):
        publish_report(report_path, repository)

    replacement, moved = swapped[0]
    assert (replacement / "belongs-to-another-process").read_text() == "keep\n"
    assert moved.is_dir()
    assert (repository / "README.md").read_text() == original_root
    assert (repository / "benchmarks" / "README.md").read_text() == original_detail
    assert not (repository / "benchmarks" / "results" / "20260805T000100Z").exists()


def test_transaction_cleanup_retains_value_free_git_private_tombstone_without_removers(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    repository, report_path, original_root, original_detail = (
        _prepare_publish_repository(tmp_path)
    )
    git_dir = Path(_git(repository, "rev-parse", "--absolute-git-dir"))
    real_unlink = os.unlink
    real_rmdir = os.rmdir
    removals: list[str] = []

    def record_unlink(
        path: str | os.PathLike[str], *, dir_fd: int | None = None
    ) -> None:
        removals.append("unlink")
        real_unlink(path, dir_fd=dir_fd)

    def record_rmdir(
        path: str | os.PathLike[str], *, dir_fd: int | None = None
    ) -> None:
        removals.append("rmdir")
        real_rmdir(path, dir_fd=dir_fd)

    def generate_tree_then_fail(
        report: LiveBenchmarkReport, output_dir: Path
    ) -> tuple[Path, ...]:
        _write_fake_publish_figures(report, output_dir)
        nested = output_dir / "nested"
        nested.mkdir()
        (nested / "secret.txt").write_text("credential-like report payload\n")
        raise RuntimeError("simulated generator failure")

    monkeypatch.setattr(os, "unlink", record_unlink)
    monkeypatch.setattr(os, "rmdir", record_rmdir)
    monkeypatch.setattr(reporting, "write_figures", generate_tree_then_fail)

    with pytest.raises(BenchmarkFailure, match="^benchmark publication failed$"):
        publish_report(report_path, repository)

    assert removals == []
    assert (repository / "README.md").read_text() == original_root
    assert (repository / "benchmarks" / "README.md").read_text() == original_detail
    assert _git(repository, "status", "--porcelain=v1", "--untracked-files=all") == ""
    tombstones = list(git_dir.glob("benchmark-publication.*.tombstone"))
    assert len(tombstones) == 1
    assert tombstones[0].stat().st_mode & 0o777 == 0o700
    retained_entries = list(tombstones[0].iterdir())
    assert 1 <= len(retained_entries) <= 3
    retained_files = [path for path in tombstones[0].rglob("*") if path.is_file()]
    assert retained_files
    assert all(path.read_bytes() == b"" for path in retained_files)

    monkeypatch.setattr(reporting, "write_figures", _write_fake_publish_figures)
    destination = publish_report(report_path, repository)

    assert destination.is_dir()
    assert removals == []
    assert len(list(git_dir.glob("benchmark-publication.*.tombstone"))) == 2


def test_readme_temp_swap_after_tombstone_verification_preserves_foreign_and_retries(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    repository, report_path, original_root, original_detail = (
        _prepare_publish_repository(tmp_path)
    )
    git_dir = Path(_git(repository, "rev-parse", "--absolute-git-dir"))
    real_open = os.open
    real_write = os.write
    real_fstat = os.fstat
    real_identity_from_stat = reporting._identity_from_stat
    temporary_fd: int | None = None
    temporary_identity: reporting._PathIdentity | None = None
    write_failed = False
    swapped: list[tuple[Path, Path]] = []

    def record_temporary_open(
        path: str | os.PathLike[str],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        nonlocal temporary_fd
        fd = real_open(path, flags, mode, dir_fd=dir_fd)
        if isinstance(path, str) and path.endswith(".tmp"):
            temporary_fd = fd
        return fd

    def write_prefix_then_fail(fd: int, value: Any) -> int:
        nonlocal temporary_identity, write_failed
        if fd == temporary_fd and not write_failed:
            write_failed = True
            temporary_identity = real_identity_from_stat(real_fstat(fd))
            prefix = memoryview(value)[:32]
            real_write(fd, prefix)
            raise OSError("simulated README temporary write failure")
        return real_write(fd, value)

    def identify_then_swap(value: os.stat_result) -> Any:
        identity = real_identity_from_stat(value)
        if identity == temporary_identity and not swapped:
            candidates = [
                candidate
                for tombstone in git_dir.glob("benchmark-publication.*.tombstone")
                for candidate in tombstone.glob("entry.*.file")
                if candidate.lstat().st_dev == identity.device
                and candidate.lstat().st_ino == identity.inode
            ]
            if candidates:
                retained = candidates[0]
                moved = retained.with_name(f"{retained.name}.moved-owned")
                retained.rename(moved)
                retained.write_text("foreign README temporary\n")
                swapped.append((retained, moved))
        return identity

    monkeypatch.setattr(reporting, "write_figures", _write_fake_publish_figures)
    monkeypatch.setattr(os, "open", record_temporary_open)
    monkeypatch.setattr(os, "write", write_prefix_then_fail)
    monkeypatch.setattr(reporting, "_identity_from_stat", identify_then_swap)

    with pytest.raises(BenchmarkFailure, match="^benchmark publication failed$"):
        publish_report(report_path, repository)

    assert write_failed
    assert len(swapped) == 1
    foreign, moved = swapped[0]
    assert foreign.read_text() == "foreign README temporary\n"
    assert moved.read_bytes() == b""
    assert (repository / "README.md").read_text() == original_root
    assert (repository / "benchmarks" / "README.md").read_text() == original_detail
    assert list(repository.glob(".README.md.*.tmp")) == []
    assert list((repository / "benchmarks").glob(".README.md.*.tmp")) == []
    assert _git(repository, "status", "--porcelain=v1", "--untracked-files=all") == ""

    monkeypatch.setattr(os, "write", real_write)
    destination = publish_report(report_path, repository)

    assert destination.is_dir()
    assert foreign.read_text() == "foreign README temporary\n"


@pytest.mark.parametrize("kind", ["tree", "empty-directory", "file"])
def test_cleanup_swap_after_last_identity_check_does_not_delete_foreign_object(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, kind: str
) -> None:
    owned_path = tmp_path / "owned"
    if kind == "file":
        owned_path.write_text("owned\n")
    else:
        owned_path.mkdir()
        if kind == "tree":
            (owned_path / "owned.txt").write_text("owned\n")
    owned = reporting._OwnedPath(
        owned_path, reporting._require_kind(owned_path, directory=kind != "file")
    )
    tombstone = _test_tombstone(tmp_path)
    moved = tmp_path / "moved-owned"
    real_rename_noreplace_at = reporting._rename_noreplace_at
    swapped = False

    def swap_then_rename(
        source_fd: int, source_name: str, destination_fd: int, destination_name: str
    ) -> None:
        nonlocal swapped
        if source_name == owned_path.name and not swapped:
            swapped = True
            owned_path.rename(moved)
            if kind == "file":
                owned_path.write_text("foreign\n")
            else:
                owned_path.mkdir()
                if kind == "tree":
                    (owned_path / "foreign.txt").write_text("foreign\n")
        real_rename_noreplace_at(
            source_fd, source_name, destination_fd, destination_name
        )

    monkeypatch.setattr(reporting, "_rename_noreplace_at", swap_then_rename)

    if kind == "tree":
        reporting._remove_owned_directory(owned, tombstone)
        assert (owned_path / "foreign.txt").read_text() == "foreign\n"
        assert (moved / "owned.txt").read_bytes() == b""
    elif kind == "empty-directory":
        reporting._remove_owned_empty_directory(owned, tombstone)
        assert owned_path.is_dir()
    else:
        reporting._remove_owned_file(owned, tombstone)
        assert owned_path.read_text() == "foreign\n"
        assert moved.read_bytes() == b""
    assert moved.exists()


@pytest.mark.parametrize("kind", ["tree", "empty-directory", "file"])
def test_cleanup_swap_after_quarantine_verification_preserves_foreign_object(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, kind: str
) -> None:
    owned_path = tmp_path / "owned"
    if kind == "file":
        owned_path.write_text("owned\n")
    else:
        owned_path.mkdir()
        if kind == "tree":
            (owned_path / "owned.txt").write_text("owned\n")
    owned = reporting._OwnedPath(
        owned_path, reporting._require_kind(owned_path, directory=kind != "file")
    )
    tombstone = _test_tombstone(tmp_path)
    real_identity_from_stat = reporting._identity_from_stat
    swapped: list[tuple[Path, Path]] = []

    def identify_then_swap(value: os.stat_result) -> Any:
        identity = real_identity_from_stat(value)
        if reporting._same_object(identity, owned.identity) and not swapped:
            candidates = [
                candidate
                for candidate in tombstone.path.rglob("*")
                if candidate.name.startswith("entry.")
                and candidate.lstat().st_dev == owned.identity.device
                and candidate.lstat().st_ino == owned.identity.inode
            ]
            if candidates:
                quarantine = candidates[0]
                moved = quarantine.with_name(f"{quarantine.name}.moved-owned")
                quarantine.rename(moved)
                if kind == "file":
                    quarantine.write_text("foreign\n")
                else:
                    quarantine.mkdir()
                    if kind == "tree":
                        (quarantine / "foreign.txt").write_text("foreign\n")
                swapped.append((quarantine, moved))
        return identity

    monkeypatch.setattr(reporting, "_identity_from_stat", identify_then_swap)

    if kind == "tree":
        reporting._remove_owned_directory(owned, tombstone)
    elif kind == "empty-directory":
        reporting._remove_owned_empty_directory(owned, tombstone)
    else:
        reporting._remove_owned_file(owned, tombstone)

    assert len(swapped) == 1
    quarantine, moved = swapped[0]
    if kind == "tree":
        assert (quarantine / "foreign.txt").read_text() == "foreign\n"
    elif kind == "empty-directory":
        assert quarantine.is_dir()
    else:
        assert quarantine.read_text() == "foreign\n"
    assert moved.exists()
    if kind == "tree":
        assert (moved / "owned.txt").read_bytes() == b""
    elif kind == "file":
        assert moved.read_bytes() == b""


@pytest.mark.parametrize("kind", ["tree", "empty-directory", "file"])
@pytest.mark.parametrize("close_error", [OSError("close failed"), KeyboardInterrupt()])
def test_cleanup_finishes_committed_quarantine_before_parent_close_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    kind: str,
    close_error: BaseException,
) -> None:
    owned_path = tmp_path / "owned"
    if kind == "file":
        owned_path.write_text("owned\n")
    else:
        owned_path.mkdir()
        if kind == "tree":
            (owned_path / "owned.txt").write_text("owned\n")
    owned = reporting._OwnedPath(
        owned_path, reporting._require_kind(owned_path, directory=kind != "file")
    )
    tombstone = _test_tombstone(tmp_path)
    real_open = os.open
    real_close = os.close
    parent_fds: set[int] = set()
    injected = False

    def record_parent_open(
        path: str | os.PathLike[str],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        fd = real_open(path, flags, mode, dir_fd=dir_fd)
        if dir_fd is None and Path(path) == tmp_path:
            parent_fds.add(fd)
        return fd

    def close_parent_then_raise(fd: int) -> None:
        nonlocal injected
        should_raise = fd in parent_fds and not injected
        parent_fds.discard(fd)
        real_close(fd)
        if should_raise:
            injected = True
            raise close_error

    monkeypatch.setattr(os, "open", record_parent_open)
    monkeypatch.setattr(os, "close", close_parent_then_raise)

    with pytest.raises(type(close_error)) as raised:
        if kind == "tree":
            reporting._remove_owned_directory(owned, tombstone)
        elif kind == "empty-directory":
            reporting._remove_owned_empty_directory(owned, tombstone)
        else:
            reporting._remove_owned_file(owned, tombstone)

    if not isinstance(close_error, Exception):
        assert raised.value is close_error
    assert injected
    assert not owned_path.exists()
    assert tombstone.path.is_dir()
    assert all(
        path.read_bytes() == b"" for path in tombstone.path.rglob("*") if path.is_file()
    )


def test_rename_then_keyboard_interrupt_removes_owned_final_and_retries(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    repository, report_path, original_root, original_detail = (
        _prepare_publish_repository(tmp_path)
    )
    destination = repository / "benchmarks" / "results" / "20260805T000100Z"
    real_move = reporting._atomic_move_noreplace
    interrupted = False

    def rename_then_interrupt(source: Path, target: Path, **kwargs: Any) -> None:
        nonlocal interrupted
        real_move(source, target, **kwargs)
        if target == destination and not interrupted:
            interrupted = True
            raise KeyboardInterrupt

    monkeypatch.setattr(reporting, "write_figures", _write_fake_publish_figures)
    monkeypatch.setattr(reporting, "_atomic_move_noreplace", rename_then_interrupt)

    with pytest.raises(KeyboardInterrupt):
        publish_report(report_path, repository)

    assert (repository / "README.md").read_text() == original_root
    assert (repository / "benchmarks" / "README.md").read_text() == original_detail
    assert not destination.exists()

    monkeypatch.setattr(reporting, "_atomic_move_noreplace", real_move)
    published = publish_report(report_path, repository)
    assert published == destination


@pytest.mark.parametrize(
    "control_flow", [KeyboardInterrupt(), SystemExit(7), asyncio.CancelledError()]
)
def test_control_flow_during_compensation_is_re_raised_unchanged(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, control_flow: BaseException
) -> None:
    repository, report_path, original_root, original_detail = (
        _prepare_publish_repository(tmp_path)
    )
    destination = repository / "benchmarks" / "results" / "20260805T000100Z"
    real_atomic_text_if_unchanged = reporting._atomic_text_if_unchanged
    real_move = reporting._atomic_move_noreplace

    def fail_final_rename(source: Path, target: Path, **kwargs: Any) -> None:
        if target == destination:
            raise OSError("final rename failed")
        real_move(source, target, **kwargs)

    def interrupt_rollback(change: reporting._AtomicTextChange) -> None:
        if change.replacement in {original_root, original_detail}:
            raise control_flow
        real_atomic_text_if_unchanged(change)

    monkeypatch.setattr(reporting, "write_figures", _write_fake_publish_figures)
    monkeypatch.setattr(reporting, "_atomic_move_noreplace", fail_final_rename)
    monkeypatch.setattr(reporting, "_atomic_text_if_unchanged", interrupt_rollback)

    with pytest.raises(type(control_flow)) as raised:
        publish_report(report_path, repository)

    assert raised.value is control_flow


def test_ordinary_lock_release_failure_does_not_mask_keyboard_interrupt(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    repository, report_path, _, _ = _prepare_publish_repository(tmp_path)
    interruption = KeyboardInterrupt()
    real_open = os.open
    real_close = os.close
    lock_fds: set[int] = set()

    def record_lock_open(
        path: str | os.PathLike[str],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        fd = real_open(path, flags, mode, dir_fd=dir_fd)
        if Path(path).name == "benchmark-publication.lock":
            lock_fds.add(fd)
        return fd

    def close_then_fail(fd: int) -> None:
        real_close(fd)
        if fd in lock_fds:
            raise OSError("simulated close failure")

    def interrupt_generation(
        report: LiveBenchmarkReport, output_dir: Path
    ) -> tuple[Path, ...]:
        del report, output_dir
        raise interruption

    monkeypatch.setattr(os, "open", record_lock_open)
    monkeypatch.setattr(os, "close", close_then_fail)
    monkeypatch.setattr(reporting, "write_figures", interrupt_generation)

    with pytest.raises(KeyboardInterrupt) as raised:
        publish_report(report_path, repository)

    assert raised.value is interruption


def test_readme_change_during_prepared_temp_window_is_not_overwritten(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    repository, report_path, original_root, _ = _prepare_publish_repository(tmp_path)
    benchmark_readme = repository / "benchmarks" / "README.md"
    conflicting_detail = f"external\n{DETAIL_START}\nconflict\n{DETAIL_END}\n"
    real_fsync = os.fsync
    changed = False

    def fsync_then_change(fd: int) -> None:
        nonlocal changed
        real_fsync(fd)
        if not changed:
            changed = True
            benchmark_readme.write_text(conflicting_detail)

    monkeypatch.setattr(reporting, "write_figures", _write_fake_publish_figures)
    monkeypatch.setattr(os, "fsync", fsync_then_change)

    with pytest.raises(BenchmarkFailure, match="^benchmark publication failed$"):
        publish_report(report_path, repository)

    assert changed
    assert benchmark_readme.read_text() == conflicting_detail
    assert (repository / "README.md").read_text() == original_root


@pytest.mark.parametrize("readme_kind", ["benchmark", "root"])
@pytest.mark.parametrize("foreign_kind", ["file", "dangling-symlink"])
def test_readme_target_swap_at_exchange_is_restored_and_publication_aborts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, readme_kind: str, foreign_kind: str
) -> None:
    repository, report_path, original_root, original_detail = (
        _prepare_publish_repository(tmp_path)
    )
    root_readme = repository / "README.md"
    benchmark_readme = repository / "benchmarks" / "README.md"
    target = benchmark_readme if readme_kind == "benchmark" else root_readme
    original_target = original_detail if readme_kind == "benchmark" else original_root
    original_aside = target.with_name(f".{target.name}.concurrent-original")
    missing_target = target.with_name("missing-foreign-target")
    real_exchange = reporting._rename_exchange_at
    desired_commit = 1 if readme_kind == "benchmark" else 2
    commit_count = 0
    injected = False

    def swap_target_then_exchange(
        source_fd: int, source_name: str, destination_fd: int, destination_name: str
    ) -> None:
        nonlocal commit_count, injected
        if source_name.endswith(".tmp") and destination_name == "README.md":
            commit_count += 1
            if commit_count == desired_commit:
                injected = True
                target.rename(original_aside)
                if foreign_kind == "file":
                    target.write_text("foreign README\n")
                else:
                    target.symlink_to(missing_target)
        real_exchange(source_fd, source_name, destination_fd, destination_name)

    monkeypatch.setattr(reporting, "_rename_exchange_at", swap_target_then_exchange)
    monkeypatch.setattr(reporting, "write_figures", _write_fake_publish_figures)

    with pytest.raises(BenchmarkFailure, match="^benchmark publication failed$"):
        publish_report(report_path, repository)

    assert injected
    assert original_aside.read_text() == original_target
    if foreign_kind == "file":
        assert target.read_text() == "foreign README\n"
    else:
        assert target.is_symlink()
        assert os.readlink(target) == str(missing_target)
    other = root_readme if readme_kind == "benchmark" else benchmark_readme
    other_original = original_root if readme_kind == "benchmark" else original_detail
    assert other.read_text() == other_original


@pytest.mark.parametrize("parent_kind", ["root", "benchmark"])
def test_readme_parent_swap_at_exchange_uses_pinned_parent_and_aborts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, parent_kind: str
) -> None:
    repository = tmp_path / "repository"
    benchmark_parent = repository / "benchmarks"
    benchmark_parent.mkdir(parents=True)
    parent = repository if parent_kind == "root" else benchmark_parent
    target = parent / "README.md"
    target.write_text("original\n")
    target_identity = reporting._require_kind(target, directory=False)
    change = reporting._AtomicTextChange(
        path=target,
        snapshot="original\n",
        snapshot_identity=target_identity,
        replacement="replacement\n",
        tombstone=_test_tombstone(tmp_path),
    )
    moved_parent = parent.with_name(f"{parent.name}.moved-original")
    real_exchange = reporting._rename_exchange_at
    injected = False

    def swap_parent_then_exchange(
        source_fd: int, source_name: str, destination_fd: int, destination_name: str
    ) -> None:
        nonlocal injected
        if source_name.endswith(".tmp") and not injected:
            injected = True
            parent.rename(moved_parent)
            parent.mkdir(parents=True)
            (parent / "README.md").write_text("foreign parent README\n")
        real_exchange(source_fd, source_name, destination_fd, destination_name)

    monkeypatch.setattr(reporting, "_rename_exchange_at", swap_parent_then_exchange)

    with pytest.raises(BenchmarkFailure, match="^benchmark publication failed$"):
        reporting._atomic_text_if_unchanged(change)

    assert injected
    assert (parent / "README.md").read_text() == "foreign parent README\n"
    assert (moved_parent / "README.md").read_text() == "original\n"
    expected_names = (
        {"README.md", "benchmarks"} if parent_kind == "root" else {"README.md"}
    )
    assert {path.name for path in moved_parent.iterdir()} == expected_names


def test_atomic_text_fails_closed_when_exchange_is_unavailable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    target = tmp_path / "README.md"
    target.write_text("original\n")
    identity = reporting._require_kind(target, directory=False)
    change = reporting._AtomicTextChange(
        path=target,
        snapshot="original\n",
        snapshot_identity=identity,
        replacement="replacement\n",
        tombstone=_test_tombstone(tmp_path),
    )

    def unsupported_exchange(*args: object) -> None:
        del args
        raise OSError(errno.ENOTSUP, "exchange unavailable")

    monkeypatch.setattr(reporting, "_rename_exchange_at", unsupported_exchange)

    with pytest.raises(BenchmarkFailure, match="^benchmark publication failed$"):
        reporting._atomic_text_if_unchanged(change)

    assert target.read_text() == "original\n"
    assert list(tmp_path.glob(".*.tmp")) == []


def test_atomic_text_prepares_temporary_relative_to_pinned_parent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    target = tmp_path / "README.md"
    target.write_text("original\n")
    identity = reporting._require_kind(target, directory=False)
    change = reporting._AtomicTextChange(
        path=target,
        snapshot="original\n",
        snapshot_identity=identity,
        replacement="replacement\n",
        tombstone=_test_tombstone(tmp_path),
    )
    real_open = os.open
    relative_temp_opens: list[tuple[str, int]] = []

    def record_open(
        path: str | os.PathLike[str],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        if (
            isinstance(path, str)
            and path.startswith(".README.md.")
            and path.endswith(".tmp")
            and dir_fd is not None
        ):
            relative_temp_opens.append((path, dir_fd))
        return real_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(os, "open", record_open)

    reporting._atomic_text_if_unchanged(change)

    assert target.read_text() == "replacement\n"
    assert len(relative_temp_opens) == 2
    assert relative_temp_opens[0][0] == relative_temp_opens[1][0]


def test_open_entry_at_cannot_block_on_foreign_fifo_swap(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    target = tmp_path / "README.md"
    target.write_text("original\n")
    expected = reporting._require_kind(target, directory=False)
    original_aside = tmp_path / "README.original"
    parent_fd, _ = reporting._open_pinned_directory(tmp_path, None)
    real_open = os.open
    real_close = os.close
    swapped = False

    def swap_to_fifo_then_open(
        path: str | os.PathLike[str],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        nonlocal swapped
        if path == target.name and dir_fd == parent_fd and not swapped:
            swapped = True
            target.rename(original_aside)
            os.mkfifo(target)
            assert flags & os.O_NONBLOCK
        return real_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(os, "open", swap_to_fifo_then_open)
    try:
        assert (
            reporting._open_entry_at(parent_fd, target.name, expected, directory=False)
            is None
        )
    finally:
        real_close(parent_fd)

    assert swapped
    assert target.is_fifo()
    assert original_aside.read_text() == "original\n"


def test_open_entry_at_does_not_retry_ambiguous_mismatch_close(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    expected_path = tmp_path / "expected"
    foreign_path = tmp_path / "foreign"
    expected_path.write_text("expected\n")
    foreign_path.write_text("foreign\n")
    expected = reporting._require_kind(expected_path, directory=False)
    parent_fd, _ = reporting._open_pinned_directory(tmp_path, None)
    real_close = os.close
    close_calls = 0

    def close_then_raise(fd: int) -> None:
        nonlocal close_calls
        close_calls += 1
        real_close(fd)
        raise OSError("simulated ambiguous close failure")

    monkeypatch.setattr(os, "close", close_then_raise)
    try:
        with pytest.raises(OSError, match="entry descriptor cleanup failed"):
            reporting._open_entry_at(
                parent_fd, foreign_path.name, expected, directory=False
            )
    finally:
        real_close(parent_fd)

    assert close_calls == 1


def test_ordinary_atomic_temp_close_failure_does_not_mask_keyboard_interrupt(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    target = tmp_path / "README.md"
    target.write_text("original")
    target_identity = reporting._require_kind(target, directory=False)
    change = reporting._AtomicTextChange(
        path=target,
        snapshot="original",
        snapshot_identity=target_identity,
        replacement="replacement",
        tombstone=_test_tombstone(tmp_path),
    )
    interruption = KeyboardInterrupt()
    real_open = os.open
    real_write = os.write
    real_close = os.close
    temporary_fd: int | None = None

    def capture_temporary_open(
        path: str | os.PathLike[str],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        nonlocal temporary_fd
        fd = real_open(path, flags, mode, dir_fd=dir_fd)
        if isinstance(path, str) and path.endswith(".tmp"):
            temporary_fd = fd
        return fd

    def interrupting_write(fd: int, value: Any) -> int:
        if fd == temporary_fd:
            raise interruption
        return real_write(fd, value)

    def failing_temporary_close(fd: int) -> None:
        real_close(fd)
        if fd == temporary_fd:
            raise OSError("simulated temp close failure")

    monkeypatch.setattr(os, "open", capture_temporary_open)
    monkeypatch.setattr(os, "write", interrupting_write)
    monkeypatch.setattr(os, "close", failing_temporary_close)

    with pytest.raises(KeyboardInterrupt) as raised:
        reporting._prepare_atomic_text(change)

    assert raised.value is interruption
    assert list(tmp_path.glob(".*.tmp")) == []


def test_clean_head_change_during_generation_aborts_publication(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    repository, report_path, original_root, original_detail = (
        _prepare_publish_repository(tmp_path)
    )

    def generate_then_commit(
        report: LiveBenchmarkReport, output_dir: Path
    ) -> tuple[Path, ...]:
        paths = _write_fake_publish_figures(report, output_dir)
        _git(repository, "commit", "--quiet", "--allow-empty", "-m", "concurrent")
        return paths

    monkeypatch.setattr(reporting, "write_figures", generate_then_commit)

    with pytest.raises(
        BenchmarkFailure, match="^benchmark publication repository is not publishable$"
    ):
        publish_report(report_path, repository)

    assert (repository / "README.md").read_text() == original_root
    assert (repository / "benchmarks" / "README.md").read_text() == original_detail
    assert not (repository / "benchmarks" / "results" / "20260805T000100Z").exists()


def test_dirty_edit_during_generation_aborts_publication(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    repository, report_path, original_root, original_detail = (
        _prepare_publish_repository(tmp_path)
    )

    def generate_then_edit(
        report: LiveBenchmarkReport, output_dir: Path
    ) -> tuple[Path, ...]:
        paths = _write_fake_publish_figures(report, output_dir)
        (repository / "notes.txt").write_text("concurrent dirty edit\n")
        return paths

    monkeypatch.setattr(reporting, "write_figures", generate_then_edit)

    with pytest.raises(
        BenchmarkFailure, match="^benchmark publication repository is not publishable$"
    ):
        publish_report(report_path, repository)

    assert (repository / "README.md").read_text() == original_root
    assert (repository / "benchmarks" / "README.md").read_text() == original_detail
    assert not (repository / "benchmarks" / "results" / "20260805T000100Z").exists()


def test_lock_symlink_is_rejected_without_touching_target(tmp_path: Path) -> None:
    repository, report_path, original_root, original_detail = (
        _prepare_publish_repository(tmp_path)
    )
    git_dir = Path(_git(repository, "rev-parse", "--absolute-git-dir"))
    outside = tmp_path / "outside-lock-target"
    outside.write_text("outside\n")
    (git_dir / "benchmark-publication.lock").symlink_to(outside)

    with pytest.raises(
        BenchmarkFailure, match="^benchmark publication repository is not publishable$"
    ):
        publish_report(report_path, repository)

    assert outside.read_text() == "outside\n"
    assert (repository / "README.md").read_text() == original_root
    assert (repository / "benchmarks" / "README.md").read_text() == original_detail


def test_nonregular_lock_descriptor_is_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    lock_fd = 41
    closed: list[int] = []

    monkeypatch.setattr(
        reporting,
        "_resolve_repository_root",
        lambda repository_root: (repository_root, repository_root),
    )
    monkeypatch.setattr(os, "open", lambda *args, **kwargs: lock_fd)
    monkeypatch.setattr(os, "fstat", lambda fd: tmp_path.stat())
    monkeypatch.setattr(os, "close", closed.append)

    with pytest.raises(
        BenchmarkFailure, match="^benchmark publication repository is not publishable$"
    ):
        with reporting._publication_lock(tmp_path):
            raise AssertionError("nonregular lock entered the critical section")

    assert closed == [lock_fd]


def test_results_symlink_component_is_rejected(tmp_path: Path) -> None:
    repository, report_path, original_root, original_detail = (
        _prepare_publish_repository(tmp_path)
    )
    outside = tmp_path / "outside-results"
    outside.mkdir()
    results = repository / "benchmarks" / "results"
    results.symlink_to(outside, target_is_directory=True)
    _git(repository, "add", "benchmarks/results")
    _git(repository, "commit", "--quiet", "-m", "tracked results symlink")
    report = _valid_report(revision=_git(repository, "rev-parse", "HEAD"))
    report_path = write_report(report, report_path.parent, forbidden_values=())

    with pytest.raises(
        BenchmarkFailure, match="^benchmark publication repository is not publishable$"
    ):
        publish_report(report_path, repository)

    assert list(outside.iterdir()) == []
    assert (repository / "README.md").read_text() == original_root
    assert (repository / "benchmarks" / "README.md").read_text() == original_detail


def test_dangling_final_symlink_collides_before_readme_mutation(tmp_path: Path) -> None:
    repository, report_path, original_root, original_detail = (
        _prepare_publish_repository(tmp_path)
    )
    results = repository / "benchmarks" / "results"
    results.mkdir()
    destination = results / "20260805T000100Z"
    destination.symlink_to(tmp_path / "missing-target", target_is_directory=True)
    _git(repository, "add", "benchmarks/results/20260805T000100Z")
    _git(repository, "commit", "--quiet", "-m", "dangling publication collision")
    report = _valid_report(revision=_git(repository, "rev-parse", "HEAD"))
    report_path = write_report(report, report_path.parent, forbidden_values=())

    with pytest.raises(
        BenchmarkFailure, match="^published benchmark timestamp already exists$"
    ):
        publish_report(report_path, repository)

    assert destination.is_symlink()
    assert (repository / "README.md").read_text() == original_root
    assert (repository / "benchmarks" / "README.md").read_text() == original_detail


@pytest.mark.parametrize("collision_kind", ["empty-directory", "symlink", "file"])
def test_late_final_collision_at_commit_boundary_is_not_overwritten(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, collision_kind: str
) -> None:
    repository, report_path, original_root, original_detail = (
        _prepare_publish_repository(tmp_path)
    )
    destination = repository / "benchmarks" / "results" / "20260805T000100Z"
    outside = tmp_path / "outside-final-target"
    outside.write_text("outside\n")
    real_move = getattr(reporting, "_atomic_move_noreplace", None)
    injected = False

    def collide_at_commit(source: Path, target: Path, **kwargs: Any) -> None:
        nonlocal injected
        if target == destination and not injected:
            injected = True
            if collision_kind == "empty-directory":
                target.mkdir()
            elif collision_kind == "symlink":
                target.symlink_to(outside)
            else:
                target.write_text("foreign\n")
        if real_move is None:
            os.rename(source, target)
        else:
            real_move(source, target, **kwargs)

    monkeypatch.setattr(
        reporting, "_atomic_move_noreplace", collide_at_commit, raising=False
    )
    monkeypatch.setattr(reporting, "write_figures", _write_fake_publish_figures)

    with pytest.raises(
        BenchmarkFailure, match="^published benchmark timestamp already exists$"
    ):
        publish_report(report_path, repository)

    assert injected
    if collision_kind == "empty-directory":
        assert destination.is_dir()
        assert list(destination.iterdir()) == []
    elif collision_kind == "symlink":
        assert destination.is_symlink()
        assert outside.read_text() == "outside\n"
    else:
        assert destination.read_text() == "foreign\n"
    assert (repository / "README.md").read_text() == original_root
    assert (repository / "benchmarks" / "README.md").read_text() == original_detail


@pytest.mark.parametrize(
    "release_error", [OSError("close failed"), KeyboardInterrupt(), SystemExit(9)]
)
def test_lock_release_failure_after_final_rename_compensates_and_retry_succeeds(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, release_error: BaseException
) -> None:
    repository, report_path, original_root, original_detail = (
        _prepare_publish_repository(tmp_path)
    )
    destination = repository / "benchmarks" / "results" / "20260805T000100Z"
    real_open = os.open
    real_close = os.close
    lock_fds: set[int] = set()

    def record_lock_open(
        path: str | os.PathLike[str],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        fd = real_open(path, flags, mode, dir_fd=dir_fd)
        if Path(path).name == "benchmark-publication.lock":
            lock_fds.add(fd)
        return fd

    def close_then_fail(fd: int) -> None:
        fail = fd in lock_fds
        lock_fds.discard(fd)
        real_close(fd)
        if fail:
            raise release_error

    monkeypatch.setattr(reporting, "write_figures", _write_fake_publish_figures)
    monkeypatch.setattr(os, "open", record_lock_open)
    monkeypatch.setattr(os, "close", close_then_fail)

    if isinstance(release_error, Exception):
        with pytest.raises(BenchmarkFailure, match="repository is not publishable"):
            publish_report(report_path, repository)
    else:
        with pytest.raises(type(release_error)) as raised:
            publish_report(report_path, repository)
        assert raised.value is release_error

    assert not destination.exists()
    assert (repository / "README.md").read_text() == original_root
    assert (repository / "benchmarks" / "README.md").read_text() == original_detail
    assert _git(repository, "status", "--porcelain=v1", "--untracked-files=all") == ""

    monkeypatch.setattr(os, "close", real_close)
    published = publish_report(report_path, repository)
    assert published == destination
