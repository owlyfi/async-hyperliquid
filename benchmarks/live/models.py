from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Final, Literal, TypedDict


MIN_INTERVAL_NS = 250_000_000
LIVE_REPORT_SCHEMA_VERSION = 2
WorkloadName = Literal[
    "cancel-id-concurrent-batch20-singles20-10-per-method-v1",
    "providers-sequential-place2-cancel2-v1",
    "combined-cancel-id-concurrent20-providers-sequential2-v1",
]
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
    cleanup_ok: bool
    started_at: str
    completed_at: str
    config: BenchmarkReportConfig
    environment: dict[str, str]
    versions: dict[str, str]
    git: GitMetadata
    samples: list[SampleRecord]
    summaries: dict[str, dict[str, dict[str, LatencySummary]]]
