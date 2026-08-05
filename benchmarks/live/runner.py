from __future__ import annotations

from collections.abc import Callable
from time import perf_counter_ns
from uuid import uuid4

from .models import BenchmarkConfig, BenchmarkFailure, CanonicalOrder, LatencySample
from .pacing import WeightedPacer
from .providers import LiveProvider, MarketSource
from .results import SampleRecorder
from .workload import build_order_pair


def _new_cloid() -> str:
    return f"0x{uuid4().int:032x}"


async def _recover_pending(
    pending: dict[str, CanonicalOrder], recovery: LiveProvider, pacer: WeightedPacer
) -> BaseException | None:
    if not pending:
        return None
    try:
        await pacer.wait(weight=1)
        await recovery.cancel_cloids(tuple(pending.values()))
    except BaseException as error:
        return error
    pending.clear()
    return None


async def run_cancel_id_suite(
    provider: LiveProvider,
    recovery: LiveProvider,
    mid_source: MarketSource,
    pacer: WeightedPacer,
    config: BenchmarkConfig,
    recorder: SampleRecorder,
    *,
    clock_ns: Callable[[], int] = perf_counter_ns,
    cloid_factory: Callable[[], str] = _new_cloid,
) -> None:
    total_rounds = config.warmups + config.rounds
    for logical_round in range(total_rounds):
        await pacer.wait(weight=2)
        mid, size_decimals = await mid_source.snapshot()
        pair = build_order_pair(
            mid,
            size_decimals,
            target_notional=config.target_notional,
            cloids=(cloid_factory(), cloid_factory()),
        )
        pending = {order.cloid: order for order in pair.as_tuple()}
        failure: BaseException | None = None

        try:
            await pacer.wait(weight=1)
            buy_oid, sell_oid = await provider.place(pair)
            if logical_round % 2 == 0:
                steps = (
                    ("cancel_by_oid", pair.buy, buy_oid),
                    ("cancel_by_cloid", pair.sell, sell_oid),
                )
            else:
                steps = (
                    ("cancel_by_cloid", pair.buy, buy_oid),
                    ("cancel_by_oid", pair.sell, sell_oid),
                )

            measured = logical_round >= config.warmups
            measured_round = logical_round - config.warmups
            for provider_order, (operation, order, oid) in enumerate(steps):
                await pacer.wait(weight=1)
                started = clock_ns() if measured else 0
                if operation == "cancel_by_oid":
                    await provider.cancel_oids((order,), (oid,))
                else:
                    await provider.cancel_cloids((order,))
                if measured:
                    recorder.record(
                        LatencySample(
                            suite="cancel-id",
                            provider=provider.name,
                            operation=operation,
                            round_index=measured_round,
                            provider_order=provider_order,
                            duration_ns=clock_ns() - started,
                        )
                    )
                pending.pop(order.cloid)
        except BaseException as error:
            failure = error

        cleanup_failure = await _recover_pending(pending, recovery, pacer)
        if cleanup_failure is not None:
            if failure is None:
                cause: BaseException = cleanup_failure
            else:
                cause = BaseExceptionGroup(
                    "cancel-id operation and cleanup both failed",
                    [failure, cleanup_failure],
                )
            raise BenchmarkFailure("cancel-id cleanup failed") from cause
        if failure is not None:
            raise failure
