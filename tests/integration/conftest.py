import os
from collections.abc import AsyncIterator
from pathlib import Path
from typing import cast

from dotenv import load_dotenv
import pytest
import pytest_asyncio

from async_hyperliquid import AsyncHyperliquid, InfoClient
from async_hyperliquid.types import Network

from .config import require_env, require_testnet, validate_credentials, validate_roles
from .info_client import IntegrationInfoClient


load_dotenv(Path(".env.local"), override=False)

_DEXS = ("",)


@pytest.fixture(scope="session")
def master_address() -> str:
    return require_env("HL_ADDR", os.environ)


@pytest.fixture(scope="session")
def api_wallet_address() -> str:
    return require_env("HL_AK", os.environ)


@pytest.fixture(scope="session")
def subaccount_address() -> str:
    return require_env("HL_SUB", os.environ)


@pytest_asyncio.fixture(
    scope="session",
    loop_scope="session",
    params=(Network.MAINNET, Network.TESTNET),
    ids=("mainnet", "testnet"),
)
async def info(request: pytest.FixtureRequest) -> AsyncIterator[IntegrationInfoClient]:
    network = cast(Network, request.param)
    async with IntegrationInfoClient(network) as client:
        yield client


def _prepare_exchange() -> None:
    require_testnet(os.environ)
    validate_credentials(os.environ)


async def _validate_exchange_roles(info: InfoClient) -> None:
    validate_roles(
        require_env("HL_ADDR", os.environ),
        await info.user_role(require_env("HL_AK", os.environ)),
        await info.user_role(require_env("HL_SUB", os.environ)),
    )


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def master_key_hl() -> AsyncIterator[AsyncHyperliquid]:
    _prepare_exchange()
    async with AsyncHyperliquid(
        require_env("HL_ADDR", os.environ),
        require_env("HL_PK", os.environ),
        network=Network.TESTNET,
        dexs=_DEXS,
    ) as client:
        await client.info.refresh_metadata()
        await _validate_exchange_roles(client.info)
        yield client


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def master_hl() -> AsyncIterator[AsyncHyperliquid]:
    _prepare_exchange()
    async with AsyncHyperliquid(
        require_env("HL_ADDR", os.environ),
        require_env("HL_SK", os.environ),
        network=Network.TESTNET,
        dexs=_DEXS,
    ) as client:
        await client.info.refresh_metadata()
        await _validate_exchange_roles(client.info)
        yield client


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def sub_hl() -> AsyncIterator[AsyncHyperliquid]:
    _prepare_exchange()
    async with AsyncHyperliquid(
        require_env("HL_ADDR", os.environ),
        require_env("HL_SK", os.environ),
        vault_address=require_env("HL_SUB", os.environ),
        network=Network.TESTNET,
        dexs=_DEXS,
    ) as client:
        await client.info.refresh_metadata()
        await _validate_exchange_roles(client.info)
        yield client
