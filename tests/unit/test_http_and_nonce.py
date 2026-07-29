from threading import Lock
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest
from aiohttp import ClientSession
from eth_account import Account

import async_hyperliquid._async_hyperliquid.core as core_module
import async_hyperliquid.exchange as exchange_module
from async_hyperliquid import AsyncHyperliquid
from async_hyperliquid.async_api import AsyncAPI
from async_hyperliquid.exchange import ExchangeAPI
from async_hyperliquid.info import InfoAPI


def build_stub_hl() -> AsyncHyperliquid:
    session = cast(ClientSession, SimpleNamespace(closed=False, close=AsyncMock()))
    return AsyncHyperliquid(
        "0x1111111111111111111111111111111111111111",
        "0x" + ("11" * 32),
        session=session,
    )


class StubResponse:
    async def __aenter__(self) -> "StubResponse":
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: object,
    ) -> None:
        return None

    def raise_for_status(self) -> None:
        return None

    async def json(self) -> dict[str, str]:
        return {"status": "ok"}


class RecordingSession:
    closed = False

    def __init__(self) -> None:
        self.urls: list[str] = []

    def post(self, url: str, *, json: object) -> StubResponse:
        self.urls.append(url)
        return StubResponse()


def test_next_nonce_increments_when_clock_repeats(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hl = build_stub_hl()
    hl._nonce_lock = Lock()
    hl._last_nonce = 0

    monkeypatch.setattr(core_module, "get_timestamp_ms", lambda: 1_700_000_000_000)

    assert hl.next_nonce() == 1_700_000_000_000
    assert hl.next_nonce() == 1_700_000_000_001
    assert hl.next_nonce() == 1_700_000_000_002


def test_async_hyperliquid_is_asyncapi_subtype() -> None:
    hl = build_stub_hl()
    assert isinstance(hl, AsyncAPI)


@pytest.mark.asyncio
async def test_async_hyperliquid_does_not_close_external_session() -> None:
    session = cast(Any, SimpleNamespace(closed=False, close=AsyncMock()))
    hl = AsyncHyperliquid(
        "0x1111111111111111111111111111111111111111",
        "0x" + ("11" * 32),
        session=session,
    )

    await hl.close()

    session.close.assert_not_awaited()
    assert hl.session is session
    assert hl.info.session is session
    assert hl.exchange.session is session


@pytest.mark.asyncio
async def test_async_hyperliquid_context_manager_returns_self_and_closes_owned_session() -> (
    None
):
    hl = AsyncHyperliquid(
        "0x1111111111111111111111111111111111111111", "0x" + ("11" * 32)
    )

    session = hl.session
    assert session is not None
    assert not session.closed

    async with hl as scoped_hl:
        assert scoped_hl is hl

    assert session.closed


@pytest.mark.asyncio
async def test_core_helper_dispatch_respects_facade_subclass_override() -> None:
    calls = {"count": 0}

    class CustomAsyncHyperliquid(AsyncHyperliquid):
        async def init_metas(self) -> None:
            calls["count"] += 1
            self.coin_names["BTC"] = "BTC"

    session = cast(Any, SimpleNamespace(closed=False, close=AsyncMock()))
    hl = CustomAsyncHyperliquid(
        "0x1111111111111111111111111111111111111111",
        "0x" + ("11" * 32),
        session=session,
    )
    hl.coin_assets = {}
    hl.coin_names = {}
    hl.coin_symbols = {}
    hl.asset_sz_decimals = {}
    hl.spot_tokens = {}
    hl.perp_dexs = [""]
    hl._metas_initialized = True

    coin_name = await hl.get_coin_name("BTC")

    assert coin_name == "BTC"
    assert calls["count"] == 1


@pytest.mark.asyncio
async def test_exchange_post_action_uses_injected_nonce_factory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    account = Account.from_key("0x" + ("22" * 32))
    session = cast(Any, SimpleNamespace())
    api = ExchangeAPI(account, session, nonce_factory=lambda: 1_700_000_000_123)
    post_action_with_sig = AsyncMock(return_value={"ok": True})
    api.post_action_with_sig = post_action_with_sig  # type: ignore[method-assign]

    signed: dict[str, Any] = {}
    expected_sig = {"r": "0x1", "s": "0x2", "v": 27}

    def fake_sign_action(
        wallet: Any,
        action: dict[str, Any],
        vault: str | None,
        nonce: int,
        is_mainnet: bool,
        expires: int | None,
    ) -> dict[str, Any]:
        signed["wallet"] = wallet
        signed["action"] = action
        signed["vault"] = vault
        signed["nonce"] = nonce
        signed["is_mainnet"] = is_mainnet
        signed["expires"] = expires
        return expected_sig

    monkeypatch.setattr(exchange_module, "sign_action", fake_sign_action)

    resp = await api.post_action({"type": "reserveRequestWeight", "weight": 5})

    assert resp == {"ok": True}
    assert signed["wallet"] is account
    assert signed["action"] == {"type": "reserveRequestWeight", "weight": 5}
    assert signed["vault"] is None
    assert signed["nonce"] == 1_700_000_000_123
    assert signed["is_mainnet"] is True
    assert signed["expires"] is None

    await_args = post_action_with_sig.await_args
    assert await_args is not None
    assert await_args.args == (
        {"type": "reserveRequestWeight", "weight": 5},
        expected_sig,
        1_700_000_000_123,
    )


def test_custom_exchange_url_uses_explicit_signing_network() -> None:
    account = Account.from_key("0x" + ("22" * 32))
    session = cast(Any, SimpleNamespace())

    api = ExchangeAPI(
        account, session, base_url="https://provider.example", is_mainnet=True
    )

    assert api.is_mainnet is True
    assert api._request_url == "https://provider.example/exchange"


@pytest.mark.asyncio
async def test_info_base_url_change_routes_the_next_request() -> None:
    session = RecordingSession()
    info = InfoAPI("https://api.hyperliquid.xyz", cast(Any, session))

    info.base_url = "http://local-node:3001"
    await info.get_all_mids()

    assert session.urls == ["http://local-node:3001/info"]
