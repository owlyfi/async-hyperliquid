from collections.abc import Sequence
from uuid import uuid4

import pytest

from async_hyperliquid import AsyncHyperliquid
from async_hyperliquid.types import (
    CancelByCloid,
    CancelOrder,
    CancelOrderResponse,
    Cloid,
    PlaceOrderRequest,
    TimeInForce,
    TriggerKind,
    limit_order_type,
    trigger_order_type,
)

from .order_checks import _resting_oid

pytestmark = [pytest.mark.exchange, pytest.mark.asyncio(loop_scope="session")]

COIN = "BTC"


async def _resting_limit(
    client: AsyncHyperliquid, *, cloid: Cloid | None = None
) -> PlaceOrderRequest:
    mid = await client.info.mid_price(COIN)
    px = mid * 0.5
    order: PlaceOrderRequest = {
        "coin": COIN,
        "is_buy": True,
        "sz": round(20 / px, await client.info.size_decimals(COIN)),
        "px": px,
        "is_market": False,
        "order_type": limit_order_type(TimeInForce.ALO),
    }
    if cloid is not None:
        order["cloid"] = cloid
    return order


async def _place_limit(client: AsyncHyperliquid, *, cloid: Cloid | None = None) -> int:
    response = await client.place_limit_order(await _resting_limit(client, cloid=cloid))
    return _resting_oid(response)


async def _place_trigger(client: AsyncHyperliquid) -> int:
    mid = await client.info.mid_price(COIN)
    px = mid * 1.5
    order: PlaceOrderRequest = {
        "coin": COIN,
        "is_buy": False,
        "sz": round(20 / px, await client.info.size_decimals(COIN)),
        "px": px,
        "is_market": False,
        "order_type": trigger_order_type(
            is_market=False, trigger_px=str(mid * 2), tpsl=TriggerKind.TAKE_PROFIT
        ),
    }
    return _resting_oid(await client.place_trigger_order(order))


async def _is_open(client: AsyncHyperliquid, oid: int) -> bool:
    status = await client.info.order_status(client.exchange.execution_address, oid)
    return status["status"] == "order" and status["order"]["status"] == "open"


async def _cleanup(client: AsyncHyperliquid, oids: Sequence[int]) -> None:
    # Normal (non-fast) cancel; already-cancelled orders only yield error statuses.
    if oids:
        await client.cancel_orders(tuple(CancelOrder(COIN, oid) for oid in oids))


def _statuses(response: CancelOrderResponse) -> list[object]:
    assert response["status"] == "ok", response
    return list(response["response"]["data"]["statuses"])


async def test_fast_cancel_order(sub_hl: AsyncHyperliquid) -> None:
    oids = [await _place_limit(sub_hl)]
    try:
        response = await sub_hl.cancel_order(CancelOrder(COIN, oids[0]), fast=True)
        assert _statuses(response) == ["success"]
        assert not await _is_open(sub_hl, oids[0])
    finally:
        await _cleanup(sub_hl, oids)


async def test_fast_cancel_orders(sub_hl: AsyncHyperliquid) -> None:
    oids: list[int] = []
    try:
        for _ in range(2):
            oids.append(await _place_limit(sub_hl))
        response = await sub_hl.cancel_orders(
            tuple(CancelOrder(COIN, oid) for oid in oids), fast=True
        )
        assert _statuses(response) == ["success", "success"]
    finally:
        await _cleanup(sub_hl, oids)


async def test_fast_cancel_by_cloid(sub_hl: AsyncHyperliquid) -> None:
    cloid = Cloid.from_int(uuid4().int)
    oids = [await _place_limit(sub_hl, cloid=cloid)]
    try:
        response = await sub_hl.cancel_by_cloid(CancelByCloid(COIN, cloid), fast=True)
        assert _statuses(response) == ["success"]
        assert not await _is_open(sub_hl, oids[0])
    finally:
        await _cleanup(sub_hl, oids)


async def test_fast_cancel_orders_by_cloid(sub_hl: AsyncHyperliquid) -> None:
    cloids = (Cloid.from_int(uuid4().int), Cloid.from_int(uuid4().int))
    oids: list[int] = []
    try:
        for cloid in cloids:
            oids.append(await _place_limit(sub_hl, cloid=cloid))
        response = await sub_hl.cancel_orders_by_cloid(
            tuple(CancelByCloid(COIN, cloid) for cloid in cloids), fast=True
        )
        assert _statuses(response) == ["success", "success"]
    finally:
        await _cleanup(sub_hl, oids)


async def test_fast_cancel_rejects_trigger_order(sub_hl: AsyncHyperliquid) -> None:
    oids = [await _place_trigger(sub_hl)]
    try:
        response = await sub_hl.cancel_order(CancelOrder(COIN, oids[0]), fast=True)
        assert response != {
            "status": "ok",
            "response": {"type": "cancel", "data": {"statuses": ["success"]}},
        }, "fast cancel unexpectedly cancelled a trigger order"
        assert await _is_open(sub_hl, oids[0])
    finally:
        await _cleanup(sub_hl, oids)


async def test_fast_cancel_batch_with_trigger_order(sub_hl: AsyncHyperliquid) -> None:
    # Pins whether the exchange rejects the trigger order per-status or the whole
    # action; the failure output shows the actual shape if this assumption breaks.
    oids: list[int] = []
    try:
        oids.append(await _place_limit(sub_hl))
        oids.append(await _place_trigger(sub_hl))
        response = await sub_hl.cancel_orders(
            tuple(CancelOrder(COIN, oid) for oid in oids), fast=True
        )
        statuses = _statuses(response)
        assert statuses[0] == "success", response
        assert isinstance(statuses[1], dict) and "error" in statuses[1], response
        assert not await _is_open(sub_hl, oids[0])
        assert await _is_open(sub_hl, oids[1])
    finally:
        await _cleanup(sub_hl, oids)
