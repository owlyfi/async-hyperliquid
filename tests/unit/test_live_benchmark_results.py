import json
from collections.abc import Sequence

import pytest

import benchmarks.live.models as live_models
from async_hyperliquid.errors import HttpError, IndeterminateActionError, ProtocolError
from benchmarks.live.models import (
    BenchmarkConfig,
    BenchmarkFailure,
    LatencySample,
    PROVIDER_DIAGNOSTIC_WORKLOAD,
    classify_failure,
)
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


def test_parse_resting_oids_rejects_duplicate_placement_identity() -> None:
    response = _resting_place_response((777, 777))

    with pytest.raises(
        BenchmarkFailure,
        match="^async-hyperliquid produced a non-resting placement result$",
    ) as raised:
        parse_resting_oids(response, expected=2, provider="async-hyperliquid")

    assert "777" not in str(raised.value)


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


def test_ccxt_place_parser_rejects_duplicate_oid_identity_without_value() -> None:
    orders = [
        {"id": "777", "status": None, "info": {"resting": {"oid": 777}}},
        {"id": "777", "status": None, "info": {"resting": {"oid": 777}}},
    ]

    with pytest.raises(
        BenchmarkFailure, match="^ccxt produced a non-resting placement result$"
    ) as raised:
        parse_ccxt_resting_oids(orders)

    assert "777" not in str(raised.value)


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
        workload=PROVIDER_DIAGNOSTIC_WORKLOAD,
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
    assert report["schema_version"] == 2
    assert report["failure_context"] is None
    assert report["config"]["workload"] == "providers-sequential-place2-cancel2-v1"
    assert report["summaries"]["providers"]["place_batch_2"]["sdk"] == {
        "count": 2,
        "median_ns": 30.0,
        "mad_ns": 10.0,
        "p95_ns": 40.0,
        "min_ns": 20,
        "max_ns": 40,
    }


def test_invalid_report_serializes_exact_safe_failure_context() -> None:
    recorder = SampleRecorder(
        config=BenchmarkConfig(rounds=1, warmups=1),
        environment={"network": "testnet"},
        versions={"async-hyperliquid": "1.0.0rc1"},
        git={"revision": "abc123", "dirty": False},
        workload=PROVIDER_DIAGNOSTIC_WORKLOAD,
    )
    context = live_models.FailureContext(
        phase="recovery",
        logical_round=0,
        measured_round=None,
        operation="cancel_by_oid",
        launch_slot=3,
        category="timeout",
        failed_count=2,
        successful_count=18,
        recovery_attempted=True,
        recovery_count=2,
        recovery_ok=True,
    )

    report = recorder.build_report(
        valid=False,
        failure_reason="cancel_id_failed",
        failure_context=context,
        cleanup_ok=True,
        started_at="2026-08-05T00:00:00Z",
        completed_at="2026-08-05T00:01:00Z",
    )

    assert report["failure_context"] == {
        "phase": "recovery",
        "logical_round": 0,
        "measured_round": None,
        "operation": "cancel_by_oid",
        "launch_slot": 3,
        "category": "timeout",
        "failed_count": 2,
        "successful_count": 18,
        "recovery_attempted": True,
        "recovery_count": 2,
        "recovery_ok": True,
    }


@pytest.mark.parametrize(
    "mutation",
    [
        {"launch_slot": 20},
        {"failed_count": True},
        {"recovery_attempted": False, "recovery_count": 1},
        {"recovery_attempted": True, "recovery_ok": None},
    ],
)
def test_failure_context_rejects_values_outside_exact_contract(
    mutation: dict[str, object],
) -> None:
    values: dict[str, object] = {
        "phase": "cancel_id",
        "logical_round": 1,
        "measured_round": 0,
        "operation": "cancel_by_cloid",
        "launch_slot": 1,
        "category": "protocol",
        "failed_count": 1,
        "successful_count": 19,
        "recovery_attempted": True,
        "recovery_count": 1,
        "recovery_ok": True,
    }
    values.update(mutation)

    with pytest.raises(ValueError, match="failure context"):
        live_models.FailureContext(**values)  # type: ignore[attr-defined]


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


_HOSTILE_READS: list[str] = []


class _ExplodingDescriptor:
    def __init__(self, name: str) -> None:
        self.name = name

    def __get__(self, instance: object, owner: type[object]) -> object:
        del instance, owner
        _HOSTILE_READS.append(self.name)
        raise AssertionError(f"classifier executed {self.name}")

    def __set__(self, instance: object, value: object) -> None:
        del instance, value
        _HOSTILE_READS.append(self.name)
        raise AssertionError(f"classifier wrote {self.name}")


class _HostileBenchmarkFailure(BenchmarkFailure):
    __dict__ = _ExplodingDescriptor("__dict__")
    __cause__ = _ExplodingDescriptor("__cause__")
    __context__ = _ExplodingDescriptor("__context__")
    category = _ExplodingDescriptor("category")
    status = _ExplodingDescriptor("status")
    status_code = _ExplodingDescriptor("status_code")


class _HostileExceptionGroup(ExceptionGroup):
    __dict__ = _ExplodingDescriptor("group.__dict__")
    __cause__ = _ExplodingDescriptor("group.__cause__")
    __context__ = _ExplodingDescriptor("group.__context__")
    exceptions = _ExplodingDescriptor("exceptions")


class _HostileInt(int):
    comparisons = 0

    def _explode(self) -> bool:
        type(self).comparisons += 1
        raise AssertionError("integer subclass comparison executed")

    def __eq__(self, other: object) -> bool:
        del other
        return self._explode()

    def __ge__(self, other: object) -> bool:
        del other
        return self._explode()

    def __le__(self, other: object) -> bool:
        del other
        return self._explode()


class _HostileTruth:
    evaluations = 0

    def __bool__(self) -> bool:
        type(self).evaluations += 1
        raise AssertionError("truthiness executed")


def test_failure_classifier_uses_only_bounded_typed_exception_state() -> None:
    status_error = HttpError(429)
    outer = RuntimeError("secret wrapper")
    outer.__cause__ = status_error

    assert classify_failure(outer) == "rate_limited"
    assert classify_failure(TimeoutError("secret timeout")) == "timeout"
    assert classify_failure(ProtocolError("secret response")) == "protocol"
    assert (
        classify_failure(IndeterminateActionError("order", 1_760_000_000_123))
        == "indeterminate_action"
    )
    assert (
        classify_failure(
            BenchmarkFailure("secret rejection", category="unsuccessful_response")
        )
        == "unsuccessful_response"
    )
    assert classify_failure(ExceptionGroup("safe", [TimeoutError()])) == "timeout"


def test_failure_classifier_never_reads_unknown_subclass_descriptors() -> None:
    _HOSTILE_READS.clear()
    hostile = RuntimeError.__new__(_HostileBenchmarkFailure)
    RuntimeError.__init__(hostile, "secret body")
    hostile_group = _HostileExceptionGroup("secret group", [TimeoutError()])

    assert classify_failure(hostile) == "internal"
    assert classify_failure(hostile_group) == "internal"
    assert _HOSTILE_READS == []


def test_integer_subclasses_are_rejected_without_comparison() -> None:
    _HostileInt.comparisons = 0
    status_error = HttpError(None)
    status_error.status = _HostileInt(429)

    assert classify_failure(status_error) == "internal"
    with pytest.raises(ValueError, match="failure context"):
        live_models.FailureContext(
            phase="cancel_id",
            logical_round=_HostileInt(0),
            measured_round=None,
            operation="placement",
            launch_slot=None,
            category="internal",
            failed_count=1,
            successful_count=0,
            recovery_attempted=False,
            recovery_count=0,
            recovery_ok=None,
        )
    with pytest.raises(ValueError, match="failure context"):
        live_models.FailureContext(
            phase="cancel_id",
            logical_round=0,
            measured_round=None,
            operation="placement",
            launch_slot=None,
            category="internal",
            failed_count=1,
            successful_count=0,
            recovery_attempted=False,
            recovery_count=_HostileInt(0),
            recovery_ok=None,
        )
    assert _HostileInt.comparisons == 0


def test_failure_context_rejects_unknown_truth_value_without_execution() -> None:
    _HostileTruth.evaluations = 0

    with pytest.raises(ValueError, match="failure context"):
        live_models.FailureContext(
            phase="cancel_id",
            logical_round=0,
            measured_round=None,
            operation="placement",
            launch_slot=None,
            category="internal",
            failed_count=1,
            successful_count=0,
            recovery_attempted=_HostileTruth(),  # type: ignore[arg-type]
            recovery_count=0,
            recovery_ok=None,
        )
    assert _HostileTruth.evaluations == 0


def test_failure_classifier_is_cycle_safe_for_trusted_links() -> None:
    error = RuntimeError("safe")
    error.__cause__ = error

    assert classify_failure(error) == "internal"


def test_failure_classifier_does_not_guess_rate_limit_after_status_is_lost() -> None:
    error = IndeterminateActionError("cancel", 1_760_000_000_123)

    assert classify_failure(error) == "indeterminate_action"
