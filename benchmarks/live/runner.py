from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from time import perf_counter_ns
from typing import Literal
from uuid import uuid4

from .models import (
    BenchmarkConfig,
    BenchmarkFailure,
    BenchmarkRunFailure,
    CanonicalOrder,
    FailureContext,
    FailureOperation,
    LatencySample,
    classify_failure,
)
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
        measured = logical_round >= config.warmups
        measured_round = logical_round - config.warmups if measured else None
        try:
            await pacer.wait(weight=2)
            mid, size_decimals = await mid_source.snapshot()
        except BaseException as error:
            if not isinstance(error, Exception):
                raise
            raise BenchmarkRunFailure(
                "cancel-id benchmark failed",
                FailureContext(
                    phase="cancel_id",
                    logical_round=logical_round,
                    measured_round=measured_round,
                    operation="market_snapshot",
                    launch_slot=None,
                    category=classify_failure(error),
                    failed_count=1,
                    successful_count=0,
                    recovery_attempted=False,
                    recovery_count=0,
                    recovery_ok=None,
                ),
            ) from error
        try:
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
            if len(pending) != len(orders):
                raise BenchmarkFailure("cancel-id generated non-unique CLOIDs")
        except BaseException as error:
            if not isinstance(error, Exception):
                raise
            raise BenchmarkRunFailure(
                "cancel-id benchmark failed",
                FailureContext(
                    phase="cancel_id",
                    logical_round=logical_round,
                    measured_round=measured_round,
                    operation="placement",
                    launch_slot=None,
                    category=classify_failure(error),
                    failed_count=1,
                    successful_count=0,
                    recovery_attempted=False,
                    recovery_count=0,
                    recovery_ok=None,
                ),
            ) from error
        failure: BaseException | None = None
        failure_operation: FailureOperation = "placement"
        failure_slot: int | None = None
        failed_count = 1
        successful_count = 0

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
            failure_operation = "internal"

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

            cancel_failures: list[tuple[int, _CancelRequest, BaseException]] = []
            samples: list[LatencySample] = []
            for provider_order, (request, result) in enumerate(
                zip(requests, results, strict=True)
            ):
                if isinstance(result, BaseException):
                    cancel_failures.append((provider_order, request, result))
                    continue
                pending.pop(request.order.cloid)
                if measured:
                    samples.append(
                        LatencySample(
                            suite="cancel-id",
                            provider=provider.name,
                            operation=request.operation,
                            round_index=logical_round - config.warmups,
                            provider_order=provider_order,
                            duration_ns=result,
                        )
                    )
            if cancel_failures:
                first_slot, first_request, _ = cancel_failures[0]
                failure_operation = first_request.operation
                failure_slot = first_slot
                failed_count = len(cancel_failures)
                successful_count = len(requests) - failed_count
                failure = BaseExceptionGroup(
                    "cancel-id concurrent cancel failed",
                    [error for _, _, error in cancel_failures],
                )
            for sample in samples:
                recorder.record(sample)
        except BaseException as error:
            if failure is None:
                failure = error
                successful_count = len(orders) - len(pending)
            else:
                failure = BaseExceptionGroup(
                    "cancel-id multiple operation failures", [failure, error]
                )

        recovery_count = len(pending)
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
            raise BenchmarkRunFailure(
                "cancel-id cleanup failed",
                FailureContext(
                    phase="recovery",
                    logical_round=logical_round,
                    measured_round=measured_round,
                    operation=failure_operation,
                    launch_slot=failure_slot,
                    category="recovery",
                    failed_count=failed_count,
                    successful_count=successful_count,
                    recovery_attempted=True,
                    recovery_count=recovery_count,
                    recovery_ok=False,
                ),
            ) from cause
        if failure is not None:
            if not isinstance(failure, Exception):
                raise failure
            raise BenchmarkRunFailure(
                "cancel-id benchmark failed",
                FailureContext(
                    phase="cancel_id",
                    logical_round=logical_round,
                    measured_round=measured_round,
                    operation=failure_operation,
                    launch_slot=failure_slot,
                    category=classify_failure(failure),
                    failed_count=failed_count,
                    successful_count=successful_count,
                    recovery_attempted=recovery_count > 0,
                    recovery_count=recovery_count,
                    recovery_ok=True if recovery_count > 0 else None,
                ),
            ) from failure


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
        measured = logical_round >= config.warmups
        measured_round = logical_round - config.warmups if measured else None
        try:
            await pacer.wait(weight=2)
            mid, size_decimals = await mid_source.snapshot()
        except BaseException as error:
            if not isinstance(error, Exception):
                raise
            raise BenchmarkRunFailure(
                "providers benchmark failed",
                FailureContext(
                    phase="providers",
                    logical_round=logical_round,
                    measured_round=measured_round,
                    operation="market_snapshot",
                    launch_slot=None,
                    category=classify_failure(error),
                    failed_count=1,
                    successful_count=0,
                    recovery_attempted=False,
                    recovery_count=0,
                    recovery_ok=None,
                ),
            ) from error
        try:
            parity_pair = build_order_pair(
                mid,
                size_decimals,
                target_notional=config.target_notional,
                cloids=(cloid_factory(), cloid_factory()),
                buy_multiplier=config.buy_multiplier,
                sell_multiplier=config.sell_multiplier,
            )
            validate_provider_wire_parity(tuple(providers), parity_pair)
        except BaseException as error:
            if not isinstance(error, Exception):
                raise
            raise BenchmarkRunFailure(
                "providers benchmark failed",
                FailureContext(
                    phase="providers",
                    logical_round=logical_round,
                    measured_round=measured_round,
                    operation="wire_parity",
                    launch_slot=None,
                    category=classify_failure(error),
                    failed_count=1,
                    successful_count=0,
                    recovery_attempted=False,
                    recovery_count=0,
                    recovery_ok=None,
                ),
            ) from error
        ordered_names = rotate_names(provider_names, logical_round)
        for provider_order, provider_name in enumerate(ordered_names):
            provider = providers_by_name[provider_name]
            try:
                pair = build_order_pair(
                    mid,
                    size_decimals,
                    target_notional=config.target_notional,
                    cloids=(cloid_factory(), cloid_factory()),
                    buy_multiplier=config.buy_multiplier,
                    sell_multiplier=config.sell_multiplier,
                )
            except BaseException as error:
                if not isinstance(error, Exception):
                    raise
                raise BenchmarkRunFailure(
                    "providers benchmark failed",
                    FailureContext(
                        phase="providers",
                        logical_round=logical_round,
                        measured_round=measured_round,
                        operation="placement",
                        launch_slot=None,
                        category=classify_failure(error),
                        failed_count=1,
                        successful_count=0,
                        recovery_attempted=False,
                        recovery_count=0,
                        recovery_ok=None,
                    ),
                ) from error
            pending = {order.cloid: order for order in pair.as_tuple()}
            failure: BaseException | None = None
            failure_operation: FailureOperation = "placement"
            successful_count = 0

            try:
                await pacer.wait(weight=1)
                place_started = clock_ns() if measured else 0
                oids = await provider.place(pair)
                if measured:
                    failure_operation = "internal"
                    recorder.record(
                        LatencySample(
                            suite="providers",
                            provider=provider.name,
                            operation="place_batch_2",
                            round_index=logical_round - config.warmups,
                            provider_order=provider_order,
                            duration_ns=clock_ns() - place_started,
                        )
                    )

                failure_operation = "cancel_batch_2_by_oid"
                await pacer.wait(weight=1)
                cancel_started = clock_ns() if measured else 0
                await provider.cancel_oids(pair.as_tuple(), oids)
                pending.clear()
                successful_count = 1
                if measured:
                    failure_operation = "internal"
                    recorder.record(
                        LatencySample(
                            suite="providers",
                            provider=provider.name,
                            operation="cancel_batch_2_by_oid",
                            round_index=logical_round - config.warmups,
                            provider_order=provider_order,
                            duration_ns=clock_ns() - cancel_started,
                        )
                    )
            except BaseException as error:
                failure = error

            recovery_count = len(pending)
            cleanup_failure = await _recover_pending(pending, recovery, pacer)
            if cleanup_failure is not None:
                if failure is not None and not isinstance(failure, Exception):
                    raise failure from cleanup_failure
                if failure is None:
                    cause: BaseException = cleanup_failure
                else:
                    cause = BaseExceptionGroup(
                        "provider operation and cleanup both failed",
                        [failure, cleanup_failure],
                    )
                raise BenchmarkRunFailure(
                    "providers cleanup failed",
                    FailureContext(
                        phase="recovery",
                        logical_round=logical_round,
                        measured_round=measured_round,
                        operation=failure_operation,
                        launch_slot=None,
                        category="recovery",
                        failed_count=1,
                        successful_count=successful_count,
                        recovery_attempted=True,
                        recovery_count=recovery_count,
                        recovery_ok=False,
                    ),
                ) from cause
            if failure is not None:
                if not isinstance(failure, Exception):
                    raise failure
                raise BenchmarkRunFailure(
                    "providers benchmark failed",
                    FailureContext(
                        phase="providers",
                        logical_round=logical_round,
                        measured_round=measured_round,
                        operation=failure_operation,
                        launch_slot=None,
                        category=classify_failure(failure),
                        failed_count=1,
                        successful_count=successful_count,
                        recovery_attempted=recovery_count > 0,
                        recovery_count=recovery_count,
                        recovery_ok=True if recovery_count > 0 else None,
                    ),
                ) from failure
