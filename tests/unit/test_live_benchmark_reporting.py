import csv
import copy
from pathlib import Path
from collections.abc import Callable
from typing import Any, cast

import pytest

from benchmarks.live.models import (
    BenchmarkConfig,
    BenchmarkFailure,
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
    validate_publishable,
    write_csv,
    write_figures,
)
from benchmarks.live.results import SampleRecorder, write_report


PROVIDERS = ("ccxt", "sdk", "async-hyperliquid")


def _valid_report() -> LiveBenchmarkReport:
    config = BenchmarkConfig()
    recorder = SampleRecorder(
        config=config,
        environment={
            "network": "testnet",
            "python": "3.12.13",
            "platform": "darwin-arm64",
        },
        versions={"async-hyperliquid": "1.0.0rc1", "sdk": "0.24.0", "ccxt": "4.5.71"},
        git=GitMetadata(revision="abc123", dirty=False),
    )
    for round_index in range(30):
        recorder.record(
            LatencySample(
                suite="cancel-id",
                provider="async-hyperliquid",
                operation="cancel_by_oid",
                round_index=round_index,
                provider_order=0,
                duration_ns=10_000_000 + round_index,
            )
        )
        recorder.record(
            LatencySample(
                suite="cancel-id",
                provider="async-hyperliquid",
                operation="cancel_by_cloid",
                round_index=round_index,
                provider_order=1,
                duration_ns=20_000_000 + round_index,
            )
        )
        for provider_order, provider in enumerate(PROVIDERS):
            base = {
                "ccxt": 100_000_000,
                "sdk": 110_000_000,
                "async-hyperliquid": 90_000_000,
            }[provider]
            recorder.record(
                LatencySample(
                    suite="providers",
                    provider=provider,
                    operation="place_batch_2",
                    round_index=round_index,
                    provider_order=provider_order,
                    duration_ns=base + round_index,
                )
            )
            recorder.record(
                LatencySample(
                    suite="providers",
                    provider=provider,
                    operation="cancel_batch_2_by_oid",
                    round_index=round_index,
                    provider_order=provider_order,
                    duration_ns=base + 100_000_000 + round_index,
                )
            )
    return recorder.build_report(
        valid=True,
        failure_reason=None,
        cleanup_ok=True,
        started_at="2026-08-05T00:00:00Z",
        completed_at="2026-08-05T00:01:00Z",
    )


def test_figure_series_keeps_operations_and_providers_separate() -> None:
    series = figure_series(_valid_report(), "providers")

    assert set(series) == {"place_batch_2", "cancel_batch_2_by_oid"}
    assert set(series["place_batch_2"]) == set(PROVIDERS)
    assert series["place_batch_2"]["async-hyperliquid"][0] == 90_000_000
    assert series["cancel_batch_2_by_oid"]["sdk"][0] == 210_000_000


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
    assert len(rows) == 240
    assert not ({"oid", "cloid", "address", "signature"} & rows[0].keys())


@pytest.mark.parametrize(
    "mutation",
    [
        lambda report: report.update(valid=False),
        lambda report: report.update(cleanup_ok=False),
        lambda report: report.update(schema_version=2),
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
    report["samples"][8]["round_index"] = 0

    with pytest.raises(BenchmarkFailure, match="publish"):
        validate_publishable(report)


def test_figures_are_written_as_png_and_svg(tmp_path: Path) -> None:
    pytest.importorskip("matplotlib")

    paths = write_figures(_valid_report(), tmp_path)

    assert {path.name for path in paths} == set(FIGURE_FILENAMES)
    for path in paths:
        assert path.stat().st_size > 100
    assert (tmp_path / "cancel-id-latency.png").read_bytes().startswith(b"\x89PNG")
    assert b"<svg" in (tmp_path / "providers-latency.svg").read_bytes()[:1000]


@pytest.mark.parametrize(
    ("suite", "expected"),
    [
        ("cancel-id", {"cancel-id-latency.png", "cancel-id-latency.svg"}),
        ("providers", {"providers-latency.png", "providers-latency.svg"}),
    ],
)
def test_figures_support_one_selected_suite(
    suite: str, expected: set[str], tmp_path: Path
) -> None:
    pytest.importorskip("matplotlib")
    report = copy.deepcopy(_valid_report())
    report["samples"] = [
        sample for sample in report["samples"] if sample["suite"] == suite
    ]
    report["summaries"] = {suite: report["summaries"][suite]}

    paths = write_figures(report, tmp_path)

    assert {path.name for path in paths} == expected


def test_publish_updates_detailed_and_overall_markers_from_one_report(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    report_path = write_report(_valid_report(), source, forbidden_values=())
    write_csv(_valid_report(), source)
    for filename in FIGURE_FILENAMES:
        (source / filename).write_bytes(b"safe benchmark figure")

    (tmp_path / "README.md").write_text(
        f"root before\n{OVERALL_START}\nold overall\n{OVERALL_END}\nroot after\n"
    )
    benchmarks = tmp_path / "benchmarks"
    benchmarks.mkdir()
    (benchmarks / "README.md").write_text(
        f"benchmark before\n{DETAIL_START}\nold detail\n{DETAIL_END}\nbenchmark after\n"
    )

    published = publish_report(report_path, tmp_path)

    assert published.name == "20260805T000100Z"
    assert sorted(path.name for path in published.iterdir()) == sorted(
        ("report.json", "samples.csv", *FIGURE_FILENAMES)
    )
    root_readme = (tmp_path / "README.md").read_text()
    detail_readme = (benchmarks / "README.md").read_text()
    assert root_readme.startswith("root before\n")
    assert root_readme.endswith("root after\n")
    assert "old overall" not in root_readme
    assert "#### Published live Exchange result" in root_readme
    assert "OID" in root_readme
    assert "async-hyperliquid" in root_readme
    assert detail_readme.startswith("benchmark before\n")
    assert detail_readme.endswith("benchmark after\n")
    assert "old detail" not in detail_readme
    assert "240 weight/minute" in detail_readme
    assert "results/20260805T000100Z/providers-latency.svg" in detail_readme


def test_publish_requires_exactly_one_marker_pair(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    report_path = write_report(_valid_report(), source, forbidden_values=())
    write_csv(_valid_report(), source)
    for filename in FIGURE_FILENAMES:
        (source / filename).write_bytes(b"safe benchmark figure")
    (tmp_path / "README.md").write_text("missing markers\n")
    benchmarks = tmp_path / "benchmarks"
    benchmarks.mkdir()
    (benchmarks / "README.md").write_text(f"{DETAIL_START}\nold\n{DETAIL_END}\n")

    with pytest.raises(BenchmarkFailure, match="README marker"):
        publish_report(report_path, tmp_path)

    assert (tmp_path / "README.md").read_text() == "missing markers\n"
