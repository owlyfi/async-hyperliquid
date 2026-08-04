from copy import deepcopy
import json
from pathlib import Path
from typing import Literal, cast

from eth_account import Account
from eth_account.signers.local import LocalAccount
import pytest

import async_hyperliquid.exchange as exchange_module
from async_hyperliquid._http import _HttpTransport
from async_hyperliquid._signing import (
    _APPROVE_AGENT_SPEC,
    _USD_SEND_SPEC,
    _sign_user_action,
    sign_exchange_action,
)
from async_hyperliquid.exchange import ExchangeClient
from async_hyperliquid.info import InfoClient
from async_hyperliquid.types import (
    BuilderFee,
    CancelByCloid,
    CancelOrder,
    Cloid,
    JsonObject,
    JsonValue,
    LimitOrder,
    MarketOrder,
    ModifyOrder,
    Network,
    OrderGrouping,
    Side,
    UserAbstraction,
)
from async_hyperliquid.types.exchange import Signature
from async_hyperliquid.types.info import Position, SpotToken


ADDRESS = "0x1111111111111111111111111111111111111111"
VAULT_ADDRESS = "0x2222222222222222222222222222222222222222"
NONCE = 1_700_000_000_000
FIXTURES = Path(__file__).parents[1] / "contracts" / "fixtures"
DEFAULT_RESPONSE: JsonObject = {"status": "ok", "response": {"type": "default"}}


def load_exchange_response(name: str) -> JsonValue:
    responses = cast(
        dict[str, JsonValue],
        json.loads((FIXTURES / "exchange-responses.json").read_text()),
    )
    return responses[name]


class RecordingTransport:
    def __init__(self, response: JsonValue) -> None:
        self.response = response
        self.requests: list[tuple[str, JsonObject]] = []

    async def post_json(self, url: str, payload: JsonObject) -> JsonValue:
        self.requests.append((url, deepcopy(payload)))
        return deepcopy(self.response)


class StubInfo:
    def __init__(self) -> None:
        self.mids = {"BTC": 100_000.0, "ETH": 2_000.0}
        self.open_positions: list[Position] = []
        self.market_info_calls = 0
        self.mid_price_batches: list[tuple[str, ...]] = []
        self.mid_price_calls = 0
        self.position_accounts: list[str] = []

    async def _market_info(self, coin: str) -> tuple[int, int]:
        markets = {"BTC": (0, 5), "ETH": (1, 4), "xyz:NVDA": (110_002, 3)}
        return markets[coin]

    async def _market_infos(
        self, coins: tuple[str, ...]
    ) -> tuple[tuple[int, int], ...]:
        self.market_info_calls += 1
        return tuple([await self._market_info(coin) for coin in coins])

    async def asset_id(self, coin: str) -> int:
        return (await self._market_info(coin))[0]

    async def mid_price(self, coin: str) -> float:
        self.mid_price_calls += 1
        return self.mids[coin]

    async def _mid_prices(self, coins: tuple[str, ...]) -> tuple[float, ...]:
        self.mid_price_batches.append(coins)
        return tuple(self.mids[coin] for coin in coins)

    async def positions(
        self, account_address: str, *, perp_dexes: tuple[str, ...] = ("",)
    ) -> list[Position]:
        self.position_accounts.append(account_address)
        return self.open_positions

    async def spot_token_metadata(self, coin: str) -> SpotToken:
        assert coin == "USOL"
        return {
            "name": "USOL",
            "index": 42,
            "isCanonical": False,
            "szDecimals": 3,
            "weiDecimals": 5,
            "tokenId": "0x1234",
            "evmContract": None,
            "fullName": "Wrapped SOL",
        }


def build_exchange(
    transport: RecordingTransport,
    *,
    network: Network = Network.MAINNET,
    exchange_url: str | None = None,
    vault_address: str | None = None,
) -> ExchangeClient:
    return ExchangeClient(
        cast(_HttpTransport, transport),
        cast(InfoClient, StubInfo()),
        Account.from_key("0x" + "11" * 32),
        account_address=ADDRESS,
        vault_address=vault_address,
        network=network,
        exchange_url=exchange_url,
    )


def test_exchange_client_uses_normal_dependency_construction() -> None:
    transport = RecordingTransport(DEFAULT_RESPONSE)

    client = ExchangeClient(
        cast(_HttpTransport, transport),
        cast(InfoClient, StubInfo()),
        Account.from_key("0x" + "11" * 32),
        account_address=ADDRESS,
        vault_address=VAULT_ADDRESS,
        network=Network.MAINNET,
    )

    assert client._transport is transport
    assert client._vault_address == VAULT_ADDRESS
    assert not hasattr(ExchangeClient, "_from_transport")


def test_exchange_client_owns_address_validation_and_normalization() -> None:
    transport = RecordingTransport(DEFAULT_RESPONSE)
    mixed_case = "0xABCDEFabcdefABCDEFabcdefABCDEFabcdefABCD"

    client = ExchangeClient(
        cast(_HttpTransport, transport),
        cast(InfoClient, StubInfo()),
        Account.from_key("0x" + "11" * 32),
        account_address=mixed_case,
        vault_address=mixed_case,
        network=Network.MAINNET,
    )

    assert client._account_address == mixed_case.lower()
    assert client._vault_address == mixed_case.lower()

    with pytest.raises(ValueError, match="account_address"):
        ExchangeClient(
            cast(_HttpTransport, transport),
            cast(InfoClient, StubInfo()),
            Account.from_key("0x" + "11" * 32),
            account_address="invalid",
            vault_address=None,
            network=Network.MAINNET,
        )
    with pytest.raises(ValueError, match="vault_address"):
        ExchangeClient(
            cast(_HttpTransport, transport),
            cast(InfoClient, StubInfo()),
            Account.from_key("0x" + "11" * 32),
            account_address=ADDRESS,
            vault_address="invalid",
            network=Network.MAINNET,
        )


def test_exchange_client_is_transport_bound_and_url_is_read_only() -> None:
    transport = RecordingTransport(load_exchange_response("order_resting"))
    mainnet = build_exchange(transport)
    testnet = build_exchange(transport, network=Network.TESTNET)
    custom = build_exchange(
        transport,
        network=Network.TESTNET,
        exchange_url="https://provider.example/custom/exchange",
    )

    assert mainnet.exchange_url == Network.MAINNET.exchange_url
    assert testnet.exchange_url == Network.TESTNET.exchange_url
    assert custom.exchange_url == "https://provider.example/custom/exchange"
    with pytest.raises(AttributeError):
        custom.exchange_url = "https://other.example/exchange"  # type: ignore[misc]


async def test_batch_orders_sign_and_post_once_without_mutating_commands(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = RecordingTransport(load_exchange_response("order_resting"))
    client = build_exchange(transport)
    monkeypatch.setattr(exchange_module, "time_ns", lambda: NONCE * 1_000_000)
    sign_calls = 0

    def spy_sign(
        account: LocalAccount,
        action: JsonObject,
        vault_address: str | None,
        nonce: int,
        signature_source: Literal["a", "b"],
        expires_after: int | None = None,
    ) -> Signature:
        nonlocal sign_calls
        sign_calls += 1
        return sign_exchange_action(
            account, action, vault_address, nonce, signature_source, expires_after
        )

    monkeypatch.setattr(exchange_module, "sign_exchange_action", spy_sign)
    orders = (
        LimitOrder("BTC", Side.BUY, 0.01, 100_000),
        LimitOrder("ETH", Side.SELL, 0.2, 2_000, reduce_only=True),
    )
    builder = BuilderFee("0xABCDEFabcdefABCDEFabcdefABCDEFabcdefABCD", 10)

    response = await client.place_orders(
        orders,
        grouping=OrderGrouping.NORMAL_TPSL,
        builder_fee=builder,
        expires_after=NONCE + 1_000,
    )

    assert response == load_exchange_response("order_resting")
    assert sign_calls == 1
    assert cast(StubInfo, client._info).market_info_calls == 1
    assert len(transport.requests) == 1
    url, envelope = transport.requests[0]
    assert url == Network.MAINNET.exchange_url
    action = cast(JsonObject, envelope["action"])
    assert action["grouping"] == "normalTpsl"
    assert len(cast(list[JsonValue], action["orders"])) == 2
    assert action["builder"] == {
        "b": "0xabcdefabcdefabcdefabcdefabcdefabcdefabcd",
        "f": 10,
    }
    assert envelope["expiresAfter"] == NONCE + 1_000
    assert builder.address == "0xABCDEFabcdefABCDEFabcdefABCDEFabcdefABCD"


async def test_vault_target_is_signed_and_sent_with_l1_actions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = RecordingTransport(load_exchange_response("order_resting"))
    client = build_exchange(transport, vault_address=VAULT_ADDRESS)
    monkeypatch.setattr(exchange_module, "time_ns", lambda: NONCE * 1_000_000)
    signed_vaults: list[str | None] = []

    def spy_sign(
        account: LocalAccount,
        action: JsonObject,
        vault_address: str | None,
        nonce: int,
        signature_source: Literal["a", "b"],
        expires_after: int | None = None,
    ) -> Signature:
        signed_vaults.append(vault_address)
        return sign_exchange_action(
            account, action, vault_address, nonce, signature_source, expires_after
        )

    monkeypatch.setattr(exchange_module, "sign_exchange_action", spy_sign)

    await client.place_limit_order(LimitOrder("BTC", Side.BUY, 0.01, 100_000))

    assert signed_vaults == [VAULT_ADDRESS]
    assert transport.requests[0][1]["vaultAddress"] == VAULT_ADDRESS


async def test_root_scoped_actions_do_not_use_vault_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = RecordingTransport(DEFAULT_RESPONSE)
    client = build_exchange(transport, vault_address=VAULT_ADDRESS)
    monkeypatch.setattr(exchange_module, "time_ns", lambda: NONCE * 1_000_000)
    signed_vaults: list[str | None] = []

    def spy_sign(
        account: LocalAccount,
        action: JsonObject,
        vault_address: str | None,
        nonce: int,
        signature_source: Literal["a", "b"],
        expires_after: int | None = None,
    ) -> Signature:
        signed_vaults.append(vault_address)
        return sign_exchange_action(
            account, action, vault_address, nonce, signature_source, expires_after
        )

    monkeypatch.setattr(exchange_module, "sign_exchange_action", spy_sign)

    await client.set_referrer_code("referrer")
    await client.create_sub_account("sub-account")
    await client.vault_transfer(VAULT_ADDRESS, 1)
    await client.reserve_request_weight(10)
    await client.use_big_blocks(True)

    assert signed_vaults == [None, None, None, None, None]
    assert all("vaultAddress" not in envelope for _, envelope in transport.requests)


async def test_vault_target_selects_position_account() -> None:
    transport = RecordingTransport(load_exchange_response("order_filled"))
    client = build_exchange(transport, vault_address=VAULT_ADDRESS)
    info = cast(StubInfo, client._info)

    assert await client.close_positions() is None
    assert info.position_accounts == [VAULT_ADDRESS]


async def test_vault_target_uses_protocol_specific_transfer_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = RecordingTransport(DEFAULT_RESPONSE)
    client = build_exchange(transport, vault_address=VAULT_ADDRESS)
    monkeypatch.setattr(exchange_module, "time_ns", lambda: NONCE * 1_000_000)

    await client.usd_transfer(1.15, ADDRESS)
    assert transport.requests[-1][1]["vaultAddress"] == VAULT_ADDRESS

    await client.usd_class_transfer(1.15)
    class_transfer = transport.requests[-1][1]
    assert cast(JsonObject, class_transfer["action"])["amount"] == (
        f"1.15 subaccount:{VAULT_ADDRESS}"
    )
    assert "vaultAddress" not in class_transfer

    await client.send_asset(
        "USOL", 1.15, ADDRESS, source_dex="", destination_dex="spot"
    )
    send_asset = transport.requests[-1][1]
    assert cast(JsonObject, send_asset["action"])["fromSubAccount"] == VAULT_ADDRESS
    assert "vaultAddress" not in send_asset


async def test_send_asset_cannot_override_constructor_target() -> None:
    transport = RecordingTransport(DEFAULT_RESPONSE)
    client = build_exchange(transport, vault_address=VAULT_ADDRESS)

    with pytest.raises(TypeError):
        await client.send_asset(
            "USOL",
            1.15,
            ADDRESS,
            source_dex="",
            destination_dex="spot",
            from_sub_account="",  # type: ignore[unknown-argument]
        )

    assert transport.requests == []


async def test_market_order_reads_info_then_submits_directly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = RecordingTransport(load_exchange_response("order_filled"))
    client = build_exchange(
        transport,
        network=Network.TESTNET,
        exchange_url="https://provider.example/exchange",
    )
    info = cast(StubInfo, client._info)
    info.mids["BTC"] = 100.0
    monkeypatch.setattr(exchange_module, "time_ns", lambda: NONCE * 1_000_000)

    await client.place_market_order(MarketOrder("BTC", Side.BUY, 0.1, slippage=0.05))

    _, envelope = transport.requests[0]
    action = cast(JsonObject, envelope["action"])
    encoded = cast(list[JsonObject], action["orders"])[0]
    assert encoded["p"] == "105"
    assert envelope["signature"] == sign_exchange_action(
        client._account, action, None, NONCE, Network.TESTNET.signature_source
    )


async def test_market_orders_use_one_batched_mid_price_lookup() -> None:
    client = build_exchange(RecordingTransport(load_exchange_response("order_filled")))
    info = cast(StubInfo, client._info)

    await client._encode_market_orders(
        (MarketOrder("BTC", Side.BUY, 0.01), MarketOrder("ETH", Side.SELL, 0.1))
    )

    assert info.mid_price_batches == [("BTC", "ETH")]
    assert info.mid_price_calls == 0


async def test_cancel_and_modify_commands_encode_without_alias_wrappers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = RecordingTransport(load_exchange_response("cancel_success"))
    client = build_exchange(transport)
    monkeypatch.setattr(exchange_module, "time_ns", lambda: NONCE * 1_000_000)

    await client.cancel_orders((CancelOrder("BTC", 12), CancelOrder("ETH", 13)))
    cancel_action = cast(JsonObject, transport.requests[-1][1]["action"])
    assert cancel_action == {
        "type": "cancel",
        "cancels": [{"a": 0, "o": 12}, {"a": 1, "o": 13}],
    }

    await client.cancel_orders_by_cloid(
        (CancelByCloid("BTC", Cloid("0x" + "12" * 16)),)
    )
    cloid_action = cast(JsonObject, transport.requests[-1][1]["action"])
    assert cloid_action["type"] == "cancelByCloid"

    transport.response = load_exchange_response("order_resting")
    await client.modify_orders(
        (ModifyOrder(12, LimitOrder("BTC", Side.SELL, 0.01, 101_000)),)
    )
    modify_action = cast(JsonObject, transport.requests[-1][1]["action"])
    assert modify_action["type"] == "batchModify"


async def test_twap_methods_accept_their_exact_response_kinds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = RecordingTransport(load_exchange_response("twap_order_running"))
    client = build_exchange(transport)
    monkeypatch.setattr(exchange_module, "time_ns", lambda: NONCE * 1_000_000)

    placed = await client.place_twap("BTC", Side.BUY, 0.01, 5)

    assert placed == load_exchange_response("twap_order_running")
    transport.response = load_exchange_response("twap_cancel_success")

    cancelled = await client.cancel_twap("BTC", 77738308)

    assert cancelled == load_exchange_response("twap_cancel_success")


async def test_twap_below_market_precision_fails_before_signing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = RecordingTransport(load_exchange_response("twap_order_running"))
    client = build_exchange(transport)
    sign_calls = 0

    def spy_sign(
        account: LocalAccount,
        action: JsonObject,
        vault_address: str | None,
        nonce: int,
        signature_source: Literal["a", "b"],
        expires_after: int | None = None,
    ) -> Signature:
        nonlocal sign_calls
        sign_calls += 1
        return sign_exchange_action(
            account, action, vault_address, nonce, signature_source, expires_after
        )

    monkeypatch.setattr(exchange_module, "sign_exchange_action", spy_sign)

    with pytest.raises(ValueError, match="precision"):
        await client.place_twap("BTC", Side.BUY, 0.000_001, 5)

    assert client._last_nonce == 0
    assert sign_calls == 0
    assert transport.requests == []


async def test_user_signed_action_uses_network_not_custom_exchange_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = RecordingTransport(DEFAULT_RESPONSE)
    client = build_exchange(
        transport,
        network=Network.TESTNET,
        exchange_url="https://provider.example/custom/exchange",
    )
    monkeypatch.setattr(exchange_module, "time_ns", lambda: NONCE * 1_000_000)
    destination = "0x2222222222222222222222222222222222222222"

    await client.usd_transfer(12.349, destination)

    url, envelope = transport.requests[0]
    action = cast(JsonObject, envelope["action"])
    unsigned: JsonObject = {
        "type": "usdSend",
        "amount": "12.34",
        "destination": destination,
        "time": NONCE,
    }
    _, expected_signature = _sign_user_action(
        client._account, unsigned, _USD_SEND_SPEC, Network.TESTNET
    )
    assert url == "https://provider.example/custom/exchange"
    assert action == {
        **unsigned,
        "signatureChainId": "0x66eee",
        "hyperliquidChain": "Testnet",
    }
    assert envelope["signature"] == expected_signature


@pytest.mark.parametrize(
    ("vault_address", "expected_user"),
    [(None, ADDRESS), (VAULT_ADDRESS, VAULT_ADDRESS)],
)
async def test_user_abstraction_uses_constructor_owned_target(
    vault_address: str | None, expected_user: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    transport = RecordingTransport(DEFAULT_RESPONSE)
    client = build_exchange(transport, vault_address=vault_address)
    monkeypatch.setattr(exchange_module, "time_ns", lambda: NONCE * 1_000_000)

    await client.user_dex_abstraction(enabled=True)
    await client.user_set_abstraction(UserAbstraction.UNIFIED_ACCOUNT)

    for _, envelope in transport.requests:
        action = cast(JsonObject, envelope["action"])
        assert action["user"] == expected_user
        assert envelope.get("vaultAddress") == vault_address


async def test_admin_actions_keep_action_fields_flat_and_exact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = RecordingTransport(DEFAULT_RESPONSE)
    client = build_exchange(transport)
    monkeypatch.setattr(exchange_module, "time_ns", lambda: NONCE * 1_000_000)

    await client.schedule_cancel()
    assert transport.requests[-1][1]["action"] == {"type": "scheduleCancel"}

    await client.update_leverage("BTC", 3, is_cross=False)
    assert transport.requests[-1][1]["action"] == {
        "type": "updateLeverage",
        "asset": 0,
        "isCross": False,
        "leverage": 3,
    }

    await client.update_isolated_margin("BTC", -1.15)
    assert transport.requests[-1][1]["action"] == {
        "type": "updateIsolatedMargin",
        "asset": 0,
        "isBuy": True,
        "ntli": -1_150_000,
    }

    agent = "0x3333333333333333333333333333333333333333"
    await client.approve_agent(agent)
    envelope = transport.requests[-1][1]
    wire = cast(JsonObject, envelope["action"])
    signing_action: JsonObject = {
        "type": "approveAgent",
        "agentAddress": agent,
        "agentName": "",
        "nonce": NONCE + 3,
    }
    _, expected_signature = _sign_user_action(
        client._account, signing_action, _APPROVE_AGENT_SPEC, Network.MAINNET
    )
    assert wire == {
        "type": "approveAgent",
        "agentAddress": agent,
        "nonce": NONCE + 3,
        "signatureChainId": "0x66eee",
        "hyperliquidChain": "Mainnet",
    }
    assert envelope["signature"] == expected_signature


async def test_admin_token_and_multisig_payloads_use_wire_precision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = RecordingTransport(DEFAULT_RESPONSE)
    client = build_exchange(transport)
    monkeypatch.setattr(exchange_module, "time_ns", lambda: NONCE * 1_000_000)

    await client.spot_transfer(
        "USOL", 1.234_567, "0x2222222222222222222222222222222222222222"
    )
    action = cast(JsonObject, transport.requests[-1][1]["action"])
    assert action["token"] == "USOL:0x1234"
    assert action["amount"] == "1.23456"

    await client.usd_transfer(1.15, "0x2222222222222222222222222222222222222222")
    action = cast(JsonObject, transport.requests[-1][1]["action"])
    assert action["amount"] == "1.15"

    users = (
        "0xbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
        "0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    )
    await client.convert_to_multi_sig_user(users, 2)
    action = cast(JsonObject, transport.requests[-1][1]["action"])
    assert action["signers"] == (
        '{"authorizedUsers": '
        '["0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", '
        '"0xbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"], '
        '"threshold": 2}'
    )


async def test_close_positions_builds_one_reduce_only_batch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = RecordingTransport(load_exchange_response("order_filled"))
    client = build_exchange(transport)
    info = cast(StubInfo, client._info)
    info.open_positions = [
        cast(Position, {"coin": "BTC", "szi": "0.02"}),
        cast(Position, {"coin": "ETH", "szi": "-0.5"}),
    ]
    monkeypatch.setattr(exchange_module, "time_ns", lambda: NONCE * 1_000_000)

    await client.close_positions(("BTC",))

    assert len(transport.requests) == 1
    action = cast(JsonObject, transport.requests[0][1]["action"])
    encoded = cast(list[JsonObject], action["orders"])
    assert encoded == [
        {
            "a": 0,
            "b": False,
            "p": "95000",
            "s": "0.02",
            "r": True,
            "t": {"limit": {"tif": "Ioc"}},
        }
    ]
