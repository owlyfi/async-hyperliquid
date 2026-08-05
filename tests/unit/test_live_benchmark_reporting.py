import csv
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
        git=GitMetadata(revision="a" * 40, dirty=False),
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
    assert report["config"]["workload"] == (
        "cancel-id-concurrent-batch20-singles20-10-per-method-v1"
    )
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
    source = tmp_path / "source"
    source.mkdir()
    report_path = write_report(_valid_report(), source, forbidden_values=())
    write_csv(_valid_report(), source)
    (source / "samples.csv").write_text("tampered source CSV\n")
    for filename in FIGURE_FILENAMES[:2]:
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
        ("report.json", "samples.csv", *FIGURE_FILENAMES[:2])
    )
    assert (
        (published / "samples.csv")
        .read_text()
        .startswith("suite,provider,operation,round_index,provider_order,duration_ns\n")
    )
    assert (published / "cancel-id-latency.png").read_bytes().startswith(b"\x89PNG")
    root_readme = (tmp_path / "README.md").read_text()
    detail_readme = (benchmarks / "README.md").read_text()
    assert root_readme.startswith("root before\n")
    assert root_readme.endswith("root after\n")
    assert "old overall" not in root_readme
    assert "#### Published live Exchange result" in root_readme
    assert "OID" in root_readme
    assert "concurrency=20 (10 OID + 10 CLOID)" in root_readme
    assert "Overall equal-weight ranking" not in root_readme
    assert detail_readme.startswith("benchmark before\n")
    assert detail_readme.endswith("benchmark after\n")
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
    source = tmp_path / "source"
    source.mkdir()
    report_path = write_report(_valid_report(), source, forbidden_values=())
    write_csv(_valid_report(), source)
    for filename in FIGURE_FILENAMES[:2]:
        (source / filename).write_bytes(b"safe benchmark figure")
    (tmp_path / "README.md").write_text("missing markers\n")
    benchmarks = tmp_path / "benchmarks"
    benchmarks.mkdir()
    (benchmarks / "README.md").write_text(f"{DETAIL_START}\nold\n{DETAIL_END}\n")

    with pytest.raises(BenchmarkFailure, match="README marker"):
        publish_report(report_path, tmp_path)

    assert (tmp_path / "README.md").read_text() == "missing markers\n"


def test_publish_rejects_noncanonical_completion_timestamp_before_mutation(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    report = _valid_report()
    report["completed_at"] = "0001-01-01T00:00:00+23:59"
    report_path = write_report(report, source, forbidden_values=())
    write_csv(report, source)
    for filename in FIGURE_FILENAMES[:2]:
        (source / filename).write_bytes(b"safe benchmark figure")
    original_root = f"root\n{OVERALL_START}\nold overall\n{OVERALL_END}\n"
    original_detail = f"detail\n{DETAIL_START}\nold detail\n{DETAIL_END}\n"
    (tmp_path / "README.md").write_text(original_root)
    benchmarks = tmp_path / "benchmarks"
    benchmarks.mkdir()
    (benchmarks / "README.md").write_text(original_detail)

    with pytest.raises(BenchmarkFailure, match="^report schema is not publishable$"):
        publish_report(report_path, tmp_path)

    assert (tmp_path / "README.md").read_text() == original_root
    assert (benchmarks / "README.md").read_text() == original_detail
    assert not (benchmarks / "results").exists()


def test_publish_rolls_back_both_readmes_and_artifacts_on_second_replace_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    pytest.importorskip("matplotlib")
    source = tmp_path / "source"
    source.mkdir()
    report_path = write_report(_valid_report(), source, forbidden_values=())
    write_csv(_valid_report(), source)
    for filename in FIGURE_FILENAMES[:2]:
        (source / filename).write_bytes(b"source figure")
    original_root = f"root\n{OVERALL_START}\nold overall\n{OVERALL_END}\n"
    original_detail = f"detail\n{DETAIL_START}\nold detail\n{DETAIL_END}\n"
    (tmp_path / "README.md").write_text(original_root)
    benchmarks = tmp_path / "benchmarks"
    benchmarks.mkdir()
    (benchmarks / "README.md").write_text(original_detail)
    real_atomic_text = reporting._atomic_text
    calls = 0

    def fail_second_replace(path: Path, content: str) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("simulated second replacement failure")
        real_atomic_text(path, content)

    monkeypatch.setattr(reporting, "_atomic_text", fail_second_replace)

    with pytest.raises(BenchmarkFailure, match="publication failed"):
        publish_report(report_path, tmp_path)

    assert (tmp_path / "README.md").read_text() == original_root
    assert (benchmarks / "README.md").read_text() == original_detail
    assert not (benchmarks / "results" / "20260805T000100Z").exists()
