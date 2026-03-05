from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest

import async_hyperliquid.async_hyperliquid as async_hl_module
from async_hyperliquid import AsyncHyperliquid


def build_stub_hl() -> Any:
    # Bypass __init__ for focused unit tests and allow dynamic mock patching.
    return cast(Any, object.__new__(AsyncHyperliquid))


@pytest.mark.asyncio
async def test_user_set_abstraction_builds_signed_action(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hl = build_stub_hl()
    hl.address = "0xAaBbCcDdEeFf0011223344556677889900AaBbCc"
    hl.account = object()
    hl.is_mainnet = True
    hl.vault = None
    hl.expires = None
    exchange = SimpleNamespace(
        post_action_with_sig=AsyncMock(return_value={"status": "ok"})
    )
    hl.exchange = exchange

    nonce = 1_700_000_000_000
    sig = {"r": "0x1", "s": "0x2", "v": 27}
    sign_call: dict[str, Any] = {}

    def fake_sign_user_set_abstraction_action(
        wallet: Any, action: dict[str, Any], is_mainnet: bool
    ) -> dict[str, Any]:
        sign_call["wallet"] = wallet
        sign_call["action"] = action
        sign_call["is_mainnet"] = is_mainnet
        return sig

    monkeypatch.setattr(async_hl_module, "get_timestamp_ms", lambda: nonce)
    monkeypatch.setattr(
        async_hl_module,
        "sign_user_set_abstraction_action",
        fake_sign_user_set_abstraction_action,
    )

    resp = await hl.user_set_abstraction("unifiedAccount")

    assert resp == {"status": "ok"}
    expected_action = {
        "type": "userSetAbstraction",
        "user": hl.address.lower(),
        "abstraction": "unifiedAccount",
        "nonce": nonce,
    }
    assert sign_call["wallet"] is hl.account
    assert sign_call["is_mainnet"] is True
    assert sign_call["action"] == expected_action

    await_args = exchange.post_action_with_sig.await_args
    assert await_args is not None
    assert await_args.args == (expected_action, sig, nonce)


@pytest.mark.asyncio
async def test_user_set_abstraction_rejects_invalid_user_address() -> None:
    hl = build_stub_hl()
    hl.address = "not-a-hex-address"
    hl.account = object()
    hl.is_mainnet = True
    hl.vault = None
    hl.expires = None
    exchange = SimpleNamespace(
        post_action_with_sig=AsyncMock(return_value={"status": "ok"})
    )
    hl.exchange = exchange

    with pytest.raises(ValueError, match="42-char hex address"):
        await hl.user_set_abstraction("disabled")


@pytest.mark.asyncio
async def test_agent_set_abstraction_posts_expected_action() -> None:
    hl = build_stub_hl()
    hl.vault = "0x1234567890123456789012345678901234567890"
    hl.expires = 1_700_000_001_000
    exchange = SimpleNamespace(post_action=AsyncMock(return_value={"ok": True}))
    hl.exchange = exchange

    resp = await hl.agent_set_abstraction("u")

    assert resp == {"ok": True}
    await_args = exchange.post_action.await_args
    assert await_args is not None
    assert await_args.args == (
        {"type": "agentSetAbstraction", "abstraction": "u"},
    )
    assert await_args.kwargs == {"vault": hl.vault, "expires": hl.expires}
