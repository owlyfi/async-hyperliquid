from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from async_hyperliquid import AsyncHyperliquid, InfoClient
from async_hyperliquid.exchange import ExchangeClient
from async_hyperliquid.types.info import OpenOrders


async def check_public_types(client: AsyncHyperliquid) -> None:
    info: InfoClient = client.info
    exchange: ExchangeClient = client.exchange
    orders: OpenOrders = await info.open_orders("0x" + "00" * 20)
    del exchange, orders


@asynccontextmanager
async def open_client() -> AsyncIterator[AsyncHyperliquid]:
    async with AsyncHyperliquid("0x" + "11" * 20, "0x" + "22" * 32) as client:
        yield client
