from __future__ import annotations

import csv
import json
import math
import shutil
import statistics
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

from .models import BenchmarkFailure, LatencySummary, LiveBenchmarkReport
from .results import assert_report_is_sanitized, summarize_ns


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
_PROVIDERS = ("async-hyperliquid", "sdk", "ccxt")
_ROTATION_PROVIDERS = ("ccxt", "sdk", "async-hyperliquid")
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
            writer = csv.DictWriter(handle, fieldnames=_CSV_FIELDS)
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
        cancel_labels = ("OID", "CLOID")
        cancel_figure, cancel_axes = plt.subplots(1, 2, figsize=(12, 5))
        _distribution_panel(
            cancel_axes[0],
            cancel_values,
            cancel_labels,
            title="Cancel latency distribution",
        )
        _comparison_panel(
            cancel_axes[1], cancel_values, cancel_labels, title="Cancel median and p95"
        )
        cancel_figure.tight_layout()
        cancel_paths = tuple(output_dir / filename for filename in FIGURE_FILENAMES[:2])
        for path in cancel_paths:
            cancel_figure.savefig(path, dpi=160 if path.suffix == ".png" else None)
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
            provider_figure.savefig(path, dpi=160 if path.suffix == ".png" else None)
        plt.close(provider_figure)
        paths.extend(provider_paths)

    if not paths:
        raise BenchmarkFailure("report has no supported figure samples")
    return tuple(paths)


def _expected_counts() -> Counter[tuple[str, str, str]]:
    expected = Counter(
        {
            ("cancel-id", "async-hyperliquid", "cancel_by_oid"): 30,
            ("cancel-id", "async-hyperliquid", "cancel_by_cloid"): 30,
        }
    )
    for provider in ("ccxt", "sdk", "async-hyperliquid"):
        expected[("providers", provider, "place_batch_2")] = 30
        expected[("providers", provider, "cancel_batch_2_by_oid")] = 30
    return expected


def _expected_provider_order(
    key: tuple[str, str, str], round_index: int, warmups: int
) -> int:
    suite, provider, operation = key
    logical_round = warmups + round_index
    if suite == "cancel-id":
        oid_order = 0 if logical_round % 2 == 0 else 1
        return oid_order if operation == "cancel_by_oid" else 1 - oid_order
    offset = logical_round % len(_ROTATION_PROVIDERS)
    rotated = _ROTATION_PROVIDERS[offset:] + _ROTATION_PROVIDERS[:offset]
    return rotated.index(provider)


def _is_git_revision(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 40
        and all(character in "0123456789abcdef" for character in value)
    )


def _is_safe_environment(environment: Mapping[str, object]) -> bool:
    if set(environment) != {"network", "python", "platform"}:
        return False
    return all(
        isinstance(value, str)
        and 0 < len(value) <= 100
        and all(character.isalnum() or character in ".-_" for character in value)
        for value in environment.values()
    )


def validate_publishable(report: LiveBenchmarkReport) -> None:
    try:
        config = report["config"]
        versions = report["versions"]
        git = report["git"]
        if (
            report["schema_version"] != 1
            or not report["valid"]
            or report["failure_reason"] is not None
            or not report["cleanup_ok"]
            or config
            != {
                "rounds": 30,
                "warmups": 3,
                "interval_ns": 250_000_000,
                "coin": "BTC",
                "target_notional": 11.0,
                "buy_multiplier": 0.9,
                "sell_multiplier": 1.1,
            }
            or versions.get("async-hyperliquid") != "1.0.0rc1"
            or versions.get("sdk") != "0.24.0"
            or versions.get("ccxt") != "4.5.71"
            or not _is_safe_environment(report["environment"])
            or report["environment"].get("network") != "testnet"
            or git.get("dirty") is not False
            or not _is_git_revision(git.get("revision"))
        ):
            raise BenchmarkFailure("report is not publishable")
        actual = Counter(
            (sample["suite"], sample["provider"], sample["operation"])
            for sample in report["samples"]
        )
        if actual != _expected_counts():
            raise BenchmarkFailure("report sample shape is not publishable")

        grouped: dict[tuple[str, str, str], list[int]] = {}
        rounds: dict[tuple[str, str, str], set[int]] = {}
        for sample in report["samples"]:
            if set(sample) != set(_CSV_FIELDS):
                raise BenchmarkFailure("report sample schema is not publishable")
            key = (sample["suite"], sample["provider"], sample["operation"])
            round_index = sample["round_index"]
            provider_order = sample["provider_order"]
            if (
                isinstance(round_index, bool)
                or not isinstance(round_index, int)
                or isinstance(provider_order, bool)
                or not isinstance(provider_order, int)
                or provider_order < 0
                or provider_order > (1 if key[0] == "cancel-id" else 2)
                or provider_order
                != _expected_provider_order(
                    key, round_index, cast(int, config["warmups"])
                )
            ):
                raise BenchmarkFailure("report sample values are not publishable")
            grouped.setdefault(key, []).append(sample["duration_ns"])
            rounds.setdefault(key, set()).add(round_index)
        expected_rounds = set(range(30))
        if any(indices != expected_rounds for indices in rounds.values()):
            raise BenchmarkFailure("report measured rounds are not publishable")

        rebuilt: dict[str, dict[str, dict[str, LatencySummary]]] = {}
        for (suite, provider, operation), values in grouped.items():
            rebuilt.setdefault(suite, {}).setdefault(operation, {})[provider] = (
                summarize_ns(values)
            )
        if report["summaries"] != rebuilt:
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


def _cancel_comparison(report: LiveBenchmarkReport) -> tuple[str, float]:
    oid = _summary(report, "cancel-id", "cancel_by_oid", "async-hyperliquid")[
        "median_ns"
    ]
    cloid = _summary(report, "cancel-id", "cancel_by_cloid", "async-hyperliquid")[
        "median_ns"
    ]
    winner = "OID" if oid <= cloid else "CLOID"
    return winner, max(oid, cloid) / min(oid, cloid)


def _combined_scores(report: LiveBenchmarkReport) -> list[tuple[str, float]]:
    scores = []
    for provider in _PROVIDERS:
        place = _summary(report, "providers", "place_batch_2", provider)["median_ns"]
        cancel = _summary(report, "providers", "cancel_batch_2_by_oid", provider)[
            "median_ns"
        ]
        scores.append((provider, math.sqrt(place * cancel)))
    return sorted(scores, key=lambda item: item[1])


def _detail_markdown(report: LiveBenchmarkReport, artifact_dir: str) -> str:
    winner, ratio = _cancel_comparison(report)
    lines = [
        "## Published live Exchange benchmark",
        "",
        f"Validated testnet run completed `{report['completed_at']}`. The runner used ",
        "three warmup rounds, 30 measured rounds, and a maximum controlled rate of ",
        "240 weight/minute. Initialization, market metadata, mid lookup, pacing, and ",
        "cleanup are excluded from measured latency.",
        "",
        "| Environment | Value |",
        "|---|---|",
    ]
    for key, value in sorted(report["environment"].items()):
        lines.append(f"| {key} | {value} |")
    for key, value in sorted(report["versions"].items()):
        lines.append(f"| {key} | {value} |")
    lines.extend(
        [
            "",
            "### OID versus CLOID cancellation",
            "",
            f"{winner} had the lower median latency; the slower median was {ratio:.3f}x the faster median.",
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
            f"![OID and CLOID latency](results/{artifact_dir}/cancel-id-latency.svg)",
            "",
            "### Provider comparison",
            "",
            "| Operation | Provider | Median (ms) | MAD (ms) | p95 (ms) |",
            "|---|---|---:|---:|---:|",
        ]
    )
    for operation in ("place_batch_2", "cancel_batch_2_by_oid"):
        for provider in _PROVIDERS:
            summary = _summary(report, "providers", operation, provider)
            lines.append(
                f"| {operation} | {provider} | {_ms(summary['median_ns'])} | "
                f"{_ms(summary['mad_ns'])} | {_ms(summary['p95_ns'])} |"
            )
    lines.extend(
        [
            "",
            f"![Provider place and cancel latency](results/{artifact_dir}/providers-latency.svg)",
            "",
            "### Equal-weight overall latency",
            "",
            "| Rank | Provider | Geometric mean of place/cancel medians (ms) |",
            "|---:|---|---:|",
        ]
    )
    for rank, (provider, score) in enumerate(_combined_scores(report), start=1):
        lines.append(f"| {rank} | {provider} | {_ms(score)} |")
    lines.extend(
        [
            "",
            "Artifacts: [sanitized JSON](results/"
            f"{artifact_dir}/report.json), [sample CSV](results/{artifact_dir}/samples.csv).",
            "",
            "These measurements describe one testnet run, not exchange capacity. Shared-IP traffic, "
            "geography, testnet load, dependency versions, and network conditions can change results.",
        ]
    )
    return "\n".join(lines)


def _overall_markdown(report: LiveBenchmarkReport) -> str:
    winner, ratio = _cancel_comparison(report)
    lines = [
        "#### Published live Exchange result",
        "",
        f"On the validated testnet run, {winner} cancellation had the lower median; the slower "
        f"identifier was {ratio:.3f}x the faster median.",
        "",
        "| Operation | Provider | Median (ms) | p95 (ms) |",
        "|---|---|---:|---:|",
    ]
    for operation in ("place_batch_2", "cancel_batch_2_by_oid"):
        ranked = sorted(
            (
                (provider, _summary(report, "providers", operation, provider))
                for provider in _PROVIDERS
            ),
            key=lambda item: item[1]["median_ns"],
        )
        for provider, summary in ranked:
            lines.append(
                f"| {operation} | {provider} | {_ms(summary['median_ns'])} | {_ms(summary['p95_ns'])} |"
            )
    lines.extend(
        [
            "",
            "Overall equal-weight ranking: "
            + ", ".join(
                f"{rank}. {provider} ({_ms(score)} ms)"
                for rank, (provider, score) in enumerate(
                    _combined_scores(report), start=1
                )
            )
            + ".",
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
    except ValueError as error:
        raise BenchmarkFailure("report completion time is not publishable") from error
    if parsed.tzinfo is None:
        raise BenchmarkFailure("report completion time is not publishable")
    return parsed.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def publish_report(report_path: Path, repository_root: Path) -> Path:
    report = _load_report(report_path)
    validate_publishable(report)
    source_dir = report_path.parent
    required = {"report.json", "samples.csv", *FIGURE_FILENAMES}
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
        shutil.copy2(report_path, destination / "report.json")
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
