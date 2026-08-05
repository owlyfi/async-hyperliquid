from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import assert_type

from async_hyperliquid import AsyncHyperliquid, InfoClient
from async_hyperliquid.exchange import ExchangeClient
from async_hyperliquid.types.info import (
    AccountState,
    AllMids,
    OpenOrders,
    Position,
    SpotToken,
)


async def check_public_types(client: AsyncHyperliquid) -> None:
    info: InfoClient = client.info
    exchange: ExchangeClient = client.exchange
    account_address = "0x" + "00" * 20

    assert_type(await info.all_mids(), AllMids)
    assert_type(await info.open_orders(account_address), OpenOrders)
    assert_type(await info.account_state(account_address), AccountState)
    assert_type(await info.positions(account_address), list[Position])
    assert_type(await info.spot_token_metadata("@0"), SpotToken)
    assert_type(await info.asset_id("BTC"), int)
    del exchange


@asynccontextmanager
async def open_client() -> AsyncIterator[AsyncHyperliquid]:
    async with AsyncHyperliquid("0x" + "11" * 20, "0x" + "22" * 32) as client:
        assert_type(client, AsyncHyperliquid)
        yield client
