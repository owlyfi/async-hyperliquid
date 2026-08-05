from __future__ import annotations

import asyncio
from collections.abc import Sequence
from typing import Any, cast

import pytest

from benchmarks.live.models import (
    BenchmarkConfig,
    BenchmarkFailure,
    CanonicalOrder,
    GitMetadata,
    OrderPair,
)
from benchmarks.live import runner as runner_module
from benchmarks.live.results import SampleRecorder
from benchmarks.live.runner import run_cancel_id_suite


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
    def __init__(self) -> None:
        self.calls = 0

    async def snapshot(self) -> tuple[float, int]:
        self.calls += 1
        return (100_000.0, 5)


class ProviderStub:
    name = "async-hyperliquid"

    def __init__(
        self,
        clock: TickClock,
        *,
        fail_place: bool = False,
        fail_cancel_calls: set[int] | None = None,
        gate_probe: Any = None,
    ) -> None:
        self.clock = clock
        self.fail_place = fail_place
        self.fail_cancel_calls = fail_cancel_calls or set()
        self.gate_probe = gate_probe
        self.placement_sizes: list[int] = []
        self.placed_orders: list[tuple[CanonicalOrder, ...]] = []
        self.cancel_calls = 0
        self.completed_calls: set[int] = set()
        self.gate_observations: list[bool] = []
        self.events: list[tuple[str, str]] = []
        self.cancelled_cloids: list[tuple[str, str]] = []

    def wire_orders(self, pair: OrderPair) -> tuple[dict[str, object], ...]:
        return ({"b": pair.buy.is_buy}, {"b": pair.sell.is_buy})

    async def place_many(
        self, orders: Sequence[CanonicalOrder]
    ) -> tuple[int, ...]:
        self.placement_sizes.append(len(orders))
        self.placed_orders.append(tuple(orders))
        self.clock.advance(500)
        if self.fail_place:
            raise TimeoutError("indeterminate placement")
        return tuple(range(100, 100 + len(orders)))

    def _begin_cancel(self, method: str, order: CanonicalOrder) -> int:
        self.cancel_calls += 1
        call_number = self.cancel_calls
        self.gate_observations.append(
            True if self.gate_probe is None else bool(self.gate_probe())
        )
        self.events.append((method, "buy" if order.is_buy else "sell"))
        self.cancelled_cloids.append((method, order.cloid))
        return call_number

    async def cancel_oids(
        self, orders: Sequence[CanonicalOrder], oids: Sequence[int]
    ) -> None:
        assert len(orders) == len(oids) == 1
        order = orders[0]
        call_number = self._begin_cancel("oid", order)
        self.clock.advance(10)
        if call_number in self.fail_cancel_calls:
            raise TimeoutError("indeterminate oid cancel")
        self.completed_calls.add(call_number)

    async def cancel_cloids(self, orders: Sequence[CanonicalOrder]) -> None:
        assert len(orders) == 1
        order = orders[0]
        call_number = self._begin_cancel("cloid", order)
        self.clock.advance(20)
        if call_number in self.fail_cancel_calls:
            raise TimeoutError("indeterminate cloid cancel")
        self.completed_calls.add(call_number)

    async def close(self) -> None:
        return None


class RecoveryStub:
    name = "recovery"

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.cleaned: list[tuple[str, ...]] = []

    async def cancel_cloids(self, orders: Sequence[CanonicalOrder]) -> None:
        self.cleaned.append(tuple(order.cloid for order in orders))
        if self.fail:
            raise RuntimeError("cleanup transport failed")


def _recorder(config: BenchmarkConfig) -> SampleRecorder:
    return SampleRecorder(
        config=config,
        environment={"network": "testnet"},
        versions={"async-hyperliquid": "1.0.0rc1"},
        git=GitMetadata(revision="abc", dirty=False),
    )


def _cloid_factory() -> Any:
    counter = 0

    def create() -> str:
        nonlocal counter
        counter += 1
        return f"0x{counter:032x}"

    return create


class TrackingEvent(asyncio.Event):
    latest: TrackingEvent | None = None

    def __init__(self) -> None:
        super().__init__()
        TrackingEvent.latest = self


async def test_cancel_identifier_launches_balanced_twenty_request_burst(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = BenchmarkConfig(rounds=2, warmups=0)
    clock = TickClock()
    pacer = PacerStub(clock)
    market = MarketSourceStub()
    monkeypatch.setattr(runner_module.asyncio, "Event", TrackingEvent)
    provider = ProviderStub(
        clock,
        gate_probe=lambda: (
            TrackingEvent.latest is not None and TrackingEvent.latest.is_set()
        ),
    )
    recovery = RecoveryStub()
    recorder = _recorder(config)

    await run_cancel_id_suite(
        cast(Any, provider),
        cast(Any, recovery),
        cast(Any, market),
        cast(Any, pacer),
        config,
        recorder,
        clock_ns=clock.now,
        cloid_factory=_cloid_factory(),
    )

    assert provider.placement_sizes == [20, 20]
    assert pacer.weights == [2, 1, 20, 2, 1, 20]
    assert market.calls == 2
    assert recovery.cleaned == []
    assert provider.gate_observations == [True] * 40

    for round_index in range(2):
        round_events = provider.events[round_index * 20 : (round_index + 1) * 20]
        method_by_cloid = {
            cloid: method
            for method, cloid in provider.cancelled_cloids[
                round_index * 20 : (round_index + 1) * 20
            ]
        }
        assert sum(method == "oid" for method, _ in round_events) == 10
        assert sum(method == "cloid" for method, _ in round_events) == 10
        assert round_events[::2] == [
            ("oid" if round_index == 0 else "cloid", side)
            for side in ("buy", "sell") * 5
        ]
        assert round_events[1::2] == [
            ("cloid" if round_index == 0 else "oid", side)
            for side in ("buy", "sell") * 5
        ]
        for method in ("oid", "cloid"):
            method_sides = [
                side for event_method, side in round_events if event_method == method
            ]
            assert method_sides.count("buy") == 5
            assert method_sides.count("sell") == 5
        for pair_index in range(10):
            expected_method = (
                "oid" if (pair_index + round_index) % 2 == 0 else "cloid"
            )
            pair_orders = provider.placed_orders[round_index][
                pair_index * 2 : pair_index * 2 + 2
            ]
            assert {method_by_cloid[order.cloid] for order in pair_orders} == {
                expected_method
            }

    assert len(recorder.samples) == 40
    for round_index in range(2):
        round_samples = recorder.samples[round_index * 20 : (round_index + 1) * 20]
        assert [sample.provider_order for sample in round_samples] == list(range(20))
        assert [sample.operation for sample in round_samples[::2]] == [
            "cancel_by_oid" if round_index == 0 else "cancel_by_cloid"
        ] * 10
        assert [sample.operation for sample in round_samples[1::2]] == [
            "cancel_by_cloid" if round_index == 0 else "cancel_by_oid"
        ] * 10
        assert [sample.duration_ns for sample in round_samples] == [
            10 if sample.operation == "cancel_by_oid" else 20
            for sample in round_samples
        ]

    first_round_orders = provider.placed_orders[0]
    assert [order.is_buy for order in first_round_orders] == [True, False] * 10
    assert [order.price for order in first_round_orders] == [90_000.0, 110_000.0] * 10
    assert all(order.tif == "Alo" for order in first_round_orders)
    assert len({order.cloid for order in first_round_orders}) == 20


async def test_cancel_identifier_omits_live_warmup_samples() -> None:
    config = BenchmarkConfig(rounds=1, warmups=2)
    clock = TickClock()
    provider = ProviderStub(clock)
    recorder = _recorder(config)

    await run_cancel_id_suite(
        cast(Any, provider),
        cast(Any, RecoveryStub()),
        cast(Any, MarketSourceStub()),
        cast(Any, PacerStub(clock)),
        config,
        recorder,
        clock_ns=clock.now,
        cloid_factory=_cloid_factory(),
    )

    assert provider.placement_sizes == [20, 20, 20]
    assert len(provider.events) == 60
    assert [(sample.round_index, sample.operation) for sample in recorder.samples] == [
        (0, "cancel_by_oid" if slot % 2 == 0 else "cancel_by_cloid")
        for slot in range(20)
    ]


async def test_indeterminate_place_cleans_both_cloids_without_retry() -> None:
    config = BenchmarkConfig(rounds=1, warmups=0)
    clock = TickClock()
    provider = ProviderStub(clock, fail_place=True)
    recovery = RecoveryStub()

    with pytest.raises(TimeoutError, match="indeterminate placement"):
        await run_cancel_id_suite(
            cast(Any, provider),
            cast(Any, recovery),
            cast(Any, MarketSourceStub()),
            cast(Any, PacerStub(clock)),
            config,
            _recorder(config),
            clock_ns=clock.now,
            cloid_factory=_cloid_factory(),
        )

    assert provider.placement_sizes == [20]
    assert len(recovery.cleaned) == 1
    assert len(recovery.cleaned[0]) == 20


@pytest.mark.parametrize(
    ("fail_calls", "expected_pending"), [({4}, 1), ({4, 15}, 2)]
)
async def test_concurrent_cancel_waits_for_all_tasks_and_recovers_pending(
    fail_calls: set[int], expected_pending: int
) -> None:
    config = BenchmarkConfig(rounds=1, warmups=0)
    clock = TickClock()
    provider = ProviderStub(clock, fail_cancel_calls=fail_calls)
    recovery = RecoveryStub()
    recorder = _recorder(config)

    with pytest.raises(ExceptionGroup, match="concurrent cancel"):
        await run_cancel_id_suite(
            cast(Any, provider),
            cast(Any, recovery),
            cast(Any, MarketSourceStub()),
            cast(Any, PacerStub(clock)),
            config,
            recorder,
            clock_ns=clock.now,
            cloid_factory=_cloid_factory(),
        )

    assert provider.cancel_calls == 20
    assert provider.completed_calls == set(range(1, 21)) - fail_calls
    assert len(recovery.cleaned[0]) == expected_pending
    assert len(recorder.samples) == 20 - expected_pending


async def test_cleanup_failure_is_terminal_and_value_free() -> None:
    config = BenchmarkConfig(rounds=1, warmups=0)
    clock = TickClock()
    provider = ProviderStub(clock, fail_place=True)

    with pytest.raises(BenchmarkFailure, match="cancel-id cleanup failed") as raised:
        await run_cancel_id_suite(
            cast(Any, provider),
            cast(Any, RecoveryStub(fail=True)),
            cast(Any, MarketSourceStub()),
            cast(Any, PacerStub(clock)),
            config,
            _recorder(config),
            clock_ns=clock.now,
            cloid_factory=_cloid_factory(),
        )

    assert "0x" not in str(raised.value)
    assert "transport" not in str(raised.value)
