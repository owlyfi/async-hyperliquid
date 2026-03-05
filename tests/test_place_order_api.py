from unittest.mock import AsyncMock

import pytest

from async_hyperliquid import AsyncHyperliquid
from async_hyperliquid.utils.types import LimitOrder, LimitTif, limit_order_type


def build_stub_hl() -> AsyncHyperliquid:
    return object.__new__(AsyncHyperliquid)


@pytest.mark.asyncio
async def test_place_market_order_uses_ioc_order_type() -> None:
    hl = build_stub_hl()
    hl.get_mid_price = AsyncMock(return_value=100.0)
    hl._round_sz_px = AsyncMock(return_value=(1, 0.1, 105.0))
    hl.place_orders = AsyncMock(return_value={"status": "ok"})

    resp = await hl.place_market_order("BTC", True, 0.1, slippage=0.05)

    assert resp == {"status": "ok"}
    hl._round_sz_px.assert_awaited_once_with("BTC", 0.1, 105.0)
    hl.place_orders.assert_awaited_once()
    order_req = hl.place_orders.await_args.args[0][0]
    assert order_req["order_type"] == limit_order_type(LimitTif.IOC)


@pytest.mark.asyncio
async def test_place_typed_order_defaults_to_ioc() -> None:
    hl = build_stub_hl()
    hl._round_sz_px = AsyncMock(return_value=(1, 0.2, 99.5))
    hl.place_orders = AsyncMock(return_value={"status": "ok"})

    resp = await hl.place_typed_order("ETH", False, 0.2, 99.5)

    assert resp == {"status": "ok"}
    order_req = hl.place_orders.await_args.args[0][0]
    assert order_req["order_type"] == limit_order_type(LimitTif.IOC)


@pytest.mark.asyncio
async def test_place_order_routes_to_market_order() -> None:
    hl = build_stub_hl()
    hl.place_market_order = AsyncMock(return_value={"status": "ok"})

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
    hl.place_market_order.assert_awaited_once_with(
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
    hl.place_typed_order = AsyncMock(return_value={"status": "ok"})

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
    hl.place_typed_order.assert_awaited_once_with(
        coin="BTC",
        is_buy=False,
        sz=0.3,
        px=88.8,
        ro=False,
        order_type=order_type,
        cloid=None,
        builder=None,
    )
