import os
from collections.abc import AsyncIterator
from pathlib import Path

from dotenv import load_dotenv
import pytest
import pytest_asyncio

from async_hyperliquid import AsyncHyperliquid, InfoClient
from async_hyperliquid.types import Network

from .live_config import (
    require_env,
    require_testnet,
    validate_live_credentials,
    validate_live_roles,
)


load_dotenv(Path(".env.local"), override=False)

_DEXS = ("",)


def _require_opt_in(name: str) -> None:
    if os.environ.get(name) != "true":
        raise pytest.skip.Exception(
            f"set {name}=true to run this live integration suite"
        )


@pytest.fixture(scope="session")
def master_address() -> str:
    return require_env("HL_ADDR", os.environ)


@pytest.fixture(scope="session")
def api_wallet_address() -> str:
    return require_env("HL_AK", os.environ)


@pytest.fixture(scope="session")
def subaccount_address() -> str:
    return require_env("HL_SUB", os.environ)


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def info() -> AsyncIterator[InfoClient]:
    _require_opt_in("RUN_LIVE_INFO_TESTS")
    async with InfoClient(network=Network.TESTNET) as client:
        yield client


def _prepare_exchange() -> None:
    require_testnet(os.environ)
    _require_opt_in("RUN_LIVE_EXCHANGE_TESTS")
    validate_live_credentials(os.environ)


async def _validate_exchange_roles(info: InfoClient) -> None:
    validate_live_roles(
        require_env("HL_ADDR", os.environ),
        await info.user_role(require_env("HL_AK", os.environ)),
        await info.user_role(require_env("HL_SUB", os.environ)),
    )


@pytest.fixture(autouse=True)
def _require_destructive_opt_in(request: pytest.FixtureRequest) -> None:
    if (
        request.node.get_closest_marker("destructive_exchange") is not None
        and os.environ.get("RUN_DESTRUCTIVE_EXCHANGE_TESTS") != "true"
    ):
        raise pytest.skip.Exception(
            "set RUN_DESTRUCTIVE_EXCHANGE_TESTS=true to run destructive Exchange cases"
        )


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def master_hl() -> AsyncIterator[AsyncHyperliquid]:
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
async def api_hl() -> AsyncIterator[AsyncHyperliquid]:
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
