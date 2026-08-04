from inspect import Parameter, signature
from typing import cast
from unittest.mock import AsyncMock

import pytest

from async_hyperliquid import AsyncHyperliquid
from async_hyperliquid.exchange import ExchangeClient
from async_hyperliquid.types import (
    Builder,
    CancelByCloid,
    CancelOrder,
    Cloid,
    OrderGrouping,
    PlaceOrderRequest,
    PlaceOrderResponse,
    TimeInForce,
    TriggerKind,
    limit_order_type,
    trigger_order_type,
)


ADDRESS = "0x1111111111111111111111111111111111111111"
KEY = "0x" + "11" * 32
RESPONSE = cast(
    PlaceOrderResponse,
    {
        "status": "ok",
        "response": {"type": "order", "data": {"statuses": [{"resting": {"oid": 7}}]}},
    },
)


def test_root_place_order_keeps_the_expanded_compatibility_signature() -> None:
    parameters = signature(AsyncHyperliquid.place_order).parameters

    assert tuple(parameters) == (
        "self",
        "coin",
        "is_buy",
        "sz",
        "px",
        "is_market",
        "ro",
        "order_type",
        "cloid",
        "slippage",
        "builder",
        "expires_after",
    )
    assert parameters["is_market"].default is True
    assert parameters["ro"].kind is Parameter.KEYWORD_ONLY
    assert parameters["ro"].default is False
    assert parameters["order_type"].default is None
    assert parameters["cloid"].default is None
    assert parameters["slippage"].default == 0.05
    assert parameters["builder"].default is None
    assert parameters["expires_after"].default is None


async def test_place_order_dispatches_market_request_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    place_market_orders = AsyncMock(return_value=RESPONSE)
    monkeypatch.setattr(AsyncHyperliquid, "place_market_orders", place_market_orders)
    client = AsyncHyperliquid(ADDRESS, KEY)
    builder = Builder(
        address="0x2222222222222222222222222222222222222222", fee_tenths_bps=10
    )

    result = await client.place_order(
        "BTC", True, 0.01, 1.0, slippage=0.02, builder=builder, expires_after=123
    )

    assert result is RESPONSE
    place_market_orders.assert_awaited_once_with(
        (
            {
                "coin": "BTC",
                "is_buy": True,
                "sz": 0.01,
                "px": 1.0,
                "is_market": True,
                "ro": False,
                "order_type": None,
                "cloid": None,
                "slippage": 0.02,
            },
        ),
        builder=builder,
        expires_after=123,
    )


async def test_place_order_dispatches_default_ioc_limit_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    place_orders = AsyncMock(return_value=RESPONSE)
    monkeypatch.setattr(AsyncHyperliquid, "place_orders", place_orders)
    client = AsyncHyperliquid(ADDRESS, KEY)
    cloid = Cloid("0x" + "12" * 16)

    result = await client.place_order(
        "ETH", False, 0.2, 2_000.0, False, ro=True, cloid=cloid
    )

    assert result is RESPONSE
    call = place_orders.await_args
    assert call is not None
    request = call.args[0][0]
    assert request == {
        "coin": "ETH",
        "is_buy": False,
        "sz": 0.2,
        "px": 2_000.0,
        "is_market": False,
        "ro": True,
        "order_type": None,
        "cloid": cloid,
        "slippage": 0.05,
    }


async def test_outer_market_flag_does_not_override_trigger_execution_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    place_orders = AsyncMock(return_value=RESPONSE)
    monkeypatch.setattr(AsyncHyperliquid, "place_orders", place_orders)
    client = AsyncHyperliquid(ADDRESS, KEY)
    trigger = trigger_order_type(
        is_market=True, trigger_px="90000", tpsl=TriggerKind.STOP_LOSS
    )

    await client.place_order("BTC", False, 0.01, 90_000.0, False, order_type=trigger)

    call = place_orders.await_args
    assert call is not None
    request = call.args[0][0]
    assert request["is_market"] is False
    assert request["order_type"] == trigger


def test_batch_place_orders_is_the_same_function_as_place_orders() -> None:
    assert AsyncHyperliquid.batch_place_orders is AsyncHyperliquid.place_orders


async def test_batch_place_orders_alias_dispatches_the_canonical_batch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    encode_orders = AsyncMock(return_value=({"a": 0},))
    submit_orders = AsyncMock(return_value=RESPONSE)
    monkeypatch.setattr(AsyncHyperliquid, "_encode_orders", encode_orders)
    monkeypatch.setattr(ExchangeClient, "_submit_orders", submit_orders)
    client = AsyncHyperliquid(ADDRESS, KEY)
    orders: tuple[PlaceOrderRequest, ...] = (
        {
            "coin": "BTC",
            "is_buy": True,
            "sz": 0.01,
            "px": 100_000.0,
            "is_market": False,
        },
    )

    await client.batch_place_orders(orders)

    encode_orders.assert_awaited_once_with(orders)
    submit_orders.assert_awaited_once_with(
        ({"a": 0},), grouping=OrderGrouping.NA, builder=None, expires_after=None
    )


async def test_place_orders_dispatches_one_typed_batch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    encode_orders = AsyncMock(return_value=({"a": 0}, {"a": 1}))
    submit_orders = AsyncMock(return_value=RESPONSE)
    monkeypatch.setattr(AsyncHyperliquid, "_encode_orders", encode_orders)
    monkeypatch.setattr(ExchangeClient, "_submit_orders", submit_orders)
    client = AsyncHyperliquid(ADDRESS, KEY)
    orders: tuple[PlaceOrderRequest, ...] = (
        {
            "coin": "BTC",
            "is_buy": True,
            "sz": 0.01,
            "px": 100_000.0,
            "is_market": False,
            "order_type": limit_order_type(TimeInForce.GTC),
        },
        {"coin": "ETH", "is_buy": False, "sz": 0.1, "px": 2_000.0, "is_market": False},
    )

    await client.place_orders(orders, grouping=OrderGrouping.NORMAL_TPSL)

    encode_orders.assert_awaited_once_with(orders)
    submit_orders.assert_awaited_once_with(
        ({"a": 0}, {"a": 1}),
        grouping=OrderGrouping.NORMAL_TPSL,
        builder=None,
        expires_after=None,
    )


async def test_place_orders_rejects_mixed_market_semantics_before_exchange(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    market = AsyncMock(return_value=RESPONSE)
    submit = AsyncMock(return_value=RESPONSE)
    monkeypatch.setattr(AsyncHyperliquid, "place_market_orders", market)
    monkeypatch.setattr(ExchangeClient, "_submit_orders", submit)
    client = AsyncHyperliquid(ADDRESS, KEY)
    orders: tuple[PlaceOrderRequest, ...] = (
        {"coin": "BTC", "is_buy": True, "sz": 0.01, "px": 0.0, "is_market": True},
        {"coin": "ETH", "is_buy": False, "sz": 0.1, "px": 2_000.0, "is_market": False},
    )

    with pytest.raises(ValueError, match="same is_market"):
        await client.place_orders(orders)

    market.assert_not_awaited()
    submit.assert_not_awaited()


async def test_singular_order_methods_delegate_to_their_plural_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    place_orders = AsyncMock(return_value=RESPONSE)
    place_market_orders = AsyncMock(return_value=RESPONSE)
    monkeypatch.setattr(AsyncHyperliquid, "place_orders", place_orders)
    monkeypatch.setattr(AsyncHyperliquid, "place_market_orders", place_market_orders)
    client = AsyncHyperliquid(ADDRESS, KEY)
    limit: PlaceOrderRequest = {
        "coin": "BTC",
        "is_buy": True,
        "sz": 0.01,
        "px": 100_000.0,
        "is_market": False,
    }
    trigger: PlaceOrderRequest = {
        "coin": "BTC",
        "is_buy": True,
        "sz": 0.01,
        "px": 100_000.0,
        "is_market": False,
        "order_type": trigger_order_type(
            is_market=False, trigger_px="101000", tpsl=TriggerKind.TAKE_PROFIT
        ),
    }
    market: PlaceOrderRequest = {
        "coin": "BTC",
        "is_buy": True,
        "sz": 0.01,
        "px": 0.0,
        "is_market": True,
    }

    await client.place_limit_order(limit)
    await client.place_trigger_order(trigger)
    await client.place_market_order(market)

    assert [call.args[0] for call in place_orders.await_args_list] == [
        (limit,),
        (trigger,),
    ]
    place_market_orders.assert_awaited_once_with(
        (market,), builder=None, expires_after=None
    )


async def test_singular_cancel_methods_delegate_to_their_plural_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cancel_orders = AsyncMock()
    cancel_orders_by_cloid = AsyncMock()
    monkeypatch.setattr(AsyncHyperliquid, "cancel_orders", cancel_orders)
    monkeypatch.setattr(
        AsyncHyperliquid, "cancel_orders_by_cloid", cancel_orders_by_cloid
    )
    client = AsyncHyperliquid(ADDRESS, KEY)
    oid = CancelOrder("BTC", 7)
    by_cloid = CancelByCloid("BTC", Cloid("0x" + "12" * 16))

    await client.cancel_order(oid)
    await client.cancel_by_cloid(by_cloid)

    cancel_orders.assert_awaited_once_with((oid,), expires_after=None)
    cancel_orders_by_cloid.assert_awaited_once_with((by_cloid,), expires_after=None)
