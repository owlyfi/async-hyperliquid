from copy import deepcopy
from decimal import Decimal
from time import time
from typing import cast
from collections.abc import Sequence
from uuid import uuid4

import pytest

from async_hyperliquid import AsyncHyperliquid
from async_hyperliquid.constants import OUTCOME_MAX_PRICE, OUTCOME_MIN_PRICE
from async_hyperliquid.types import (
    Cloid,
    Builder,
    JsonObject,
    JsonValue,
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

from .order_checks import _resting_oid

pytestmark = [pytest.mark.exchange, pytest.mark.asyncio(loop_scope="session")]


def _grouped_order_cancels(
    response: PlaceOrderResponse, expected_count: int
) -> list[CancelOrder]:
    assert response["status"] == "ok"
    statuses = response["response"]["data"]["statuses"]
    assert len(statuses) == expected_count
    cancels: list[CancelOrder] = []
    for status in statuses:
        if status in ("waitingForFill", "waitingForTrigger"):
            continue
        status_object = cast(JsonObject, status)
        assert "error" not in status_object
        resting = status_object.get("resting")
        if resting is not None:
            resting_object = cast(JsonObject, resting)
            oid = resting_object["oid"]
            assert isinstance(oid, int)
            cancels.append(CancelOrder("BTC", oid))
    return cancels


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


async def _market_request(
    client: AsyncHyperliquid, coin: str, *, notional: float = 20
) -> PlaceOrderRequest:
    mid = await client.info.mid_price(coin)
    size_decimals = await client.info.size_decimals(coin)
    return {
        "coin": coin,
        "is_buy": True,
        "sz": round(notional / mid, size_decimals),
        "px": 0,
        "is_market": True,
    }


async def _cancel(client: AsyncHyperliquid, orders: Sequence[CancelOrder]) -> None:
    if orders:
        response = await client.cancel_orders(orders)
        assert response["status"] == "ok"


async def _assert_resting_price(
    client: AsyncHyperliquid, coin: str, expected_px: Decimal
) -> None:
    mid = await client.info.mid_price(coin)
    px = float(expected_px)
    is_buy = px < mid
    size_decimals = await client.info.size_decimals(coin)
    size = round(20 / px, size_decimals)
    oid: int | None = None
    try:
        order: PlaceOrderRequest = {
            "coin": coin,
            "is_buy": is_buy,
            "sz": size,
            "px": px,
            "is_market": False,
            "order_type": limit_order_type(TimeInForce.ALO),
        }
        response = await client.place_limit_order(order)
        oid = _resting_oid(response)
        result = await client.info.order_status(client.exchange.execution_address, oid)
        assert result["status"] == "order"
        assert Decimal(result["order"]["order"]["limitPx"]) == expected_px
    finally:
        if oid is not None:
            await _cancel(client, (CancelOrder(coin, oid),))


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


async def test_place_limit_order(sub_hl: AsyncHyperliquid) -> None:
    cancels: list[CancelOrder] = []
    try:
        for coin in await _order_coins(sub_hl):
            response = await sub_hl.place_limit_order(
                await _limit_request(sub_hl, coin)
            )
            cancels.append(CancelOrder(coin, _resting_oid(response)))
    finally:
        await _cancel(sub_hl, cancels)


async def test_outcome_minimum_notional_is_exchange_owned(
    sub_hl: AsyncHyperliquid,
) -> None:
    mids = await sub_hl.info.all_mids()
    coin = next(
        (
            name
            for name, price in mids.items()
            if name.startswith("#") and float(price) != 0.5
        ),
        None,
    )
    if coin is None:
        raise pytest.skip.Exception("testnet allMids has no priced outcome market")
    mid = float(mids[coin])
    is_buy = mid > OUTCOME_MIN_PRICE
    px = OUTCOME_MIN_PRICE if is_buy else OUTCOME_MAX_PRICE
    oid: int | None = None
    try:
        response = await sub_hl.place_limit_order(
            {
                "coin": coin,
                "is_buy": is_buy,
                "sz": 1.0,
                "px": px,
                "is_market": False,
                "order_type": limit_order_type(TimeInForce.ALO),
            }
        )
        assert response["status"] == "ok"
        status = cast(JsonObject, response["response"]["data"]["statuses"][0])
        resting = status.get("resting")
        if isinstance(resting, dict):
            resting_oid = resting.get("oid")
            if isinstance(resting_oid, int):
                oid = resting_oid
        error = status.get("error")
        assert isinstance(error, str)
        assert "minimum value" in error.lower()
    finally:
        if oid is not None:
            await _cancel(sub_hl, (CancelOrder(coin, oid),))


async def test_btc_integer_price_above_10000_is_preserved(
    sub_hl: AsyncHyperliquid,
) -> None:
    expected_px = Decimal("10001")
    mid = await sub_hl.info.mid_price("BTC")
    if not mid * 0.2 <= float(expected_px) <= mid * 1.8:
        raise pytest.skip.Exception(
            "BTC 10001 is outside the Exchange 80% reference-price gate"
        )
    await _assert_resting_price(sub_hl, "BTC", expected_px)


async def test_kpepe_six_decimal_price_is_preserved(sub_hl: AsyncHyperliquid) -> None:
    await _assert_resting_price(sub_hl, "kPEPE", Decimal("0.002001"))


async def test_place_trigger_order(sub_hl: AsyncHyperliquid) -> None:
    coin = "BTC"
    mid = await sub_hl.info.mid_price(coin)
    order = await _limit_request(sub_hl, coin, is_buy=False)
    order["order_type"] = trigger_order_type(
        is_market=False, trigger_px=str(mid * 2), tpsl=TriggerKind.TAKE_PROFIT
    )
    oid: int | None = None
    try:
        response = await sub_hl.place_trigger_order(order)
        oid = _resting_oid(response)
    finally:
        if oid is not None:
            await _cancel(sub_hl, (CancelOrder(coin, oid),))


async def test_place_market_order(sub_hl: AsyncHyperliquid) -> None:
    try:
        response = await sub_hl.place_market_order(await _market_request(sub_hl, "BTC"))
        assert response["status"] == "ok"
    finally:
        await sub_hl.close_position("BTC")


async def test_place_orders_market_batch(sub_hl: AsyncHyperliquid) -> None:
    orders = (await _market_request(sub_hl, "BTC"),)
    try:
        response = await sub_hl.place_orders(orders)
        assert response["status"] == "ok"
    finally:
        await sub_hl.close_positions(("BTC",))


async def test_place_orders(sub_hl: AsyncHyperliquid) -> None:
    orders = (
        await _limit_request(sub_hl, "BTC"),
        await _limit_request(sub_hl, "BTC", is_buy=False),
    )
    cancels: list[CancelOrder] = []
    try:
        response = await sub_hl.place_orders(orders)
        assert response["status"] == "ok"
        for status in response["response"]["data"]["statuses"]:
            resting = cast(JsonObject, cast(JsonObject, status)["resting"])
            oid = resting["oid"]
            assert isinstance(oid, int)
            cancels.append(CancelOrder("BTC", oid))
    finally:
        await _cancel(sub_hl, cancels)


async def test_cancel_order(sub_hl: AsyncHyperliquid) -> None:
    response = await sub_hl.place_limit_order(await _limit_request(sub_hl, "BTC"))
    oid = _resting_oid(response)
    try:
        cancelled = await sub_hl.cancel_order(CancelOrder("BTC", oid))
        assert cancelled["status"] == "ok"
        oid = None
    finally:
        if oid is not None:
            await _cancel(sub_hl, (CancelOrder("BTC", oid),))


async def test_cancel_orders(sub_hl: AsyncHyperliquid) -> None:
    cancels: list[CancelOrder] = []
    try:
        for _ in range(2):
            placed = await sub_hl.place_limit_order(await _limit_request(sub_hl, "BTC"))
            cancels.append(CancelOrder("BTC", _resting_oid(placed)))
        response = await sub_hl.cancel_orders(cancels)
        assert response["status"] == "ok"
        cancels.clear()
    finally:
        await _cancel(sub_hl, cancels)


async def test_cancel_by_cloid(sub_hl: AsyncHyperliquid) -> None:
    cloid = Cloid.from_int(uuid4().int)
    order = await _limit_request(sub_hl, "BTC")
    order["cloid"] = cloid
    oid: int | None = None
    try:
        placed = await sub_hl.place_limit_order(order)
        oid = _resting_oid(placed)
        response = await sub_hl.cancel_by_cloid(CancelByCloid("BTC", cloid))
        assert response["status"] == "ok"
        oid = None
    finally:
        if oid is not None:
            await _cancel(sub_hl, (CancelOrder("BTC", oid),))


async def test_cancel_orders_by_cloid(sub_hl: AsyncHyperliquid) -> None:
    cloids = (Cloid.from_int(uuid4().int), Cloid.from_int(uuid4().int))
    cancels: list[CancelOrder] = []
    try:
        for cloid in cloids:
            order = await _limit_request(sub_hl, "BTC")
            order["cloid"] = cloid
            placed = await sub_hl.place_limit_order(order)
            cancels.append(CancelOrder("BTC", _resting_oid(placed)))
        response = await sub_hl.cancel_orders_by_cloid(
            tuple(CancelByCloid("BTC", cloid) for cloid in cloids)
        )
        assert response["status"] == "ok"
        cancels.clear()
    finally:
        await _cancel(sub_hl, cancels)


async def test_modify_order(sub_hl: AsyncHyperliquid) -> None:
    original_cloid = Cloid.from_int(uuid4().int)
    replacement_cloid = Cloid.from_int(uuid4().int)
    original_order = await _limit_request(sub_hl, "BTC")
    original_order["cloid"] = original_cloid
    original = await sub_hl.place_limit_order(original_order)
    _resting_oid(original)
    modify: ModifyOrderRequest = {
        "oid": original_cloid,
        "coin": original_order["coin"],
        "is_buy": original_order["is_buy"],
        "sz": original_order["sz"],
        "px": original_order["px"] * 0.9,
        "order_type": original_order.get("order_type"),
        "cloid": replacement_cloid,
    }
    try:
        response = await sub_hl.modify_order(modify)
        assert response["status"] == "ok"
    finally:
        canceled = await sub_hl.cancel_orders_by_cloid(
            (
                CancelByCloid("BTC", original_cloid),
                CancelByCloid("BTC", replacement_cloid),
            )
        )
        assert canceled["status"] == "ok"


async def test_modify_orders(sub_hl: AsyncHyperliquid) -> None:
    original_order = await _limit_request(sub_hl, "BTC")
    original = await sub_hl.place_limit_order(original_order)
    oid = _resting_oid(original)
    modify: ModifyOrderRequest = {
        "oid": oid,
        "coin": original_order["coin"],
        "is_buy": original_order["is_buy"],
        "sz": original_order["sz"],
        "px": original_order["px"] * 0.8,
        "order_type": original_order.get("order_type"),
    }
    final_oid = oid
    try:
        response = await sub_hl.modify_orders((modify,))
        final_oid = _resting_oid(response)
    finally:
        await _cancel(sub_hl, (CancelOrder("BTC", final_oid),))


async def test_schedule_cancel(sub_hl: AsyncHyperliquid) -> None:
    try:
        response = await sub_hl.exchange.schedule_cancel(int(time() * 1_000) + 10_000)
        if response["status"] == "err":
            assert response["response"].startswith(
                "Cannot set scheduled cancel time until enough volume traded."
            )
        else:
            assert response["response"]["type"] == "default"
    finally:
        await sub_hl.exchange.schedule_cancel()


async def test_update_leverage(sub_hl: AsyncHyperliquid) -> None:
    for coin in await _order_coins(sub_hl):
        if "/" not in coin and not coin.startswith("@"):
            response = await sub_hl.update_leverage(coin, 1, is_cross=False)
            assert response["status"] == "ok"


async def test_update_isolated_margin(sub_hl: AsyncHyperliquid) -> None:
    try:
        leverage = await sub_hl.update_leverage("ETH", 1, is_cross=False)
        assert leverage["status"] == "ok", leverage
        await sub_hl.place_market_order(await _market_request(sub_hl, "ETH"))
        response = await sub_hl.update_isolated_margin("ETH", 1)
        assert response["status"] == "ok", response
    finally:
        await sub_hl.close_position("ETH")


async def test_place_twap(sub_hl: AsyncHyperliquid) -> None:
    order = await _market_request(sub_hl, "BTC", notional=120)
    twap_id: int | None = None
    try:
        response = await sub_hl.place_twap("BTC", True, order["sz"], 5)
        assert response["status"] == "ok"
        status = cast(JsonObject, response["response"]["data"]["status"])
        running = cast(JsonObject, status["running"])
        value = running["twapId"]
        assert isinstance(value, int)
        twap_id = value
    finally:
        try:
            if twap_id is not None:
                await sub_hl.cancel_twap("BTC", twap_id)
        finally:
            await sub_hl.close_position("BTC")


@pytest.mark.parametrize(
    ("with_trigger", "with_stop"),
    [(True, True), (True, False), (False, True)],
    ids=("trigger-and-stop", "trigger-only", "stop-only"),
)
async def test_place_twap_advanced_prices(
    sub_hl: AsyncHyperliquid,
    monkeypatch: pytest.MonkeyPatch,
    with_trigger: bool,
    with_stop: bool,
) -> None:
    mark_px = await sub_hl.info.mark_price("BTC")
    trigger_value = round(mark_px * 0.95) if with_trigger else None
    stop_value = round(mark_px * 1.05) if with_stop else None
    trigger_px = None if trigger_value is None else float(trigger_value)
    stop_px = None if stop_value is None else float(stop_value)
    captured_actions: list[JsonObject] = []
    original_post_json = sub_hl._transport.post_json

    async def capture_action(url: str, payload: JsonObject) -> JsonValue:
        action = payload.get("action")
        if isinstance(action, dict) and action.get("type") == "twapOrder":
            captured_actions.append(deepcopy(cast(JsonObject, action)))
        return await original_post_json(url, payload)

    monkeypatch.setattr(sub_hl._transport, "post_json", capture_action)
    order = await _market_request(sub_hl, "BTC", notional=120)
    twap_id: int | None = None
    try:
        response = await sub_hl.place_twap(
            "BTC", True, order["sz"], 5, trigger_px=trigger_px, stop_px=stop_px
        )
        assert response["status"] == "ok"
        status = cast(JsonObject, response["response"]["data"]["status"])
        running = cast(JsonObject, status["running"])
        value = running["twapId"]
        assert isinstance(value, int)
        twap_id = value

        assert len(captured_actions) == 1
        details = cast(JsonObject, captured_actions[0]["details"])
        assert details["s"] == (None if stop_value is None else str(stop_value))
        if trigger_value is None:
            assert details["t"] is None
        else:
            assert details["t"] == {"a": False, "p": str(trigger_value)}
    finally:
        try:
            if twap_id is not None:
                await sub_hl.cancel_twap("BTC", twap_id)
        finally:
            await sub_hl.close_position("BTC")


async def test_cancel_twap(sub_hl: AsyncHyperliquid) -> None:
    order = await _market_request(sub_hl, "BTC", notional=120)
    twap_id: int | None = None
    try:
        placed = await sub_hl.place_twap("BTC", True, order["sz"], 5)
        assert placed["status"] == "ok"
        status = cast(JsonObject, placed["response"]["data"]["status"])
        running = cast(JsonObject, status["running"])
        value = running["twapId"]
        assert isinstance(value, int)
        twap_id = value
        response = await sub_hl.cancel_twap("BTC", twap_id)
        assert response["status"] == "ok"
        twap_id = None
    finally:
        try:
            if twap_id is not None:
                await sub_hl.cancel_twap("BTC", twap_id)
        finally:
            await sub_hl.close_position("BTC")


async def test_place_order(sub_hl: AsyncHyperliquid) -> None:
    order = await _limit_request(sub_hl, "BTC")
    oid: int | None = None
    try:
        response = await sub_hl.place_order(
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
            await _cancel(sub_hl, (CancelOrder("BTC", oid),))


async def test_batch_place_orders(sub_hl: AsyncHyperliquid) -> None:
    order = await _limit_request(sub_hl, "BTC")
    oid: int | None = None
    try:
        response = await sub_hl.batch_place_orders((order,))
        oid = _resting_oid(response)
    finally:
        if oid is not None:
            await _cancel(sub_hl, (CancelOrder("BTC", oid),))


async def test_normal_tpsl_accepts_parent_and_trigger_child(
    sub_hl: AsyncHyperliquid,
) -> None:
    mid = await sub_hl.info.mid_price("BTC")
    size_decimals = await sub_hl.info.size_decimals("BTC")
    parent_px = float(f"{mid * 0.8:.5g}")
    stop_trigger_px = float(f"{mid * 0.7:.5g}")
    stop_limit_px = float(f"{stop_trigger_px * 0.9:.5g}")
    size = round(20 / parent_px, size_decimals)
    parent: PlaceOrderRequest = {
        "coin": "BTC",
        "is_buy": True,
        "sz": size,
        "px": parent_px,
        "is_market": False,
        "order_type": limit_order_type(TimeInForce.GTC),
    }
    stop: PlaceOrderRequest = {
        "coin": "BTC",
        "is_buy": False,
        "sz": size,
        "px": stop_limit_px,
        "is_market": False,
        "ro": True,
        "order_type": trigger_order_type(
            is_market=True, trigger_px=str(stop_trigger_px), tpsl=TriggerKind.STOP_LOSS
        ),
    }
    cancels: list[CancelOrder] = []
    try:
        response = await sub_hl.place_orders(
            (parent, stop), grouping=OrderGrouping.NORMAL_TPSL
        )
        cancels = _grouped_order_cancels(response, 2)
    finally:
        await _cancel(sub_hl, cancels)


async def test_normal_tpsl_accepts_parent_take_profit_and_stop_loss(
    sub_hl: AsyncHyperliquid,
) -> None:
    mid = await sub_hl.info.mid_price("BTC")
    size_decimals = await sub_hl.info.size_decimals("BTC")
    parent_px = float(f"{mid * 0.8:.5g}")
    take_trigger_px = float(f"{mid * 1.2:.5g}")
    take_limit_px = float(f"{take_trigger_px * 0.9:.5g}")
    stop_trigger_px = float(f"{mid * 0.7:.5g}")
    stop_limit_px = float(f"{stop_trigger_px * 0.9:.5g}")
    size = round(20 / parent_px, size_decimals)
    parent: PlaceOrderRequest = {
        "coin": "BTC",
        "is_buy": True,
        "sz": size,
        "px": parent_px,
        "is_market": False,
        "order_type": limit_order_type(TimeInForce.GTC),
    }
    take_profit: PlaceOrderRequest = {
        "coin": "BTC",
        "is_buy": False,
        "sz": size,
        "px": take_limit_px,
        "is_market": False,
        "ro": True,
        "order_type": trigger_order_type(
            is_market=True,
            trigger_px=str(take_trigger_px),
            tpsl=TriggerKind.TAKE_PROFIT,
        ),
    }
    stop_loss: PlaceOrderRequest = {
        "coin": "BTC",
        "is_buy": False,
        "sz": size,
        "px": stop_limit_px,
        "is_market": False,
        "ro": True,
        "order_type": trigger_order_type(
            is_market=True, trigger_px=str(stop_trigger_px), tpsl=TriggerKind.STOP_LOSS
        ),
    }
    cancels: list[CancelOrder] = []
    try:
        response = await sub_hl.place_orders(
            (parent, take_profit, stop_loss), grouping=OrderGrouping.NORMAL_TPSL
        )
        cancels = _grouped_order_cancels(response, 3)
    finally:
        await _cancel(sub_hl, cancels)


async def test_place_orders_rejects_spot_and_perp_batch(
    sub_hl: AsyncHyperliquid,
) -> None:
    spot_meta = await sub_hl.info.spot_meta()
    assert spot_meta["universe"]
    spot_coin = spot_meta["universe"][0]["name"]
    perp = await _limit_request(sub_hl, "BTC")
    spot = await _limit_request(sub_hl, spot_coin)

    with pytest.raises(
        ValueError, match="orders cannot mix spot and perpetual markets"
    ):
        await sub_hl.place_orders((perp, spot))


async def test_root_place_orders(sub_hl: AsyncHyperliquid) -> None:
    order = await _limit_request(sub_hl, "BTC")
    oid: int | None = None
    try:
        response = await sub_hl.place_orders((order,))
        oid = _resting_oid(response)
    finally:
        if oid is not None:
            await _cancel(sub_hl, (CancelOrder("BTC", oid),))


async def test_place_order_with_builder(sub_hl: AsyncHyperliquid) -> None:
    order = await _limit_request(sub_hl, "BTC")
    builder = Builder("0x90c52b66db2da13853bbace7c556efb9e5172afd", 0)
    oid: int | None = None
    try:
        response = await sub_hl.place_order(
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
            await _cancel(sub_hl, (CancelOrder("BTC", oid),))


async def test_close_position(sub_hl: AsyncHyperliquid) -> None:
    await sub_hl.place_market_order(await _market_request(sub_hl, "BTC"))
    response = await sub_hl.close_position("BTC")
    assert response is None or response["status"] == "ok"


async def test_close_positions(sub_hl: AsyncHyperliquid) -> None:
    await sub_hl.place_market_order(await _market_request(sub_hl, "BTC"))
    response = await sub_hl.close_positions(("BTC",))
    assert response is None or response["status"] == "ok"


async def test_close_all_positions(sub_hl: AsyncHyperliquid) -> None:
    response = await sub_hl.close_all_positions()
    assert response is None or response["status"] == "ok"
