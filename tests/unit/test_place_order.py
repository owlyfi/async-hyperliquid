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
    resp = await hl.place_typed_order("BTC", False, 0.2, 99.5, order_type=trigger)

    assert resp == {"status": "ok"}
    await_args = place_orders.await_args
    assert await_args is not None
    order_req = await_args.args[0][0]
    assert order_req["order_type"] == trigger


@pytest.mark.asyncio
async def test_batch_place_orders_builds_limit_orders_in_input_order() -> None:
    hl = build_stub_hl()

    async def fake_round_sz_px(
        coin: str, sz: float, px: float
    ) -> tuple[int, float, float]:
        mapping = {"BTC": (10, 0.1, 101.0), "ETH": (11, 0.2, 202.0)}
        return mapping[coin]

    place_orders = AsyncMock(return_value={"status": "ok"})
    setattr(hl, "_round_sz_px", fake_round_sz_px)
    setattr(hl, "place_orders", place_orders)

    orders = [
        {"coin": "BTC", "is_buy": True, "sz": 0.1, "px": 100.0, "ro": False},
        {"coin": "ETH", "is_buy": False, "sz": 0.2, "px": 200.0, "ro": True},
    ]

    resp = await hl.batch_place_orders(orders)

    assert resp == {"status": "ok"}
    await_args = place_orders.await_args
    assert await_args is not None
    assert await_args.args[0] == [
        {
            "coin": "BTC",
            "is_buy": True,
            "sz": 0.1,
            "px": 101.0,
            "ro": False,
            "asset": 10,
        },
        {
            "coin": "ETH",
            "is_buy": False,
            "sz": 0.2,
            "px": 202.0,
            "ro": True,
            "asset": 11,
        },
    ]


@pytest.mark.asyncio
async def test_get_batch_limit_orders_uses_cached_fast_path() -> None:
    hl = build_stub_hl()
    get_coin_name = AsyncMock(
        side_effect=AssertionError("cache miss path should not run")
    )
    setattr(hl, "coin_names", {"BTC": "BTC", "ETH": "ETH"})
    setattr(hl, "coin_assets", {"BTC": 10, "ETH": 11})
    setattr(hl, "asset_sz_decimals", {10: 1, 11: 2})
    setattr(hl, "get_coin_name", get_coin_name)

    orders = [
        {"coin": "BTC", "is_buy": True, "sz": 0.1, "px": 100.0, "ro": False},
        {"coin": "ETH", "is_buy": False, "sz": 0.25, "px": 200.0, "ro": True},
    ]

    reqs = await hl._get_batch_limit_orders(orders)

    assert reqs == [
        {"coin": "BTC", "is_buy": True, "sz": 0.1, "px": 100, "ro": False, "asset": 10},
        {
            "coin": "ETH",
            "is_buy": False,
            "sz": 0.25,
            "px": 200,
            "ro": True,
            "asset": 11,
        },
    ]
    get_coin_name.assert_not_called()


@pytest.mark.asyncio
async def test_close_positions_batches_requested_coins_only() -> None:
    hl = build_stub_hl()
    get_all_positions = AsyncMock(
        return_value=[
            {"coin": "flx:BTC", "szi": "-0.5"},
            {"coin": "ETH", "szi": "1.25"},
            {"coin": "SOL", "szi": "2.0"},
        ]
    )
    batch_place_orders = AsyncMock(return_value={"status": "ok"})
    setattr(hl, "get_all_positions", get_all_positions)
    setattr(hl, "batch_place_orders", batch_place_orders)

    resp = await hl.close_positions(["ETH", "flx:BTC", "MISSING"])

    assert resp == {"status": "ok"}
    get_all_positions.assert_awaited_once_with(dexs=["", "flx"])
    batch_place_orders.assert_awaited_once_with(
        [
            {"coin": "ETH", "is_buy": False, "sz": 1.25, "px": 0, "ro": True},
            {"coin": "flx:BTC", "is_buy": True, "sz": 0.5, "px": 0, "ro": True},
        ],
        is_market=True,
    )


@pytest.mark.asyncio
async def test_close_position_reuses_close_positions_batch_path() -> None:
    hl = build_stub_hl()
    close_positions = AsyncMock(return_value={"status": "ok"})
    setattr(hl, "close_positions", close_positions)

    resp = await hl.close_position("BTC")

    assert resp == {"status": "ok"}
    close_positions.assert_awaited_once_with(["BTC"])
