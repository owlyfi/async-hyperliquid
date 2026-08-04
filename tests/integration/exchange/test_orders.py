from time import time
from typing import cast
from collections.abc import Sequence

import pytest

from async_hyperliquid import AsyncHyperliquid
from async_hyperliquid.types import (
    Cloid,
    Builder,
    JsonObject,
    CancelOrder,
    TimeInForce,
    TriggerKind,
    CancelByCloid,
    OrderGrouping,
    PlaceOrderRequest,
    ModifyOrderRequest,
    PlaceOrderResponse,
    limit_order_type,
    trigger_order_type,
)

pytestmark = [
    pytest.mark.exchange,
    pytest.mark.destructive_exchange,
    pytest.mark.asyncio(loop_scope="session"),
]


def _resting_oid(response: PlaceOrderResponse) -> int:
    assert response["status"] == "ok"
    status = cast(JsonObject, response["response"]["data"]["statuses"][0])
    resting = cast(JsonObject, status["resting"])
    oid = resting["oid"]
    assert isinstance(oid, int)
    return oid


async def _limit_request(
    client: AsyncHyperliquid, coin: str, *, is_buy: bool = True
) -> PlaceOrderRequest:
    mid = await client.info.mid_price(coin)
    px = mid * (0.5 if is_buy else 1.5)
    size_decimals = await client.info.size_decimals(coin)
    sz = round(20 / px, size_decimals)
    return {
        "coin": coin,
        "is_buy": is_buy,
        "sz": sz,
        "px": px,
        "is_market": False,
        "order_type": limit_order_type(TimeInForce.ALO),
    }


async def _market_request(client: AsyncHyperliquid, coin: str) -> PlaceOrderRequest:
    mid = await client.info.mid_price(coin)
    size_decimals = await client.info.size_decimals(coin)
    return {
        "coin": coin,
        "is_buy": True,
        "sz": round(20 / mid, size_decimals),
        "px": 0,
        "is_market": True,
    }


async def _cancel(client: AsyncHyperliquid, orders: Sequence[CancelOrder]) -> None:
    if orders:
        response = await client.cancel_orders(orders)
        assert response["status"] == "ok"


async def _order_coins(client: AsyncHyperliquid) -> tuple[str, ...]:
    coins = ["BTC"]
    spot = await client.info.spot_meta()
    if spot["universe"]:
        coins.append(spot["universe"][0]["name"])
    for dex in await client.info.perp_dex_names():
        if not dex:
            continue
        meta = await client.info.perp_meta(dex)
        if meta["universe"]:
            coins.append(meta["universe"][0]["name"])
            break
    return tuple(coins)


async def test_place_limit_order(api_hl: AsyncHyperliquid) -> None:
    cancels: list[CancelOrder] = []
    try:
        for coin in await _order_coins(api_hl):
            response = await api_hl.place_limit_order(
                await _limit_request(api_hl, coin)
            )
            cancels.append(CancelOrder(coin, _resting_oid(response)))
    finally:
        await _cancel(api_hl, cancels)


async def test_place_trigger_order(api_hl: AsyncHyperliquid) -> None:
    coin = "BTC"
    mid = await api_hl.info.mid_price(coin)
    order = await _limit_request(api_hl, coin, is_buy=False)
    order["order_type"] = trigger_order_type(
        is_market=False, trigger_px=str(mid * 2), tpsl=TriggerKind.TAKE_PROFIT
    )
    oid: int | None = None
    try:
        response = await api_hl.place_trigger_order(order)
        oid = _resting_oid(response)
    finally:
        if oid is not None:
            await _cancel(api_hl, (CancelOrder(coin, oid),))


async def test_place_market_order(api_hl: AsyncHyperliquid) -> None:
    try:
        response = await api_hl.place_market_order(await _market_request(api_hl, "BTC"))
        assert response["status"] == "ok"
    finally:
        await api_hl.close_position("BTC")


async def test_place_orders_market_batch(api_hl: AsyncHyperliquid) -> None:
    orders = (await _market_request(api_hl, "BTC"),)
    try:
        response = await api_hl.place_orders(orders)
        assert response["status"] == "ok"
    finally:
        await api_hl.close_positions(("BTC",))


async def test_place_orders(api_hl: AsyncHyperliquid) -> None:
    orders = (
        await _limit_request(api_hl, "BTC"),
        await _limit_request(api_hl, "BTC", is_buy=False),
    )
    cancels: list[CancelOrder] = []
    try:
        response = await api_hl.place_orders(orders)
        assert response["status"] == "ok"
        for status in response["response"]["data"]["statuses"]:
            resting = cast(JsonObject, cast(JsonObject, status)["resting"])
            oid = resting["oid"]
            assert isinstance(oid, int)
            cancels.append(CancelOrder("BTC", oid))
    finally:
        await _cancel(api_hl, cancels)


async def test_cancel_order(api_hl: AsyncHyperliquid) -> None:
    response = await api_hl.place_limit_order(await _limit_request(api_hl, "BTC"))
    oid = _resting_oid(response)
    try:
        cancelled = await api_hl.cancel_order(CancelOrder("BTC", oid))
        assert cancelled["status"] == "ok"
        oid = None
    finally:
        if oid is not None:
            await _cancel(api_hl, (CancelOrder("BTC", oid),))


async def test_cancel_orders(api_hl: AsyncHyperliquid) -> None:
    cancels: list[CancelOrder] = []
    try:
        for _ in range(2):
            placed = await api_hl.place_limit_order(await _limit_request(api_hl, "BTC"))
            cancels.append(CancelOrder("BTC", _resting_oid(placed)))
        response = await api_hl.cancel_orders(cancels)
        assert response["status"] == "ok"
        cancels.clear()
    finally:
        await _cancel(api_hl, cancels)


async def test_cancel_by_cloid(api_hl: AsyncHyperliquid) -> None:
    cloid = Cloid.from_int(1)
    order = await _limit_request(api_hl, "BTC")
    order["cloid"] = cloid
    oid: int | None = None
    try:
        placed = await api_hl.place_limit_order(order)
        oid = _resting_oid(placed)
        response = await api_hl.cancel_by_cloid(CancelByCloid("BTC", cloid))
        assert response["status"] == "ok"
        oid = None
    finally:
        if oid is not None:
            await _cancel(api_hl, (CancelOrder("BTC", oid),))


async def test_cancel_orders_by_cloid(api_hl: AsyncHyperliquid) -> None:
    cloids = (Cloid.from_int(2), Cloid.from_int(3))
    cancels: list[CancelOrder] = []
    try:
        for cloid in cloids:
            order = await _limit_request(api_hl, "BTC")
            order["cloid"] = cloid
            placed = await api_hl.place_limit_order(order)
            cancels.append(CancelOrder("BTC", _resting_oid(placed)))
        response = await api_hl.cancel_orders_by_cloid(
            tuple(CancelByCloid("BTC", cloid) for cloid in cloids)
        )
        assert response["status"] == "ok"
        cancels.clear()
    finally:
        await _cancel(api_hl, cancels)


async def test_modify_order(api_hl: AsyncHyperliquid) -> None:
    original = await api_hl.place_limit_order(await _limit_request(api_hl, "BTC"))
    oid = _resting_oid(original)
    replacement = await _limit_request(api_hl, "BTC")
    modify: ModifyOrderRequest = {
        "oid": oid,
        "coin": replacement["coin"],
        "is_buy": replacement["is_buy"],
        "sz": replacement["sz"],
        "px": replacement["px"],
        "order_type": replacement.get("order_type"),
    }
    final_oid = oid
    try:
        response = await api_hl.modify_order(modify)
        final_oid = _resting_oid(response)
    finally:
        await _cancel(api_hl, (CancelOrder("BTC", final_oid),))


async def test_modify_orders(api_hl: AsyncHyperliquid) -> None:
    original = await api_hl.place_limit_order(await _limit_request(api_hl, "BTC"))
    oid = _resting_oid(original)
    replacement = await _limit_request(api_hl, "BTC", is_buy=False)
    modify: ModifyOrderRequest = {
        "oid": oid,
        "coin": replacement["coin"],
        "is_buy": replacement["is_buy"],
        "sz": replacement["sz"],
        "px": replacement["px"],
        "order_type": replacement.get("order_type"),
    }
    final_oid = oid
    try:
        response = await api_hl.modify_orders((modify,))
        final_oid = _resting_oid(response)
    finally:
        await _cancel(api_hl, (CancelOrder("BTC", final_oid),))


async def test_schedule_cancel(api_hl: AsyncHyperliquid) -> None:
    try:
        response = await api_hl.exchange.schedule_cancel(int(time() * 1_000) + 10_000)
        assert response["status"] == "ok"
    finally:
        await api_hl.exchange.schedule_cancel()


async def test_update_leverage(api_hl: AsyncHyperliquid) -> None:
    for coin in await _order_coins(api_hl):
        if "/" not in coin and not coin.startswith("@"):
            response = await api_hl.update_leverage(coin, 1, is_cross=False)
            assert response["status"] == "ok"


async def test_update_isolated_margin(api_hl: AsyncHyperliquid) -> None:
    try:
        await api_hl.place_market_order(await _market_request(api_hl, "ETH"))
        response = await api_hl.update_isolated_margin("ETH", 1)
        assert response["status"] == "ok"
    finally:
        await api_hl.close_position("ETH")


async def test_place_twap(api_hl: AsyncHyperliquid) -> None:
    order = await _market_request(api_hl, "BTC")
    twap_id: int | None = None
    try:
        response = await api_hl.place_twap("BTC", True, order["sz"], 5)
        assert response["status"] == "ok"
        status = cast(JsonObject, response["response"]["data"]["status"])
        running = cast(JsonObject, status["running"])
        value = running["twapId"]
        assert isinstance(value, int)
        twap_id = value
    finally:
        if twap_id is not None:
            await api_hl.cancel_twap("BTC", twap_id)


async def test_cancel_twap(api_hl: AsyncHyperliquid) -> None:
    order = await _market_request(api_hl, "BTC")
    twap_id: int | None = None
    try:
        placed = await api_hl.place_twap("BTC", True, order["sz"], 5)
        assert placed["status"] == "ok"
        status = cast(JsonObject, placed["response"]["data"]["status"])
        running = cast(JsonObject, status["running"])
        value = running["twapId"]
        assert isinstance(value, int)
        twap_id = value
        response = await api_hl.cancel_twap("BTC", twap_id)
        assert response["status"] == "ok"
        twap_id = None
    finally:
        if twap_id is not None:
            await api_hl.cancel_twap("BTC", twap_id)


async def test_place_order(api_hl: AsyncHyperliquid) -> None:
    order = await _limit_request(api_hl, "BTC")
    oid: int | None = None
    try:
        response = await api_hl.place_order(
            order["coin"],
            order["is_buy"],
            order["sz"],
            order["px"],
            False,
            order_type=order["order_type"],
        )
        oid = _resting_oid(response)
    finally:
        if oid is not None:
            await _cancel(api_hl, (CancelOrder("BTC", oid),))


async def test_batch_place_orders(api_hl: AsyncHyperliquid) -> None:
    order = await _limit_request(api_hl, "BTC")
    oid: int | None = None
    try:
        response = await api_hl.batch_place_orders(
            (order,), grouping=OrderGrouping.NORMAL_TPSL
        )
        oid = _resting_oid(response)
    finally:
        if oid is not None:
            await _cancel(api_hl, (CancelOrder("BTC", oid),))


async def test_root_place_orders(api_hl: AsyncHyperliquid) -> None:
    order = await _limit_request(api_hl, "BTC")
    oid: int | None = None
    try:
        response = await api_hl.place_orders((order,))
        oid = _resting_oid(response)
    finally:
        if oid is not None:
            await _cancel(api_hl, (CancelOrder("BTC", oid),))


async def test_place_order_with_builder(api_hl: AsyncHyperliquid) -> None:
    order = await _limit_request(api_hl, "BTC")
    builder = Builder("0x90c52b66db2da13853bbace7c556efb9e5172afd", 0)
    oid: int | None = None
    try:
        response = await api_hl.place_order(
            order["coin"],
            order["is_buy"],
            order["sz"],
            order["px"],
            False,
            order_type=order["order_type"],
            builder=builder,
        )
        oid = _resting_oid(response)
    finally:
        if oid is not None:
            await _cancel(api_hl, (CancelOrder("BTC", oid),))


async def test_close_position(api_hl: AsyncHyperliquid) -> None:
    await api_hl.place_market_order(await _market_request(api_hl, "BTC"))
    response = await api_hl.close_position("BTC")
    assert response is None or response["status"] == "ok"


async def test_close_positions(api_hl: AsyncHyperliquid) -> None:
    await api_hl.place_market_order(await _market_request(api_hl, "BTC"))
    response = await api_hl.close_positions(("BTC",))
    assert response is None or response["status"] == "ok"


async def test_close_all_positions(api_hl: AsyncHyperliquid) -> None:
    response = await api_hl.close_all_positions()
    assert response is None or response["status"] == "ok"
