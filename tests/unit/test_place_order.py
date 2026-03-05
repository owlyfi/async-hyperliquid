from unittest.mock import AsyncMock
from typing import Any, cast

import pytest

from async_hyperliquid import AsyncHyperliquid
from async_hyperliquid.utils.types import (
    LimitOrder,
    LimitTif,
    TriggerTpsl,
    limit_order_type,
    trigger_order_type,
)


def build_stub_hl() -> Any:
    # Bypass __init__ for focused unit tests and allow dynamic mock patching.
    return cast(Any, object.__new__(AsyncHyperliquid))


@pytest.mark.asyncio
async def test_place_market_order_uses_ioc_order_type() -> None:
    hl = build_stub_hl()
    get_mid_price = AsyncMock(return_value=100.0)
    round_sz_px = AsyncMock(return_value=(1, 0.1, 105.0))
    place_orders = AsyncMock(return_value={"status": "ok"})
    setattr(hl, "get_mid_price", get_mid_price)
    setattr(hl, "_round_sz_px", round_sz_px)
    setattr(hl, "place_orders", place_orders)

    resp = await hl.place_market_order("BTC", True, 0.1, slippage=0.05)

    assert resp == {"status": "ok"}
    round_sz_px.assert_awaited_once_with("BTC", 0.1, 105.0)
    place_orders.assert_awaited_once()
    await_args = place_orders.await_args
    assert await_args is not None
    order_req = await_args.args[0][0]
    assert order_req["order_type"] == limit_order_type(LimitTif.IOC)


@pytest.mark.asyncio
async def test_place_typed_order_defaults_to_ioc() -> None:
    hl = build_stub_hl()
    round_sz_px = AsyncMock(return_value=(1, 0.2, 99.5))
    place_orders = AsyncMock(return_value={"status": "ok"})
    setattr(hl, "_round_sz_px", round_sz_px)
    setattr(hl, "place_orders", place_orders)

    resp = await hl.place_typed_order("ETH", False, 0.2, 99.5)

    assert resp == {"status": "ok"}
    await_args = place_orders.await_args
    assert await_args is not None
    order_req = await_args.args[0][0]
    assert order_req["order_type"] == limit_order_type(LimitTif.IOC)


@pytest.mark.asyncio
async def test_place_order_routes_to_market_order() -> None:
    hl = build_stub_hl()
    place_market_order = AsyncMock(return_value={"status": "ok"})
    setattr(hl, "place_market_order", place_market_order)

    resp = await hl.place_order(
        coin="BTC",
        is_buy=True,
        sz=0.1,
        px=1.0,
        is_market=True,
        order_type=LimitOrder.ALO.value,
        slippage=0.02,
    )

    assert resp == {"status": "ok"}
    place_market_order.assert_awaited_once_with(
        coin="BTC",
        is_buy=True,
        sz=0.1,
        ro=False,
        cloid=None,
        slippage=0.02,
        builder=None,
    )


@pytest.mark.asyncio
async def test_place_order_routes_to_typed_order() -> None:
    hl = build_stub_hl()
    place_typed_order = AsyncMock(return_value={"status": "ok"})
    setattr(hl, "place_typed_order", place_typed_order)

    order_type = limit_order_type(LimitTif.GTC)
    resp = await hl.place_order(
        coin="BTC",
        is_buy=False,
        sz=0.3,
        px=88.8,
        is_market=False,
        order_type=order_type,
    )

    assert resp == {"status": "ok"}
    place_typed_order.assert_awaited_once_with(
        coin="BTC",
        is_buy=False,
        sz=0.3,
        px=88.8,
        ro=False,
        order_type=order_type,
        cloid=None,
        builder=None,
    )


def test_trigger_order_type_builder() -> None:
    order_type = trigger_order_type(
        is_market=False, trigger_px=12345.6, tpsl=TriggerTpsl.TP
    )
    assert order_type == {
        "trigger": {"isMarket": False, "triggerPx": "12345.6", "tpsl": "tp"}
    }


@pytest.mark.asyncio
async def test_place_typed_order_accepts_trigger_order_type() -> None:
    hl = build_stub_hl()
    round_sz_px = AsyncMock(return_value=(1, 0.2, 99.5))
    place_orders = AsyncMock(return_value={"status": "ok"})
    setattr(hl, "_round_sz_px", round_sz_px)
    setattr(hl, "place_orders", place_orders)

    trigger = trigger_order_type(
        is_market=False, trigger_px=88_000.0, tpsl=TriggerTpsl.SL
    )
    resp = await hl.place_typed_order(
        "BTC", False, 0.2, 99.5, order_type=trigger
    )

    assert resp == {"status": "ok"}
    await_args = place_orders.await_args
    assert await_args is not None
    order_req = await_args.args[0][0]
    assert order_req["order_type"] == trigger
