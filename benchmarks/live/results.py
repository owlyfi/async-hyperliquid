from __future__ import annotations

import json
import math
import statistics
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import cast

from .models import (
    BenchmarkConfig,
    BenchmarkFailure,
    FailureContext,
    GitMetadata,
    LIVE_REPORT_SCHEMA_VERSION,
    LatencySample,
    LatencySummary,
    LiveBenchmarkReport,
    SampleRecord,
    WorkloadName,
)


_SENSITIVE_FIELDS = frozenset(
    {
        "address",
        "wallet_address",
        "private_key",
        "signing_key",
        "signature",
        "nonce",
        "oid",
        "cloid",
        "raw_request",
        "raw_response",
    }
)


def _mapping(value: object) -> Mapping[str, object] | None:
    if not isinstance(value, Mapping):
        return None
    return cast(Mapping[str, object], value)


def _statuses(response: object, *, provider: str, operation: str) -> list[object]:
    root = _mapping(response)
    if root is None or root.get("status") != "ok":
        raise BenchmarkFailure(
            f"{provider} produced an invalid {operation} response", category="protocol"
        )
    inner = _mapping(root.get("response"))
    if inner is None:
        raise BenchmarkFailure(
            f"{provider} produced an invalid {operation} response", category="protocol"
        )
    data = _mapping(inner.get("data"))
    if data is None:
        raise BenchmarkFailure(
            f"{provider} produced an invalid {operation} response", category="protocol"
        )
    statuses = data.get("statuses")
    if not isinstance(statuses, list):
        raise BenchmarkFailure(
            f"{provider} produced an invalid {operation} response", category="protocol"
        )
    return cast(list[object], statuses)


def _positive_oid(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, str) and value.isdecimal():
        parsed = int(value)
        return parsed if parsed > 0 else None
    return None


def parse_resting_oids(
    response: object, *, expected: int, provider: str
) -> tuple[int, ...]:
    if expected < 1:
        raise ValueError("expected must be positive")
    statuses = _statuses(response, provider=provider, operation="placement")
    oids: list[int] = []
    if len(statuses) == expected:
        for status in statuses:
            status_mapping = _mapping(status)
            resting = (
                _mapping(status_mapping.get("resting"))
                if status_mapping is not None
                else None
            )
            oid = _positive_oid(resting.get("oid")) if resting is not None else None
            if oid is None:
                break
            oids.append(oid)
    if len(oids) != expected or len(set(oids)) != expected:
        raise BenchmarkFailure(
            f"{provider} produced a non-resting placement result", category="placement"
        )
    return tuple(oids)


def parse_cancel_success(response: object, *, expected: int, provider: str) -> None:
    if expected < 1:
        raise ValueError("expected must be positive")
    statuses = _statuses(response, provider=provider, operation="cancel")
    if len(statuses) != expected or any(status != "success" for status in statuses):
        raise BenchmarkFailure(
            f"{provider} produced an unsuccessful cancel result",
            category="unsuccessful_response",
        )


def parse_ccxt_resting_oids(orders: object) -> tuple[int, int]:
    oids: list[int] = []
    if isinstance(orders, list) and len(orders) == 2:
        for order in orders:
            order_mapping = _mapping(order)
            if order_mapping is None:
                break
            info = _mapping(order_mapping.get("info"))
            if info is None:
                break
            resting = _mapping(info.get("resting"))
            if resting is None:
                break
            oid = _positive_oid(resting.get("oid"))
            parsed_id = _positive_oid(order_mapping.get("id"))
            if oid is None or parsed_id != oid:
                break
            oids.append(oid)
    if len(oids) != 2 or len(set(oids)) != 2:
        raise BenchmarkFailure(
            "ccxt produced a non-resting placement result", category="placement"
        )
    return (oids[0], oids[1])


def parse_ccxt_cancel_success(orders: object, *, expected: int) -> None:
    if expected < 1:
        raise ValueError("expected must be positive")
    if not isinstance(orders, list) or len(orders) != expected:
        raise BenchmarkFailure(
            "ccxt produced an unsuccessful cancel result",
            category="unsuccessful_response",
        )
    for order in orders:
        order_mapping = _mapping(order)
        if (
            order_mapping is None
            or order_mapping.get("info") != "success"
            or order_mapping.get("status") != "success"
        ):
            raise BenchmarkFailure(
                "ccxt produced an unsuccessful cancel result",
                category="unsuccessful_response",
            )


def summarize_ns(samples: Sequence[int]) -> LatencySummary:
    if not samples or any(
        isinstance(sample, bool) or not isinstance(sample, int) or sample < 1
        for sample in samples
    ):
        raise ValueError("samples must contain positive integer latencies")
    ordered = sorted(samples)
    median = float(statistics.median(ordered))
    deviations = [abs(sample - median) for sample in ordered]
    p95_index = max(0, math.ceil(0.95 * len(ordered)) - 1)
    return {
        "count": len(ordered),
        "median_ns": median,
        "mad_ns": float(statistics.median(deviations)),
        "p95_ns": float(ordered[p95_index]),
        "min_ns": ordered[0],
        "max_ns": ordered[-1],
    }


def _sample_record(sample: LatencySample) -> SampleRecord:
    return {
        "suite": sample.suite,
        "provider": sample.provider,
        "operation": sample.operation,
        "round_index": sample.round_index,
        "provider_order": sample.provider_order,
        "duration_ns": sample.duration_ns,
    }


class SampleRecorder:
    __slots__ = (
        "_config",
        "_environment",
        "_git",
        "_samples",
        "_versions",
        "_workload",
    )

    def __init__(
        self,
        *,
        config: BenchmarkConfig,
        environment: Mapping[str, str],
        versions: Mapping[str, str],
        git: GitMetadata,
        workload: WorkloadName,
    ) -> None:
        self._config = config
        self._environment = dict(environment)
        self._versions = dict(versions)
        self._git = GitMetadata(revision=git["revision"], dirty=git["dirty"])
        self._workload = workload
        self._samples: list[LatencySample] = []

    @property
    def samples(self) -> tuple[LatencySample, ...]:
        return tuple(self._samples)

    def record(self, sample: LatencySample) -> None:
        self._samples.append(sample)

    def build_report(
        self,
        *,
        valid: bool,
        failure_reason: str | None,
        cleanup_ok: bool,
        started_at: str,
        completed_at: str,
        failure_context: FailureContext | None = None,
    ) -> LiveBenchmarkReport:
        if valid == (failure_context is not None):
            raise ValueError("validity and failure context do not agree")
        grouped: dict[str, dict[str, dict[str, list[int]]]] = {}
        for sample in self._samples:
            grouped.setdefault(sample.suite, {}).setdefault(
                sample.operation, {}
            ).setdefault(sample.provider, []).append(sample.duration_ns)
        summaries = {
            suite: {
                operation: {
                    provider: summarize_ns(values)
                    for provider, values in sorted(providers.items())
                }
                for operation, providers in sorted(operations.items())
            }
            for suite, operations in sorted(grouped.items())
        }
        config = self._config
        report: LiveBenchmarkReport = {
            "schema_version": LIVE_REPORT_SCHEMA_VERSION,
            "valid": valid,
            "failure_reason": failure_reason,
            "failure_context": (
                None if failure_context is None else failure_context.as_record()
            ),
            "cleanup_ok": cleanup_ok,
            "started_at": started_at,
            "completed_at": completed_at,
            "config": {
                "workload": self._workload,
                "rounds": config.rounds,
                "warmups": config.warmups,
                "interval_ns": config.interval_ns,
                "coin": config.coin,
                "target_notional": config.target_notional,
                "buy_multiplier": config.buy_multiplier,
                "sell_multiplier": config.sell_multiplier,
            },
            "environment": dict(self._environment),
            "versions": dict(self._versions),
            "git": GitMetadata(
                revision=self._git["revision"], dirty=self._git["dirty"]
            ),
            "samples": [_sample_record(sample) for sample in self._samples],
            "summaries": summaries,
        }
        return report


def _check_sensitive_keys(value: object) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if not isinstance(key, str):
                raise BenchmarkFailure("report contains a non-string field name")
            if key.casefold() in _SENSITIVE_FIELDS:
                raise BenchmarkFailure("report contains a sensitive field")
            _check_sensitive_keys(child)
    elif isinstance(value, list | tuple):
        for child in value:
            _check_sensitive_keys(child)


def assert_report_is_sanitized(
    report: Mapping[str, object], *, forbidden_values: Sequence[str]
) -> None:
    _check_sensitive_keys(report)
    try:
        rendered = json.dumps(report, sort_keys=True).casefold()
    except (TypeError, ValueError) as error:
        raise BenchmarkFailure("report is not JSON serializable") from error
    for value in forbidden_values:
        if value and value.casefold() in rendered:
            raise BenchmarkFailure("report contains a sensitive value")


def write_report(
    report: LiveBenchmarkReport, output_dir: Path, *, forbidden_values: Sequence[str]
) -> Path:
    assert_report_is_sanitized(
        cast(Mapping[str, object], report), forbidden_values=forbidden_values
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    filename = "report.json" if report["valid"] else "report.invalid.json"
    destination = output_dir / filename
    temporary = output_dir / f".{filename}.tmp"
    rendered = json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n"
    try:
        temporary.write_text(rendered)
        temporary.replace(destination)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return destination
