from collections.abc import Awaitable, Callable

import pytest

from benchmarks.live.models import BenchmarkConfig
from benchmarks.live.pacing import WeightedPacer
from benchmarks.live.workload import build_order_pair, rotate_names


class FakeClock:
    def __init__(self) -> None:
        self.now_ns = 0
        self.sleeps: list[float] = []

    def now(self) -> int:
        return self.now_ns

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now_ns += round(seconds * 1_000_000_000)


def _clock_functions(
    clock: FakeClock,
) -> tuple[Callable[[], int], Callable[[float], Awaitable[None]]]:
    return clock.now, clock.sleep


async def test_weighted_pacer_reserves_250_ms_per_weight() -> None:
    clock = FakeClock()
    clock_ns, sleep = _clock_functions(clock)
    pacer = WeightedPacer(interval_ns=250_000_000, clock_ns=clock_ns, sleep=sleep)

    await pacer.wait(weight=2)
    await pacer.wait(weight=1)

    assert clock.sleeps == [0.5]


async def test_weighted_pacer_does_not_sleep_after_a_slow_request() -> None:
    clock = FakeClock()
    pacer = WeightedPacer(
        interval_ns=250_000_000, clock_ns=clock.now, sleep=clock.sleep
    )

    await pacer.wait()
    clock.now_ns = 400_000_000
    await pacer.wait()

    assert clock.sleeps == []


@pytest.mark.parametrize("weight", [True, 0, -1])
async def test_weighted_pacer_rejects_invalid_weight(weight: int) -> None:
    clock = FakeClock()
    pacer = WeightedPacer(
        interval_ns=250_000_000, clock_ns=clock.now, sleep=clock.sleep
    )

    with pytest.raises(ValueError, match="weight must be a positive integer"):
        await pacer.wait(weight=weight)


def test_order_pair_uses_balanced_alo_prices_and_minimum_notional() -> None:
    pair = build_order_pair(
        100_000.0, 5, target_notional=11.0, cloids=("0x" + "01" * 16, "0x" + "02" * 16)
    )

    assert (pair.buy.price, pair.sell.price) == (90_000.0, 110_000.0)
    assert (pair.buy.size, pair.sell.size) == (0.00013, 0.0001)
    assert pair.buy.size * pair.buy.price >= 10.0
    assert pair.sell.size * pair.sell.price >= 10.0
    assert pair.buy.tif == pair.sell.tif == "Alo"
    assert pair.buy.is_buy is True
    assert pair.sell.is_buy is False


def test_order_pair_applies_hyperliquid_price_precision() -> None:
    pair = build_order_pair(
        93_456.78, 5, target_notional=11.0, cloids=("0x" + "03" * 16, "0x" + "04" * 16)
    )

    assert pair.buy.price == 84_111.0
    assert pair.sell.price == 102_800.0


@pytest.mark.parametrize(
    ("factory", "message"),
    [
        (lambda: BenchmarkConfig(rounds=0), "rounds must be positive"),
        (lambda: BenchmarkConfig(warmups=-1), "warmups must not be negative"),
        (
            lambda: BenchmarkConfig(interval_ns=249_999_999),
            "interval_ns must be at least",
        ),
        (
            lambda: BenchmarkConfig(target_notional=0.0),
            "target_notional must be positive",
        ),
    ],
)
def test_benchmark_config_rejects_unsafe_values(
    factory: Callable[[], BenchmarkConfig], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        factory()


def test_provider_names_rotate_by_round() -> None:
    names = ("ccxt", "sdk", "async-hyperliquid")

    assert [rotate_names(names, index) for index in range(4)] == [
        ("ccxt", "sdk", "async-hyperliquid"),
        ("sdk", "async-hyperliquid", "ccxt"),
        ("async-hyperliquid", "ccxt", "sdk"),
        ("ccxt", "sdk", "async-hyperliquid"),
    ]
