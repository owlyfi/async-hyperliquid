import os
from collections.abc import AsyncIterator
from pathlib import Path

from dotenv import load_dotenv
import pytest
import pytest_asyncio

from async_hyperliquid import AsyncHyperliquid
from async_hyperliquid.types import Network


load_dotenv(Path(".env.local"))


def get_network() -> Network:
    return (
        Network.MAINNET
        if os.getenv("IS_MAINNET", "true").lower() == "true"
        else Network.TESTNET
    )


@pytest_asyncio.fixture(loop_scope="session")
async def hl() -> AsyncIterator[AsyncHyperliquid]:
    if os.getenv("RUN_LIVE_EXCHANGE_TESTS") != "true":
        raise pytest.skip.Exception(
            "set RUN_LIVE_EXCHANGE_TESTS=true to run exchange integration"
        )
    if get_network() is not Network.TESTNET:
        raise pytest.skip.Exception(
            "live exchange integration is restricted to testnet"
        )

    account_address = os.getenv("HL_ADDR")
    signing_key = os.getenv("HL_AK")
    if not account_address or not signing_key:
        raise pytest.skip.Exception(
            "HL_ADDR and HL_AK are required for exchange integration"
        )

    async with AsyncHyperliquid(
        account_address,
        signing_key,
        network=Network.TESTNET,
        perp_dexes=("", "flx", "vntl", "xyz"),
    ) as client:
        await client.info.refresh_metadata()
        yield client
