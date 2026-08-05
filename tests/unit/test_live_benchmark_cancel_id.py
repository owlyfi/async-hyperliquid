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
        fail_cancel_call: int | None = None,
    ) -> None:
        self.clock = clock
        self.fail_place = fail_place
        self.fail_cancel_call = fail_cancel_call
        self.place_calls = 0
        self.cancel_calls = 0
        self.events: list[tuple[str, str]] = []

    def wire_orders(self, pair: OrderPair) -> tuple[dict[str, object], ...]:
        return ({"b": pair.buy.is_buy}, {"b": pair.sell.is_buy})

    async def place(self, pair: OrderPair) -> tuple[int, int]:
        self.place_calls += 1
        self.clock.advance(500)
        if self.fail_place:
            raise TimeoutError("indeterminate placement")
        return (101, 202)

    async def cancel_oids(
        self, orders: Sequence[CanonicalOrder], oids: Sequence[int]
    ) -> None:
        assert len(orders) == len(oids) == 1
        self.cancel_calls += 1
        order = orders[0]
        self.events.append(("oid", "buy" if order.is_buy else "sell"))
        self.clock.advance(10)
        if self.cancel_calls == self.fail_cancel_call:
            raise TimeoutError("indeterminate oid cancel")

    async def cancel_cloids(self, orders: Sequence[CanonicalOrder]) -> None:
        assert len(orders) == 1
        self.cancel_calls += 1
        order = orders[0]
        self.events.append(("cloid", "buy" if order.is_buy else "sell"))
        self.clock.advance(20)
        if self.cancel_calls == self.fail_cancel_call:
            raise TimeoutError("indeterminate cloid cancel")

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


async def test_cancel_identifier_balances_method_side_and_order() -> None:
    config = BenchmarkConfig(rounds=4, warmups=0)
    clock = TickClock()
    pacer = PacerStub(clock)
    market = MarketSourceStub()
    provider = ProviderStub(clock)
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

    assert provider.events == [
        ("oid", "buy"),
        ("cloid", "sell"),
        ("cloid", "buy"),
        ("oid", "sell"),
        ("oid", "buy"),
        ("cloid", "sell"),
        ("cloid", "buy"),
        ("oid", "sell"),
    ]
    assert [sample.operation for sample in recorder.samples] == [
        "cancel_by_oid",
        "cancel_by_cloid",
        "cancel_by_cloid",
        "cancel_by_oid",
        "cancel_by_oid",
        "cancel_by_cloid",
        "cancel_by_cloid",
        "cancel_by_oid",
    ]
    assert [sample.duration_ns for sample in recorder.samples] == [
        10,
        20,
        20,
        10,
        10,
        20,
        20,
        10,
    ]
    assert pacer.weights == [2, 1, 1, 1] * 4
    assert market.calls == 4
    assert recovery.cleaned == []


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

    assert provider.place_calls == 3
    assert len(provider.events) == 6
    assert [(sample.round_index, sample.operation) for sample in recorder.samples] == [
        (0, "cancel_by_oid"),
        (0, "cancel_by_cloid"),
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

    assert provider.place_calls == 1
    assert len(recovery.cleaned) == 1
    assert len(recovery.cleaned[0]) == 2


@pytest.mark.parametrize(
    ("fail_call", "expected_pending", "recorded_samples"), [(1, 2, 0), (2, 1, 1)]
)
async def test_failed_cancel_cleans_only_still_pending_cloids(
    fail_call: int, expected_pending: int, recorded_samples: int
) -> None:
    config = BenchmarkConfig(rounds=1, warmups=0)
    clock = TickClock()
    provider = ProviderStub(clock, fail_cancel_call=fail_call)
    recovery = RecoveryStub()
    recorder = _recorder(config)

    with pytest.raises(TimeoutError, match="indeterminate"):
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

    assert provider.cancel_calls == fail_call
    assert len(recovery.cleaned[0]) == expected_pending
    assert len(recorder.samples) == recorded_samples


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
