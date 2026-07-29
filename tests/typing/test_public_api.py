from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from async_hyperliquid import AsyncHyperliquid, ExchangeAPI, InfoAPI
from async_hyperliquid.utils.types import UserOpenOrders


async def check_public_types(client: AsyncHyperliquid) -> None:
    info: InfoAPI = client.info
    exchange: ExchangeAPI = client.exchange
    orders: UserOpenOrders = await info.get_user_open_orders("0x" + "00" * 20)
    del exchange, orders


@asynccontextmanager
async def open_client() -> AsyncIterator[AsyncHyperliquid]:
    async with AsyncHyperliquid("0x" + "11" * 20, "0x" + "22" * 32) as client:
        yield client
