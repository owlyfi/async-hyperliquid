from inspect import signature
from typing import cast
from unittest.mock import AsyncMock

import pytest

from async_hyperliquid import AsyncHyperliquid
from async_hyperliquid.info import InfoClient
from async_hyperliquid.types import Builder, PlaceOrderResponse
from async_hyperliquid.types.info import Position


ADDRESS = "0x1111111111111111111111111111111111111111"
VAULT = "0x2222222222222222222222222222222222222222"
KEY = "0x" + "11" * 32
RESPONSE = cast(
    PlaceOrderResponse,
    {
        "status": "ok",
        "response": {
            "type": "order",
            "data": {
                "statuses": [{"filled": {"totalSz": "0.02", "avgPx": "1", "oid": 1}}]
            },
        },
    },
)


def position(coin: str, size: str) -> Position:
    return cast(Position, {"coin": coin, "szi": size})


def test_close_signatures_expose_only_full_position_controls() -> None:
    assert tuple(signature(AsyncHyperliquid.close_position).parameters) == (
        "self",
        "coin",
        "builder",
        "expires_after",
    )
    assert tuple(signature(AsyncHyperliquid.close_positions).parameters) == (
        "self",
        "coins",
        "dexs",
        "builder",
        "expires_after",
    )
    assert tuple(signature(AsyncHyperliquid.close_all_positions).parameters) == (
        "self",
        "dexs",
        "builder",
        "expires_after",
    )


async def test_selected_positions_use_one_read_and_one_order_batch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    positions = AsyncMock(
        return_value=[
            position("xyz:NVDA", "-0.5"),
            position("ETH", "1.25"),
            position("BTC", "0.02"),
        ]
    )
    place_orders = AsyncMock(return_value=RESPONSE)
    monkeypatch.setattr(InfoClient, "positions", positions)
    monkeypatch.setattr(AsyncHyperliquid, "place_orders", place_orders)
    client = AsyncHyperliquid(ADDRESS, KEY, vault_address=VAULT)
    builder = Builder(
        address="0x3333333333333333333333333333333333333333", fee_tenths_bps=10
    )

    result = await client.close_positions(
        ("BTC", "xyz:NVDA", "BTC"), builder=builder, expires_after=123
    )

    assert result is RESPONSE
    positions.assert_awaited_once_with(VAULT, dexs=("", "xyz"))
    place_orders.assert_awaited_once_with(
        (
            {
                "coin": "BTC",
                "is_buy": False,
                "sz": 0.02,
                "px": 0.0,
                "is_market": True,
                "ro": True,
            },
            {
                "coin": "xyz:NVDA",
                "is_buy": True,
                "sz": 0.5,
                "px": 0.0,
                "is_market": True,
                "ro": True,
            },
        ),
        builder=builder,
        expires_after=123,
    )


async def test_close_position_delegates_without_prefetching(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    close_positions = AsyncMock(return_value=RESPONSE)
    positions = AsyncMock(side_effect=AssertionError("wrapper must not prefetch"))
    monkeypatch.setattr(AsyncHyperliquid, "close_positions", close_positions)
    monkeypatch.setattr(InfoClient, "positions", positions)
    client = AsyncHyperliquid(ADDRESS, KEY)

    result = await client.close_position("BTC", expires_after=123)

    assert result is RESPONSE
    close_positions.assert_awaited_once_with(("BTC",), builder=None, expires_after=123)
    positions.assert_not_awaited()


async def test_close_all_positions_delegates_configured_dexs_without_prefetching(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    close_positions = AsyncMock(return_value=RESPONSE)
    positions = AsyncMock(side_effect=AssertionError("wrapper must not prefetch"))
    monkeypatch.setattr(AsyncHyperliquid, "close_positions", close_positions)
    monkeypatch.setattr(InfoClient, "positions", positions)
    client = AsyncHyperliquid(ADDRESS, KEY, dexs=("", "xyz"))

    result = await client.close_all_positions()

    assert result is RESPONSE
    close_positions.assert_awaited_once_with(
        None, dexs=None, builder=None, expires_after=None
    )
    positions.assert_not_awaited()


async def test_empty_or_flat_selection_does_not_submit_an_exchange_action(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    positions = AsyncMock(return_value=[position("BTC", "0")])
    place_orders = AsyncMock(return_value=RESPONSE)
    monkeypatch.setattr(InfoClient, "positions", positions)
    monkeypatch.setattr(AsyncHyperliquid, "place_orders", place_orders)
    client = AsyncHyperliquid(ADDRESS, KEY)

    assert await client.close_positions(()) is None
    positions.assert_not_awaited()
    assert await client.close_positions(("BTC",)) is None
    positions.assert_awaited_once_with(ADDRESS, dexs=("",))
    place_orders.assert_not_awaited()
