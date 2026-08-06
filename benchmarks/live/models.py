from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Final, Literal, TypedDict, cast

from async_hyperliquid.errors import HttpError, IndeterminateActionError, ProtocolError


MIN_INTERVAL_NS = 250_000_000
LIVE_REPORT_SCHEMA_VERSION = 2
WorkloadName = Literal[
    "cancel-id-concurrent-batch20-singles20-10-per-method-v1",
    "providers-sequential-place2-cancel2-v1",
    "combined-cancel-id-concurrent20-providers-sequential2-v1",
]
FailurePhase = Literal[
    "preflight",
    "provider_setup",
    "cancel_id",
    "providers",
    "recovery",
    "client_close",
    "artifact_generation",
]
FailureOperation = Literal[
    "preflight",
    "provider_setup",
    "market_snapshot",
    "wire_parity",
    "placement",
    "cancel_by_oid",
    "cancel_by_cloid",
    "cancel_batch_2_by_oid",
    "recovery",
    "client_close",
    "artifact_generation",
    "internal",
]
FailureCategory = Literal[
    "rate_limited",
    "timeout",
    "protocol",
    "unsuccessful_response",
    "indeterminate_action",
    "placement",
    "recovery",
    "client_close",
    "preflight",
    "internal",
]
_FAILURE_PHASES = frozenset(
    {
        "preflight",
        "provider_setup",
        "cancel_id",
        "providers",
        "recovery",
        "client_close",
        "artifact_generation",
    }
)
_FAILURE_OPERATIONS = frozenset(
    {
        "preflight",
        "provider_setup",
        "market_snapshot",
        "wire_parity",
        "placement",
        "cancel_by_oid",
        "cancel_by_cloid",
        "cancel_batch_2_by_oid",
        "recovery",
        "client_close",
        "artifact_generation",
        "internal",
    }
)
_FAILURE_CATEGORIES = frozenset(
    {
        "rate_limited",
        "timeout",
        "protocol",
        "unsuccessful_response",
        "indeterminate_action",
        "placement",
        "recovery",
        "client_close",
        "preflight",
        "internal",
    }
)
CONCURRENT_CANCEL_WORKLOAD: Final[WorkloadName] = (
    "cancel-id-concurrent-batch20-singles20-10-per-method-v1"
)
PROVIDER_DIAGNOSTIC_WORKLOAD: Final[WorkloadName] = (
    "providers-sequential-place2-cancel2-v1"
)
COMBINED_DIAGNOSTIC_WORKLOAD: Final[WorkloadName] = (
    "combined-cancel-id-concurrent20-providers-sequential2-v1"
)


class BenchmarkFailure(RuntimeError):
    """The live benchmark cannot produce trustworthy comparable results."""

    __slots__ = ("category",)
    category: FailureCategory

    def __init__(self, message: str, *, category: FailureCategory = "internal") -> None:
        self.category = (
            category
            if type(category) is str and category in _FAILURE_CATEGORIES
            else "internal"
        )
        super().__init__(message)


class FailureContextRecord(TypedDict):
    phase: FailurePhase
    logical_round: int | None
    measured_round: int | None
    operation: FailureOperation
    launch_slot: int | None
    category: FailureCategory
    failed_count: int
    successful_count: int
    recovery_attempted: bool
    recovery_count: int
    recovery_ok: bool | None


def _bounded_int(value: object, *, minimum: int, maximum: int | None = None) -> bool:
    return (
        type(value) is int
        and value >= minimum
        and (maximum is None or value <= maximum)
    )


@dataclass(frozen=True, slots=True)
class FailureContext:
    phase: FailurePhase
    logical_round: int | None
    measured_round: int | None
    operation: FailureOperation
    launch_slot: int | None
    category: FailureCategory
    failed_count: int
    successful_count: int
    recovery_attempted: bool
    recovery_count: int
    recovery_ok: bool | None

    def __post_init__(self) -> None:
        valid_rounds = (
            (self.logical_round is None or _bounded_int(self.logical_round, minimum=0))
            and (
                self.measured_round is None
                or _bounded_int(self.measured_round, minimum=0)
            )
            and not (self.logical_round is None and self.measured_round is not None)
        )
        valid_recovery = (
            self.recovery_attempted is True
            and _bounded_int(self.recovery_count, minimum=1, maximum=20)
            and type(self.recovery_ok) is bool
        ) or (
            self.recovery_attempted is False
            and _bounded_int(self.recovery_count, minimum=0, maximum=0)
            and self.recovery_ok is None
        )
        if (
            type(self.phase) is not str
            or self.phase not in _FAILURE_PHASES
            or type(self.operation) is not str
            or self.operation not in _FAILURE_OPERATIONS
            or type(self.category) is not str
            or self.category not in _FAILURE_CATEGORIES
            or not valid_rounds
            or (
                self.launch_slot is not None
                and not _bounded_int(self.launch_slot, minimum=0, maximum=19)
            )
            or not _bounded_int(self.failed_count, minimum=1, maximum=20)
            or not _bounded_int(self.successful_count, minimum=0, maximum=20)
            or type(self.recovery_attempted) is not bool
            or not valid_recovery
        ):
            raise ValueError("failure context is outside the safe contract")

    def as_record(self) -> FailureContextRecord:
        return {
            "phase": self.phase,
            "logical_round": self.logical_round,
            "measured_round": self.measured_round,
            "operation": self.operation,
            "launch_slot": self.launch_slot,
            "category": self.category,
            "failed_count": self.failed_count,
            "successful_count": self.successful_count,
            "recovery_attempted": self.recovery_attempted,
            "recovery_count": self.recovery_count,
            "recovery_ok": self.recovery_ok,
        }


class BenchmarkRunFailure(BenchmarkFailure):
    """A runtime failure with a report-safe, bounded diagnostic context."""

    __slots__ = ("failure_context",)
    failure_context: FailureContext

    def __init__(self, message: str, failure_context: FailureContext) -> None:
        self.failure_context = failure_context
        super().__init__(message, category=failure_context.category)


_BENCHMARK_CATEGORY_SLOT = BenchmarkFailure.__dict__["category"]
_TRUSTED_LINK_TYPES = (
    Exception,
    RuntimeError,
    TimeoutError,
    OSError,
    ConnectionError,
    ValueError,
    TypeError,
    HttpError,
    ProtocolError,
    IndeterminateActionError,
    BenchmarkFailure,
    BenchmarkRunFailure,
    ExceptionGroup,
    BaseExceptionGroup,
)


def _trusted_benchmark_category(error: BaseException) -> FailureCategory:
    value = _BENCHMARK_CATEGORY_SLOT.__get__(error, BenchmarkFailure)
    if type(value) is str and value in _FAILURE_CATEGORIES:
        return cast(FailureCategory, value)
    return "internal"


def classify_failure(error: BaseException) -> FailureCategory:
    """Classify bounded typed exception state without rendering exception text."""
    pending: list[tuple[BaseException, int]] = [(error, 0)]
    seen: set[int] = set()
    categories: set[FailureCategory] = set()
    while pending and len(seen) < 32:
        current, depth = pending.pop(0)
        identity = id(current)
        if identity in seen:
            continue
        seen.add(identity)
        current_type = type(current)
        if current_type is HttpError:
            status = cast(HttpError, current).status
            if type(status) is int and status == 429:
                categories.add("rate_limited")
        if current_type is IndeterminateActionError:
            categories.add("indeterminate_action")
        elif current_type is TimeoutError:
            categories.add("timeout")
        elif current_type is ProtocolError:
            categories.add("protocol")
        elif current_type is BenchmarkFailure or current_type is BenchmarkRunFailure:
            categories.add(_trusted_benchmark_category(current))
        if depth >= 4:
            continue
        if current_type is ExceptionGroup or current_type is BaseExceptionGroup:
            children = cast(BaseExceptionGroup, current).exceptions
            pending.extend((child, depth + 1) for child in children[:20])
        if any(current_type is trusted for trusted in _TRUSTED_LINK_TYPES):
            for linked in (current.__cause__, current.__context__):
                if linked is not None:
                    pending.append((linked, depth + 1))
    for category in (
        "rate_limited",
        "indeterminate_action",
        "timeout",
        "protocol",
        "unsuccessful_response",
        "placement",
        "recovery",
        "client_close",
        "preflight",
        "internal",
    ):
        if category in categories:
            return category
    return "internal"


@dataclass(frozen=True, slots=True)
class BenchmarkConfig:
    rounds: int = 30
    warmups: int = 3
    interval_ns: int = MIN_INTERVAL_NS
    coin: str = "BTC"
    target_notional: float = 11.0
    buy_multiplier: float = 0.90
    sell_multiplier: float = 1.10

    def __post_init__(self) -> None:
        if self.rounds < 1:
            raise ValueError("rounds must be positive")
        if self.warmups < 0:
            raise ValueError("warmups must not be negative")
        if self.interval_ns < MIN_INTERVAL_NS:
            raise ValueError(f"interval_ns must be at least {MIN_INTERVAL_NS}")
        if not math.isfinite(self.target_notional) or self.target_notional <= 0:
            raise ValueError("target_notional must be positive and finite")
        if not math.isfinite(self.buy_multiplier) or not 0 < self.buy_multiplier < 1:
            raise ValueError("buy_multiplier must be between zero and one")
        if not math.isfinite(self.sell_multiplier) or self.sell_multiplier <= 1:
            raise ValueError("sell_multiplier must be greater than one")


@dataclass(frozen=True, slots=True)
class CanonicalOrder:
    is_buy: bool
    price: float
    size: float
    cloid: str
    tif: str = "Alo"
    reduce_only: bool = False


@dataclass(frozen=True, slots=True)
class OrderPair:
    buy: CanonicalOrder
    sell: CanonicalOrder

    def as_tuple(self) -> tuple[CanonicalOrder, CanonicalOrder]:
        return (self.buy, self.sell)


@dataclass(frozen=True, slots=True)
class LatencySample:
    suite: str
    provider: str
    operation: str
    round_index: int
    provider_order: int
    duration_ns: int

    def __post_init__(self) -> None:
        if self.round_index < 0:
            raise ValueError("round_index must not be negative")
        if self.provider_order < 0:
            raise ValueError("provider_order must not be negative")
        if isinstance(self.duration_ns, bool) or self.duration_ns < 1:
            raise ValueError("duration_ns must be a positive integer")


class LatencySummary(TypedDict):
    count: int
    median_ns: float
    mad_ns: float
    p95_ns: float
    min_ns: int
    max_ns: int


class SampleRecord(TypedDict):
    suite: str
    provider: str
    operation: str
    round_index: int
    provider_order: int
    duration_ns: int


class GitMetadata(TypedDict):
    revision: str
    dirty: bool


class BenchmarkReportConfig(TypedDict):
    workload: WorkloadName
    rounds: int
    warmups: int
    interval_ns: int
    coin: str
    target_notional: float
    buy_multiplier: float
    sell_multiplier: float


class LiveBenchmarkReport(TypedDict):
    schema_version: int
    valid: bool
    failure_reason: str | None
    failure_context: FailureContextRecord | None
    cleanup_ok: bool
    started_at: str
    completed_at: str
    config: BenchmarkReportConfig
    environment: dict[str, str]
    versions: dict[str, str]
    git: GitMetadata
    samples: list[SampleRecord]
    summaries: dict[str, dict[str, dict[str, LatencySummary]]]
