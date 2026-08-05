from __future__ import annotations

import csv
import json
import math
import re
import shutil
import statistics
from collections import Counter
from collections.abc import Mapping, Sequence
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


def _atomic_text(path: Path, content: str) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        temporary.write_text(content)
        temporary.replace(path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


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


def publish_report(report_path: Path, repository_root: Path) -> Path:
    report = _load_report(report_path)
    validate_publishable(report)
    source_dir = report_path.parent
    required = {"report.json", "samples.csv", *_PUBLISH_FIGURE_FILENAMES}
    if any(not (source_dir / filename).is_file() for filename in required):
        raise BenchmarkFailure("benchmark artifacts are not publishable")

    root_readme = repository_root / "README.md"
    benchmark_readme = repository_root / "benchmarks" / "README.md"
    try:
        root_text = root_readme.read_text()
        benchmark_text = benchmark_readme.read_text()
    except OSError as error:
        raise BenchmarkFailure("README files are not publishable") from error

    timestamp = _artifact_timestamp(report["completed_at"])
    rendered_root = _replace_marker(
        root_text, OVERALL_START, OVERALL_END, _overall_markdown(report)
    )
    rendered_benchmark = _replace_marker(
        benchmark_text, DETAIL_START, DETAIL_END, _detail_markdown(report, timestamp)
    )

    destination = repository_root / "benchmarks" / "results" / timestamp
    try:
        destination.mkdir(parents=True, exist_ok=False)
    except FileExistsError as error:
        raise BenchmarkFailure(
            "published benchmark timestamp already exists"
        ) from error

    benchmark_replaced = False
    root_replaced = False
    try:
        write_report(report, destination, forbidden_values=())
        write_csv(report, destination)
        write_figures(report, destination)
        _atomic_text(benchmark_readme, rendered_benchmark)
        benchmark_replaced = True
        _atomic_text(root_readme, rendered_root)
        root_replaced = True
    except Exception as error:
        rollback_failures: list[Exception] = []
        for replaced, path, original in (
            (root_replaced, root_readme, root_text),
            (benchmark_replaced, benchmark_readme, benchmark_text),
        ):
            if not replaced:
                continue
            try:
                _atomic_text(path, original)
            except Exception as rollback_error:
                rollback_failures.append(rollback_error)
        try:
            shutil.rmtree(destination)
        except Exception as rollback_error:
            rollback_failures.append(rollback_error)
        if rollback_failures:
            raise BenchmarkFailure(
                "benchmark publication failed and rollback was incomplete"
            ) from ExceptionGroup("publication rollback failures", rollback_failures)
        raise BenchmarkFailure("benchmark publication failed") from error
    return destination
