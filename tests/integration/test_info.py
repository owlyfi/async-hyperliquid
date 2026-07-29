import os
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio

from async_hyperliquid import InfoClient
from async_hyperliquid.types import Network
from tests.conftest import get_network


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_LIVE_INFO_TESTS") != "true",
    reason="set RUN_LIVE_INFO_TESTS=true to run read-only integration",
)


@pytest_asyncio.fixture(loop_scope="session")
async def live_info() -> AsyncIterator[InfoClient]:
    async with InfoClient(network=get_network()) as info:
        yield info


@pytest.mark.asyncio(loop_scope="session")
async def test_live_info_metadata_and_prices(live_info: InfoClient) -> None:
    await live_info.refresh_metadata()

    assert "" in await live_info.perp_dex_names()
    assert await live_info.asset_id("BTC") == 0
    assert await live_info.size_decimals("BTC") >= 0
    assert await live_info.mid_price("BTC") > 0
    assert await live_info.mark_price("BTC") > 0


@pytest.mark.asyncio(loop_scope="session")
async def test_live_info_account_queries_require_only_an_address(
    live_info: InfoClient,
) -> None:
    account_address = os.getenv(
        "HL_INFO_ADDRESS", "0x0000000000000000000000000000000000000000"
    )

    assert isinstance(await live_info.open_orders(account_address), list)
    assert isinstance(await live_info.positions(account_address), list)
    state = await live_info.account_state(account_address, perp_dexes=("", "xyz"))
    assert set(state) == {"perp", "spot", "dexs"}


def test_live_info_uses_explicit_network_without_credentials() -> None:
    info = InfoClient(network=Network.MAINNET)

    assert info.info_url == Network.MAINNET.info_url
    assert not hasattr(info, "exchange")
