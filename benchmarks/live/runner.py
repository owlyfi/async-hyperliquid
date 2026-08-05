from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from time import perf_counter_ns
from typing import Literal
from uuid import uuid4

from .models import BenchmarkConfig, BenchmarkFailure, CanonicalOrder, LatencySample
from .pacing import WeightedPacer
from .providers import (
    ConcurrentCancelProvider,
    LiveProvider,
    MarketSource,
    validate_provider_wire_parity,
)
from .results import SampleRecorder
from .workload import build_order_pair, rotate_names


def _new_cloid() -> str:
    return f"0x{uuid4().int:032x}"


@dataclass(frozen=True, slots=True)
class _CancelRequest:
    operation: Literal["cancel_by_oid", "cancel_by_cloid"]
    order: CanonicalOrder
    oid: int


async def _cancel_one(
    provider: ConcurrentCancelProvider,
    gate: asyncio.Event,
    request: _CancelRequest,
    clock_ns: Callable[[], int],
) -> int:
    await gate.wait()
    started = clock_ns()
    if request.operation == "cancel_by_oid":
        await provider.cancel_oids((request.order,), (request.oid,))
    else:
        await provider.cancel_cloids((request.order,))
    return clock_ns() - started


async def _recover_pending(
    pending: dict[str, CanonicalOrder], recovery: LiveProvider, pacer: WeightedPacer
) -> Exception | None:
    if not pending:
        return None
    try:
        await pacer.wait(weight=1)
        await recovery.cancel_cloids(tuple(pending.values()))
    except Exception as error:
        return error
    pending.clear()
    return None


async def run_cancel_id_suite(
    provider: ConcurrentCancelProvider,
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
        pairs = tuple(
            build_order_pair(
                mid,
                size_decimals,
                target_notional=config.target_notional,
                cloids=(cloid_factory(), cloid_factory()),
                buy_multiplier=config.buy_multiplier,
                sell_multiplier=config.sell_multiplier,
            )
            for _ in range(10)
        )
        orders = tuple(order for pair in pairs for order in pair.as_tuple())
        pending = {order.cloid: order for order in orders}
        failure: BaseException | None = None

        try:
            await pacer.wait(weight=1)
            oids = await provider.place_many(orders)

            by_method: dict[
                Literal["cancel_by_oid", "cancel_by_cloid"], list[_CancelRequest]
            ] = {"cancel_by_oid": [], "cancel_by_cloid": []}
            for pair_index, pair in enumerate(pairs):
                operation: Literal["cancel_by_oid", "cancel_by_cloid"] = (
                    "cancel_by_oid"
                    if (pair_index + logical_round) % 2 == 0
                    else "cancel_by_cloid"
                )
                by_method[operation].extend(
                    (
                        _CancelRequest(operation, pair.buy, oids[pair_index * 2]),
                        _CancelRequest(operation, pair.sell, oids[pair_index * 2 + 1]),
                    )
                )

            first_operation: Literal["cancel_by_oid", "cancel_by_cloid"] = (
                "cancel_by_oid" if logical_round % 2 == 0 else "cancel_by_cloid"
            )
            second_operation: Literal["cancel_by_oid", "cancel_by_cloid"] = (
                "cancel_by_cloid" if logical_round % 2 == 0 else "cancel_by_oid"
            )
            requests = tuple(
                request
                for pair in zip(
                    by_method[first_operation], by_method[second_operation], strict=True
                )
                for request in pair
            )

            measured = logical_round >= config.warmups
            measured_round = logical_round - config.warmups
            await pacer.wait(weight=20)
            gate = asyncio.Event()
            tasks = tuple(
                asyncio.create_task(_cancel_one(provider, gate, request, clock_ns))
                for request in requests
            )
            try:
                await asyncio.sleep(0)
                gate.set()
                results = await asyncio.gather(*tasks, return_exceptions=True)
            except BaseException:
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                raise

            cancel_failures: list[BaseException] = []
            samples: list[LatencySample] = []
            for provider_order, (request, result) in enumerate(
                zip(requests, results, strict=True)
            ):
                if isinstance(result, BaseException):
                    cancel_failures.append(result)
                    continue
                pending.pop(request.order.cloid)
                if measured:
                    samples.append(
                        LatencySample(
                            suite="cancel-id",
                            provider=provider.name,
                            operation=request.operation,
                            round_index=measured_round,
                            provider_order=provider_order,
                            duration_ns=result,
                        )
                    )
            if cancel_failures:
                failure = BaseExceptionGroup(
                    "cancel-id concurrent cancel failed", cancel_failures
                )
            for sample in samples:
                recorder.record(sample)
        except BaseException as error:
            if failure is None:
                failure = error
            else:
                failure = BaseExceptionGroup(
                    "cancel-id multiple operation failures", [failure, error]
                )

        cleanup_failure = await _recover_pending(pending, recovery, pacer)
        if cleanup_failure is not None:
            if failure is not None and not isinstance(failure, Exception):
                raise failure from cleanup_failure
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


async def run_provider_suite(
    providers: Sequence[LiveProvider],
    recovery: LiveProvider,
    mid_source: MarketSource,
    pacer: WeightedPacer,
    config: BenchmarkConfig,
    recorder: SampleRecorder,
    *,
    clock_ns: Callable[[], int] = perf_counter_ns,
    cloid_factory: Callable[[], str] = _new_cloid,
) -> None:
    if not providers:
        raise ValueError("providers must not be empty")
    providers_by_name = {provider.name: provider for provider in providers}
    if len(providers_by_name) != len(providers):
        raise ValueError("provider names must be unique")
    provider_names = tuple(providers_by_name)

    total_rounds = config.warmups + config.rounds
    for logical_round in range(total_rounds):
        await pacer.wait(weight=2)
        mid, size_decimals = await mid_source.snapshot()
        parity_pair = build_order_pair(
            mid,
            size_decimals,
            target_notional=config.target_notional,
            cloids=(cloid_factory(), cloid_factory()),
            buy_multiplier=config.buy_multiplier,
            sell_multiplier=config.sell_multiplier,
        )
        validate_provider_wire_parity(tuple(providers), parity_pair)

        measured = logical_round >= config.warmups
        measured_round = logical_round - config.warmups
        ordered_names = rotate_names(provider_names, logical_round)
        for provider_order, provider_name in enumerate(ordered_names):
            provider = providers_by_name[provider_name]
            pair = build_order_pair(
                mid,
                size_decimals,
                target_notional=config.target_notional,
                cloids=(cloid_factory(), cloid_factory()),
                buy_multiplier=config.buy_multiplier,
                sell_multiplier=config.sell_multiplier,
            )
            pending = {order.cloid: order for order in pair.as_tuple()}
            failure: BaseException | None = None

            try:
                await pacer.wait(weight=1)
                place_started = clock_ns() if measured else 0
                oids = await provider.place(pair)
                if measured:
                    recorder.record(
                        LatencySample(
                            suite="providers",
                            provider=provider.name,
                            operation="place_batch_2",
                            round_index=measured_round,
                            provider_order=provider_order,
                            duration_ns=clock_ns() - place_started,
                        )
                    )

                await pacer.wait(weight=1)
                cancel_started = clock_ns() if measured else 0
                await provider.cancel_oids(pair.as_tuple(), oids)
                pending.clear()
                if measured:
                    recorder.record(
                        LatencySample(
                            suite="providers",
                            provider=provider.name,
                            operation="cancel_batch_2_by_oid",
                            round_index=measured_round,
                            provider_order=provider_order,
                            duration_ns=clock_ns() - cancel_started,
                        )
                    )
            except BaseException as error:
                failure = error

            cleanup_failure = await _recover_pending(pending, recovery, pacer)
            if cleanup_failure is not None:
                if failure is None:
                    cause: BaseException = cleanup_failure
                else:
                    cause = BaseExceptionGroup(
                        "provider operation and cleanup both failed",
                        [failure, cleanup_failure],
                    )
                raise BenchmarkFailure("providers cleanup failed") from cause
            if failure is not None:
                raise failure
