from inspect import Parameter, signature
from typing import cast
from unittest.mock import AsyncMock

import pytest

from async_hyperliquid import AsyncHyperliquid, InfoClient
from async_hyperliquid._internal.metadata import _MarketInfo
from async_hyperliquid.client import _market_limit_price
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
BUILDER_ADDRESS = "0x2222222222222222222222222222222222222222"
KEY = "0x" + "11" * 32
RESPONSE = cast(
    PlaceOrderResponse,
    {
        "status": "ok",
        "response": {"type": "order", "data": {"statuses": [{"resting": {"oid": 7}}]}},
    },
)


def _limit_request(coin: str = "BTC") -> PlaceOrderRequest:
    return {
        "coin": coin,
        "is_buy": True,
        "sz": 0.01,
        "px": 100_000.0,
        "is_market": False,
        "order_type": limit_order_type(TimeInForce.GTC),
    }


def _spot_limit_request() -> PlaceOrderRequest:
    return {
        "coin": "@0",
        "is_buy": True,
        "sz": 1.0,
        "px": 1.0,
        "is_market": False,
        "order_type": limit_order_type(TimeInForce.GTC),
    }


def _market_request() -> PlaceOrderRequest:
    return {"coin": "BTC", "is_buy": True, "sz": 0.01, "px": 0.0, "is_market": True}


def _trigger_request() -> PlaceOrderRequest:
    return {
        "coin": "BTC",
        "is_buy": False,
        "sz": 0.01,
        "px": 90_000.0,
        "is_market": False,
        "ro": True,
        "order_type": trigger_order_type(
            is_market=True, trigger_px="90000", tpsl=TriggerKind.STOP_LOSS
        ),
    }


@pytest.mark.parametrize(
    ("mid", "is_buy", "expected"),
    [
        (0.99999, True, 0.99999),
        (0.00001, False, 0.00001),
        (0.4, True, 0.42),
        (0.4, False, 0.38),
    ],
)
def test_outcome_market_limit_price_stays_in_domain(
    mid: float, is_buy: bool, expected: float
) -> None:
    assert _market_limit_price(
        mid, is_buy=is_buy, slippage=0.05, is_outcome=True
    ) == pytest.approx(expected)


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


@pytest.mark.parametrize("is_market", [False, True])
async def test_place_order_always_dispatches_to_place_orders(
    monkeypatch: pytest.MonkeyPatch, is_market: bool
) -> None:
    place_orders = AsyncMock(return_value=RESPONSE)
    monkeypatch.setattr(AsyncHyperliquid, "place_orders", place_orders)
    client = AsyncHyperliquid(ADDRESS, KEY)
    builder = Builder(address=BUILDER_ADDRESS, fee_tenths_bps=10)

    result = await client.place_order(
        "BTC",
        True,
        0.01,
        100_000.0,
        is_market=is_market,
        slippage=0.02,
        builder=builder,
        expires_after=123,
    )

    assert result is RESPONSE
    place_orders.assert_awaited_once()
    call = place_orders.await_args
    assert call is not None
    request = call.args[0][0]
    assert request == {
        "coin": "BTC",
        "is_buy": True,
        "sz": 0.01,
        "px": 100_000.0,
        "is_market": is_market,
        "ro": False,
        "order_type": None,
        "cloid": None,
        "slippage": 0.02,
    }
    assert call.kwargs == {"builder": builder, "expires_after": 123}


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
    market_infos = AsyncMock(return_value=(_MarketInfo("BTC", 0, 5, False, ""),))
    submit_orders = AsyncMock(return_value=RESPONSE)
    monkeypatch.setattr(InfoClient, "_market_infos", market_infos)
    monkeypatch.setattr(ExchangeClient, "_submit_orders", submit_orders)
    client = AsyncHyperliquid(ADDRESS, KEY)
    orders = (_limit_request(),)

    await client.batch_place_orders(orders)

    market_infos.assert_awaited_once_with(("BTC",))
    submit_orders.assert_awaited_once_with(
        (
            {
                "a": 0,
                "b": True,
                "p": "100000",
                "s": "0.01",
                "r": False,
                "t": {"limit": {"tif": "Gtc"}},
            },
        ),
        grouping=OrderGrouping.NA,
        builder=None,
        expires_after=None,
    )


async def test_place_orders_dispatches_one_typed_batch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    market_infos = AsyncMock(
        return_value=(
            _MarketInfo("BTC", 0, 5, False, ""),
            _MarketInfo("ETH", 1, 4, False, ""),
        )
    )
    submit_orders = AsyncMock(return_value=RESPONSE)
    monkeypatch.setattr(InfoClient, "_market_infos", market_infos)
    monkeypatch.setattr(ExchangeClient, "_submit_orders", submit_orders)
    client = AsyncHyperliquid(ADDRESS, KEY)
    orders: tuple[PlaceOrderRequest, ...] = (
        _limit_request(),
        {"coin": "ETH", "is_buy": False, "sz": 0.1, "px": 2_000.0, "is_market": False},
    )

    await client.place_orders(orders)

    market_infos.assert_awaited_once_with(("BTC", "ETH"))
    submit_orders.assert_awaited_once()
    call = submit_orders.await_args
    assert call is not None
    assert len(call.args[0]) == 2


async def test_outer_market_mode_cannot_replace_a_trigger(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    market_infos = AsyncMock()
    submit = AsyncMock()
    monkeypatch.setattr(InfoClient, "_market_infos", market_infos)
    monkeypatch.setattr(ExchangeClient, "_submit_orders", submit)
    client = AsyncHyperliquid(ADDRESS, KEY)
    order = _trigger_request()
    order["is_market"] = True

    with pytest.raises(ValueError, match="trigger.isMarket"):
        await client.place_orders((order,))

    market_infos.assert_not_awaited()
    submit.assert_not_awaited()


async def test_normal_tpsl_requires_parent_and_trigger_child(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    market_infos = AsyncMock()
    monkeypatch.setattr(InfoClient, "_market_infos", market_infos)
    client = AsyncHyperliquid(ADDRESS, KEY)

    with pytest.raises(ValueError, match="parent and at least one trigger child"):
        await client.place_orders(
            (_limit_request(),), grouping=OrderGrouping.NORMAL_TPSL
        )

    market_infos.assert_not_awaited()


async def test_normal_tpsl_rejects_trigger_as_parent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    market_infos = AsyncMock()
    monkeypatch.setattr(InfoClient, "_market_infos", market_infos)
    client = AsyncHyperliquid(ADDRESS, KEY)

    with pytest.raises(ValueError, match="first order must be a non-trigger parent"):
        await client.place_orders(
            (_trigger_request(), _trigger_request()), grouping=OrderGrouping.NORMAL_TPSL
        )

    market_infos.assert_not_awaited()


async def test_normal_tpsl_rejects_non_trigger_child(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    market_infos = AsyncMock()
    monkeypatch.setattr(InfoClient, "_market_infos", market_infos)
    client = AsyncHyperliquid(ADDRESS, KEY)

    with pytest.raises(ValueError, match="child orders must be trigger orders"):
        await client.place_orders(
            (_limit_request(), _limit_request()), grouping=OrderGrouping.NORMAL_TPSL
        )

    market_infos.assert_not_awaited()


async def test_place_orders_normalizes_only_the_market_subset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parent = _market_request()
    child = _trigger_request()
    btc = _MarketInfo("BTC", 0, 5, False, "")
    market_infos = AsyncMock(return_value=(btc, btc))
    mid_prices = AsyncMock(return_value=(100_000.0,))
    submit = AsyncMock(return_value=RESPONSE)
    monkeypatch.setattr(InfoClient, "_market_infos", market_infos)
    monkeypatch.setattr(InfoClient, "_mid_prices", mid_prices)
    monkeypatch.setattr(ExchangeClient, "_submit_orders", submit)
    client = AsyncHyperliquid(ADDRESS, KEY)

    await client.place_orders((parent, child), grouping=OrderGrouping.NORMAL_TPSL)

    market_infos.assert_awaited_once_with(("BTC", "BTC"))
    mid_prices.assert_awaited_once_with((btc,))
    submit.assert_awaited_once()
    call = submit.await_args
    assert call is not None
    encoded = call.args[0]
    assert encoded[0]["t"] == {"limit": {"tif": "Ioc"}}
    assert encoded[1]["t"] == {
        "trigger": {"isMarket": True, "triggerPx": "90000", "tpsl": "sl"}
    }


async def test_place_orders_rejects_spot_and_perp_in_one_batch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    market_infos = AsyncMock(
        return_value=(
            _MarketInfo("BTC", 0, 5, False, ""),
            _MarketInfo("PURR/USDC", 10_000, 0, True, ""),
        )
    )
    mid_prices = AsyncMock()
    submit = AsyncMock()
    monkeypatch.setattr(InfoClient, "_market_infos", market_infos)
    monkeypatch.setattr(InfoClient, "_mid_prices", mid_prices)
    monkeypatch.setattr(ExchangeClient, "_submit_orders", submit)
    client = AsyncHyperliquid(ADDRESS, KEY)

    with pytest.raises(
        ValueError, match="orders cannot mix spot and perpetual markets"
    ):
        await client.place_orders((_limit_request(), _spot_limit_request()))

    mid_prices.assert_not_awaited()
    submit.assert_not_awaited()


@pytest.mark.parametrize(
    ("market", "fee"),
    [
        (_MarketInfo("BTC", 0, 5, False, ""), 100),
        (_MarketInfo("ETH", 1, 4, False, ""), 100),
        (_MarketInfo("@107", 10_107, 2, True, ""), 1000),
        (_MarketInfo("#10", 100_000_010, 0, True, ""), 1000),
    ],
)
async def test_place_orders_accepts_builder_fee_at_venue_limit(
    monkeypatch: pytest.MonkeyPatch, market: _MarketInfo, fee: int
) -> None:
    market_infos = AsyncMock(return_value=(market,))
    submit = AsyncMock(return_value=RESPONSE)
    monkeypatch.setattr(InfoClient, "_market_infos", market_infos)
    monkeypatch.setattr(ExchangeClient, "_submit_orders", submit)
    client = AsyncHyperliquid(ADDRESS, KEY)
    order = _limit_request(market.coin)
    if market.coin.startswith("#"):
        order["px"] = 0.4
        order["sz"] = 1.0

    await client.place_orders(
        (order,), builder=Builder(address=BUILDER_ADDRESS, fee_tenths_bps=fee)
    )

    submit.assert_awaited_once()


@pytest.mark.parametrize(
    ("market", "fee", "maximum"),
    [
        (_MarketInfo("BTC", 0, 5, False, ""), 101, 100),
        (_MarketInfo("@107", 10_107, 2, True, ""), 1001, 1000),
        (_MarketInfo("#10", 100_000_010, 0, True, ""), 1001, 1000),
    ],
)
async def test_place_orders_rejects_builder_fee_above_venue_limit(
    monkeypatch: pytest.MonkeyPatch, market: _MarketInfo, fee: int, maximum: int
) -> None:
    market_infos = AsyncMock(return_value=(market,))
    mid_prices = AsyncMock()
    submit = AsyncMock()
    monkeypatch.setattr(InfoClient, "_market_infos", market_infos)
    monkeypatch.setattr(InfoClient, "_mid_prices", mid_prices)
    monkeypatch.setattr(ExchangeClient, "_submit_orders", submit)
    client = AsyncHyperliquid(ADDRESS, KEY)
    order = _market_request()
    order["coin"] = market.coin

    with pytest.raises(ValueError, match=rf"fee_tenths_bps must be <= {maximum}"):
        await client.place_orders(
            (order,), builder=Builder(address=BUILDER_ADDRESS, fee_tenths_bps=fee)
        )

    market_infos.assert_awaited_once()
    mid_prices.assert_not_awaited()
    submit.assert_not_awaited()


async def test_place_orders_does_not_reject_spot_buy_with_builder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    market = _MarketInfo("@107", 10_107, 2, True, "")
    market_infos = AsyncMock(return_value=(market,))
    submit = AsyncMock(return_value=RESPONSE)
    monkeypatch.setattr(InfoClient, "_market_infos", market_infos)
    monkeypatch.setattr(ExchangeClient, "_submit_orders", submit)
    client = AsyncHyperliquid(ADDRESS, KEY)
    order = _spot_limit_request()
    order["coin"] = "HYPE/USDC"

    await client.place_orders(
        (order,), builder=Builder(address=BUILDER_ADDRESS, fee_tenths_bps=1000)
    )

    submit.assert_awaited_once()


async def test_singular_order_methods_delegate_to_place_orders(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    place_orders = AsyncMock(return_value=RESPONSE)
    monkeypatch.setattr(AsyncHyperliquid, "place_orders", place_orders)
    client = AsyncHyperliquid(ADDRESS, KEY)
    limit = _limit_request()
    trigger = _trigger_request()
    market = _market_request()

    await client.place_limit_order(limit)
    await client.place_market_order(market)
    await client.place_trigger_order(trigger, grouping=OrderGrouping.POSITION_TPSL)

    assert [call.args[0] for call in place_orders.await_args_list] == [
        (limit,),
        (market,),
        (trigger,),
    ]
    assert place_orders.await_args_list[-1].kwargs["grouping"] is (
        OrderGrouping.POSITION_TPSL
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
