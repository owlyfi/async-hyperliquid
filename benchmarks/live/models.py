from __future__ import annotations

import math
from dataclasses import dataclass


MIN_INTERVAL_NS = 250_000_000


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
        if not math.isfinite(self.buy_multiplier) or self.buy_multiplier <= 0:
            raise ValueError("buy_multiplier must be positive and finite")
        if not math.isfinite(self.sell_multiplier) or self.sell_multiplier <= 0:
            raise ValueError("sell_multiplier must be positive and finite")


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
