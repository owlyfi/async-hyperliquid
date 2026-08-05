import json
from collections.abc import Sequence

import pytest

from benchmarks.live.models import BenchmarkConfig, BenchmarkFailure, LatencySample
from benchmarks.live.results import (
    SampleRecorder,
    assert_report_is_sanitized,
    parse_cancel_success,
    parse_ccxt_cancel_success,
    parse_ccxt_resting_oids,
    parse_resting_oids,
    summarize_ns,
)


def _place_response(*statuses: object) -> dict[str, object]:
    return {
        "status": "ok",
        "response": {"type": "order", "data": {"statuses": list(statuses)}},
    }


def _resting_place_response(oids: Sequence[int]) -> dict[str, object]:
    return _place_response(*({"resting": {"oid": oid}} for oid in oids))


def _cancel_response(*statuses: object) -> dict[str, object]:
    return {
        "status": "ok",
        "response": {"type": "cancel", "data": {"statuses": list(statuses)}},
    }


def test_raw_place_parser_requires_two_resting_integer_oids() -> None:
    response = _place_response({"resting": {"oid": 101}}, {"resting": {"oid": 202}})

    assert parse_resting_oids(response, expected=2, provider="sdk") == (101, 202)


def test_parse_twenty_resting_oids_requires_exact_count() -> None:
    response = _resting_place_response(range(100, 120))

    assert parse_resting_oids(
        response, expected=20, provider="async-hyperliquid"
    ) == tuple(range(100, 120))

    with pytest.raises(BenchmarkFailure, match="non-resting"):
        parse_resting_oids(response, expected=19, provider="async-hyperliquid")


@pytest.mark.parametrize(
    "response",
    [
        _place_response({"filled": {"oid": 101}}, {"resting": {"oid": 202}}),
        _place_response({"error": "rejected"}, {"resting": {"oid": 202}}),
        _place_response({"resting": {"oid": True}}, {"resting": {"oid": 202}}),
        _place_response({"resting": {"oid": 101}}),
    ],
)
def test_raw_place_parser_rejects_incomparable_results(response: object) -> None:
    with pytest.raises(BenchmarkFailure, match="sdk.*non-resting"):
        parse_resting_oids(response, expected=2, provider="sdk")


def test_raw_cancel_parser_requires_exact_success_count() -> None:
    parse_cancel_success(
        _cancel_response("success", "success"), expected=2, provider="sdk"
    )

    with pytest.raises(BenchmarkFailure, match="sdk.*cancel"):
        parse_cancel_success(
            _cancel_response("success", "error"), expected=2, provider="sdk"
        )


def test_ccxt_place_parser_requires_resting_info_and_ids() -> None:
    orders = [
        {"id": "101", "status": None, "info": {"resting": {"oid": 101}}},
        {"id": "202", "status": None, "info": {"resting": {"oid": 202}}},
    ]

    assert parse_ccxt_resting_oids(orders) == (101, 202)

    orders[0] = {"id": "101", "status": "closed", "info": {"filled": {"oid": 101}}}
    with pytest.raises(BenchmarkFailure, match="ccxt.*non-resting"):
        parse_ccxt_resting_oids(orders)


def test_ccxt_cancel_parser_requires_success_info() -> None:
    parse_ccxt_cancel_success(
        [
            {"status": "success", "info": "success"},
            {"status": "success", "info": "success"},
        ],
        expected=2,
    )

    with pytest.raises(BenchmarkFailure, match="ccxt.*cancel"):
        parse_ccxt_cancel_success(
            [{"status": "success", "info": "success"}], expected=2
        )


def test_summary_reports_robust_latency_statistics() -> None:
    assert summarize_ns([10, 20, 30, 40, 100]) == {
        "count": 5,
        "median_ns": 30.0,
        "mad_ns": 10.0,
        "p95_ns": 100.0,
        "min_ns": 10,
        "max_ns": 100,
    }


@pytest.mark.parametrize("samples", [[], [0], [True]])
def test_summary_rejects_invalid_latency_samples(samples: list[int]) -> None:
    with pytest.raises(ValueError, match="positive integer"):
        summarize_ns(samples)


def test_sample_recorder_builds_serializable_grouped_report() -> None:
    recorder = SampleRecorder(
        config=BenchmarkConfig(rounds=2, warmups=0),
        environment={"python": "3.12.13", "network": "testnet"},
        versions={"async-hyperliquid": "1.0.0rc1", "sdk": "0.24.0"},
        git={"revision": "abc123", "dirty": False},
    )
    recorder.record(
        LatencySample(
            suite="providers",
            provider="sdk",
            operation="place_batch_2",
            round_index=0,
            provider_order=1,
            duration_ns=20,
        )
    )
    recorder.record(
        LatencySample(
            suite="providers",
            provider="sdk",
            operation="place_batch_2",
            round_index=1,
            provider_order=0,
            duration_ns=40,
        )
    )

    report = recorder.build_report(
        valid=True,
        failure_reason=None,
        cleanup_ok=True,
        started_at="2026-08-05T00:00:00Z",
        completed_at="2026-08-05T00:01:00Z",
    )

    json.dumps(report)
    assert report["summaries"]["providers"]["place_batch_2"]["sdk"] == {
        "count": 2,
        "median_ns": 30.0,
        "mad_ns": 10.0,
        "p95_ns": 40.0,
        "min_ns": 20,
        "max_ns": 40,
    }


def test_report_sanitizer_rejects_sensitive_keys_and_values() -> None:
    safe = {"valid": True, "failure_reason": None, "samples": []}
    assert_report_is_sanitized(safe, forbidden_values=("super-secret",))

    with pytest.raises(BenchmarkFailure, match="sensitive field"):
        assert_report_is_sanitized(
            {**safe, "signature": "not-a-real-signature"},
            forbidden_values=("super-secret",),
        )
    with pytest.raises(BenchmarkFailure, match="sensitive value"):
        assert_report_is_sanitized(
            {**safe, "reason": "contains SUPER-SECRET material"},
            forbidden_values=("super-secret",),
        )
