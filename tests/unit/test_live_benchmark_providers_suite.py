import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any, cast

import pytest

from benchmarks.live.models import (
    BenchmarkConfig,
    CanonicalOrder,
    GitMetadata,
    LiveBenchmarkReport,
    OrderPair,
)
from benchmarks.live.results import SampleRecorder, write_report
from benchmarks.live.runner import run_provider_suite


class TickClock:
    def __init__(self) -> None:
        self.value = 0

    def now(self) -> int:
        return self.value

    def advance(self, nanoseconds: int) -> None:
        self.value += nanoseconds


class PacerStub:
    def __init__(self, clock: TickClock) -> None:
        self.clock = clock
        self.weights: list[int] = []

    async def wait(self, weight: int = 1) -> None:
        self.weights.append(weight)
        self.clock.advance(1_000)


class MarketSourceStub:
    async def snapshot(self) -> tuple[float, int]:
        return (100_000.0, 5)


class ProviderStub:
    def __init__(
        self,
        name: str,
        clock: TickClock,
        events: list[tuple[str, str, OrderPair]],
        *,
        fail_cancel: bool = False,
    ) -> None:
        self.name = name
        self.clock = clock
        self.events = events
        self.fail_cancel = fail_cancel

    def wire_orders(self, pair: OrderPair) -> tuple[dict[str, object], ...]:
        return cast(
            tuple[dict[str, object], ...],
            tuple(
                {
                    "a": 0,
                    "b": order.is_buy,
                    "p": str(order.price),
                    "s": str(order.size),
                    "r": False,
                    "t": {"limit": {"tif": "Alo"}},
                    "c": order.cloid,
                }
                for order in pair.as_tuple()
            ),
        )

    async def place(self, pair: OrderPair) -> tuple[int, int]:
        self.events.append(("place", self.name, pair))
        self.clock.advance(10)
        return (101, 202)

    async def cancel_oids(
        self, orders: Sequence[CanonicalOrder], oids: Sequence[int]
    ) -> None:
        assert len(orders) == len(oids) == 2
        pair = OrderPair(buy=orders[0], sell=orders[1])
        self.events.append(("cancel", self.name, pair))
        self.clock.advance(20)
        if self.fail_cancel:
            raise TimeoutError("provider cancel timed out")

    async def cancel_cloids(self, orders: Sequence[CanonicalOrder]) -> None:
        raise AssertionError("measured providers must cancel by oid")

    async def close(self) -> None:
        return None


class RecoveryStub:
    name = "recovery"

    def __init__(self) -> None:
        self.cleaned: list[tuple[str, ...]] = []

    async def cancel_cloids(self, orders: Sequence[CanonicalOrder]) -> None:
        self.cleaned.append(tuple(order.cloid for order in orders))


def _recorder(config: BenchmarkConfig) -> SampleRecorder:
    return SampleRecorder(
        config=config,
        environment={"network": "testnet"},
        versions={"async-hyperliquid": "1.0.0rc1", "sdk": "0.24.0", "ccxt": "4.5.71"},
        git=GitMetadata(revision="abc", dirty=False),
    )


def _cloid_factory() -> Any:
    counter = 0

    def create() -> str:
        nonlocal counter
        counter += 1
        return f"0x{counter:032x}"

    return create


async def test_provider_suite_rotates_order_and_uses_unique_live_cloids() -> None:
    config = BenchmarkConfig(rounds=3, warmups=0)
    clock = TickClock()
    events: list[tuple[str, str, OrderPair]] = []
    providers = tuple(
        ProviderStub(name, clock, events)
        for name in ("ccxt", "sdk", "async-hyperliquid")
    )
    pacer = PacerStub(clock)
    recorder = _recorder(config)

    await run_provider_suite(
        cast(Any, providers),
        cast(Any, RecoveryStub()),
        cast(Any, MarketSourceStub()),
        cast(Any, pacer),
        config,
        recorder,
        clock_ns=clock.now,
        cloid_factory=_cloid_factory(),
    )

    assert [name for operation, name, _ in events if operation == "place"] == [
        "ccxt",
        "sdk",
        "async-hyperliquid",
        "sdk",
        "async-hyperliquid",
        "ccxt",
        "async-hyperliquid",
        "ccxt",
        "sdk",
    ]
    placed_pairs = [pair for operation, _, pair in events if operation == "place"]
    assert (
        len({order.cloid for pair in placed_pairs for order in pair.as_tuple()}) == 18
    )
    for offset in range(0, len(placed_pairs), 3):
        round_pairs = placed_pairs[offset : offset + 3]
        assert {(pair.buy.price, pair.sell.price) for pair in round_pairs} == {
            (90_000.0, 110_000.0)
        }
        assert {(pair.buy.size, pair.sell.size) for pair in round_pairs} == {
            (0.00013, 0.0001)
        }
    assert [sample.duration_ns for sample in recorder.samples] == [10, 20] * 9
    assert pacer.weights == [2, 1, 1, 1, 1, 1, 1] * 3


async def test_provider_cancel_failure_cleans_both_cloids_without_retry() -> None:
    config = BenchmarkConfig(rounds=1, warmups=0)
    clock = TickClock()
    events: list[tuple[str, str, OrderPair]] = []
    failing = ProviderStub("ccxt", clock, events, fail_cancel=True)
    recovery = RecoveryStub()

    with pytest.raises(TimeoutError, match="provider cancel timed out"):
        await run_provider_suite(
            cast(Any, (failing,)),
            cast(Any, recovery),
            cast(Any, MarketSourceStub()),
            cast(Any, PacerStub(clock)),
            config,
            _recorder(config),
            clock_ns=clock.now,
            cloid_factory=_cloid_factory(),
        )

    assert [operation for operation, _, _ in events] == ["place", "cancel"]
    assert len(recovery.cleaned) == 1
    assert len(recovery.cleaned[0]) == 2


def _invalid_report() -> LiveBenchmarkReport:
    config = BenchmarkConfig(rounds=1, warmups=0)
    return _recorder(config).build_report(
        valid=False,
        failure_reason="ccxt rate limited",
        cleanup_ok=True,
        started_at="2026-08-05T00:00:00Z",
        completed_at="2026-08-05T00:00:01Z",
    )


def test_invalid_report_is_written_atomically_without_comparison_files(
    tmp_path: Path,
) -> None:
    path = write_report(_invalid_report(), tmp_path, forbidden_values=("secret",))

    assert path.name == "report.invalid.json"
    assert sorted(item.name for item in tmp_path.iterdir()) == ["report.invalid.json"]
    assert json.loads(path.read_text())["failure_reason"] == "ccxt rate limited"


def test_valid_report_uses_canonical_filename(tmp_path: Path) -> None:
    report = dict(_invalid_report())
    report["valid"] = True
    report["failure_reason"] = None

    path = write_report(
        cast(LiveBenchmarkReport, report), tmp_path, forbidden_values=()
    )

    assert path.name == "report.json"
