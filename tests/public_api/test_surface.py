from importlib import import_module
from inspect import Parameter, signature
from typing import cast

from aiohttp import ClientSession
import pytest

from async_hyperliquid import AsyncHyperliquid, InfoClient
from async_hyperliquid.exchange import ExchangeClient
from async_hyperliquid.types import Network


ADDRESS = "0xABCDEFabcdefABCDEFabcdefABCDEFabcdefABCD"
SIGNING_KEY = "0x" + "11" * 32


def test_root_constructor_is_explicit_and_creates_no_async_resource() -> None:
    parameters = signature(AsyncHyperliquid).parameters

    assert tuple(parameters) == (
        "account_address",
        "signing_key",
        "vault_address",
        "network",
        "info_url",
        "exchange_url",
        "session",
        "timeout",
        "perp_dexes",
    )
    assert parameters["account_address"].kind is Parameter.POSITIONAL_OR_KEYWORD
    assert parameters["signing_key"].kind is Parameter.POSITIONAL_OR_KEYWORD
    assert parameters["vault_address"].kind is Parameter.KEYWORD_ONLY
    assert parameters["vault_address"].default is None
    assert parameters["network"].kind is Parameter.KEYWORD_ONLY
    assert parameters["network"].default is Network.MAINNET
    assert parameters["perp_dexes"].default == ("",)

    client = AsyncHyperliquid(ADDRESS, SIGNING_KEY)

    assert client._transport._session is None
    assert client.exchange._account_address == ADDRESS.lower()
    assert not hasattr(type(client), "__getattr__")
    assert not hasattr(client, "all_mids")
    assert not hasattr(client, "place_limit_order")


def test_root_normalizes_vault_execution_target() -> None:
    client = AsyncHyperliquid(
        ADDRESS, SIGNING_KEY, vault_address="0xABCDEFabcdefABCDEFabcdefABCDEFabcdefABCD"
    )

    assert client.exchange._vault_address == ADDRESS.lower()


def test_root_rejects_invalid_vault_execution_target() -> None:
    with pytest.raises(ValueError, match="vault_address"):
        AsyncHyperliquid(ADDRESS, SIGNING_KEY, vault_address="not-an-address")


@pytest.mark.parametrize(
    ("account_address", "signing_key", "message"),
    [
        ("", SIGNING_KEY, "account_address"),
        ("not-an-address", SIGNING_KEY, "account_address"),
        (ADDRESS, "", "signing_key"),
        (ADDRESS, "not-a-key", "signing_key"),
    ],
)
def test_root_rejects_invalid_credentials_synchronously(
    account_address: str, signing_key: str, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        AsyncHyperliquid(account_address, signing_key)


@pytest.mark.parametrize(
    ("info_url", "exchange_url"),
    [
        ("/info", None),
        ("file:///tmp/info", None),
        (None, "exchange"),
        (None, "ftp://exchange.example/action"),
    ],
)
def test_clients_reject_non_http_absolute_endpoints(
    info_url: str | None, exchange_url: str | None
) -> None:
    with pytest.raises(ValueError, match=r"absolute HTTP\(S\)"):
        AsyncHyperliquid(
            ADDRESS, SIGNING_KEY, info_url=info_url, exchange_url=exchange_url
        )


@pytest.mark.parametrize("network", tuple(Network))
@pytest.mark.parametrize("custom_info", [False, True])
@pytest.mark.parametrize("custom_exchange", [False, True])
def test_network_and_endpoint_matrix_is_independent(
    network: Network, custom_info: bool, custom_exchange: bool
) -> None:
    info_url = "https://info.example/custom?token=secret" if custom_info else None
    exchange_url = (
        "https://exchange.example/custom?token=secret" if custom_exchange else None
    )

    client = AsyncHyperliquid(
        ADDRESS,
        SIGNING_KEY,
        network=network,
        info_url=info_url,
        exchange_url=exchange_url,
        perp_dexes=("", "xyz"),
    )

    assert client.info.info_url == (info_url or network.info_url)
    assert client.exchange.exchange_url == (exchange_url or network.exchange_url)
    assert client.exchange._network is network
    assert client.exchange._perp_dexes == ("", "xyz")
    assert client.info._transport is client._transport
    assert client.exchange._transport is client._transport


def test_child_clients_are_concrete_read_only_capabilities() -> None:
    client = AsyncHyperliquid(ADDRESS, SIGNING_KEY)

    assert type(client.info) is InfoClient
    assert type(client.exchange) is ExchangeClient
    with pytest.raises(AttributeError):
        client.info = InfoClient()  # type: ignore[misc]
    with pytest.raises(AttributeError):
        client.exchange = cast(ExchangeClient, object())  # type: ignore[misc]


def test_user_abstraction_has_no_per_call_target_override() -> None:
    assert tuple(signature(ExchangeClient.user_dex_abstraction).parameters) == (
        "self",
        "enabled",
    )
    assert tuple(signature(ExchangeClient.user_set_abstraction).parameters) == (
        "self",
        "abstraction",
    )


async def test_root_owns_one_session_and_closes_it_once() -> None:
    client = AsyncHyperliquid(ADDRESS, SIGNING_KEY)

    await client.open()
    session = client._transport._session
    assert session is not None
    assert not session.closed
    await client.open()
    assert client._transport._session is session

    await client.close()
    await client.close()
    assert session.closed


async def test_root_never_closes_an_injected_session() -> None:
    session = ClientSession()
    client = AsyncHyperliquid(ADDRESS, SIGNING_KEY, session=session)

    try:
        async with client as opened:
            assert opened is client
            assert client._transport._session is session
        assert not session.closed
    finally:
        await session.close()


@pytest.mark.parametrize(
    "module_name",
    [
        "async_hyperliquid.async_api",
        "async_hyperliquid.async_hyperliquid",
        "async_hyperliquid._async_hyperliquid",
        "async_hyperliquid._legacy_info",
        "async_hyperliquid._legacy_exchange",
        "async_hyperliquid.utils",
    ],
)
def test_legacy_modules_are_removed(module_name: str) -> None:
    with pytest.raises(ModuleNotFoundError):
        import_module(module_name)
