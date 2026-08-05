from copy import deepcopy
import json
from pathlib import Path
from typing import Literal, cast

from eth_account import Account
from eth_account.signers.local import LocalAccount
import pytest

import async_hyperliquid.exchange as exchange_module
from async_hyperliquid import AsyncHyperliquid
from async_hyperliquid._internal.http import _HttpTransport
from async_hyperliquid._internal.metadata import _MarketInfo
from async_hyperliquid._internal.signing import (
    _APPROVE_AGENT_SPEC,
    _USD_SEND_SPEC,
    _sign_user_action,
    sign_exchange_action,
)
from async_hyperliquid.errors import ProtocolError
from async_hyperliquid.exchange import ExchangeClient
from async_hyperliquid.info import InfoClient
from async_hyperliquid.types import (
    AgentAbstraction,
    Builder,
    CancelByCloid,
    CancelOrder,
    Cloid,
    JsonObject,
    JsonValue,
    ModifyOrderRequest,
    Network,
    OrderGrouping,
    PlaceOrderRequest,
    TriggerKind,
    UserAbstraction,
    trigger_order_type,
)
from async_hyperliquid.types.exchange import Signature
from async_hyperliquid.types.info import Position, SpotToken


ADDRESS = "0x1111111111111111111111111111111111111111"
VAULT_ADDRESS = "0x2222222222222222222222222222222222222222"
NONCE = 1_700_000_000_000
FIXTURES = Path(__file__).parents[1] / "contracts" / "fixtures"
DEFAULT_RESPONSE: JsonObject = {"status": "ok", "response": {"type": "default"}}


def order_request(
    coin: str,
    is_buy: bool,
    sz: float,
    px: float,
    *,
    is_market: bool = False,
    ro: bool = False,
    slippage: float = 0.05,
) -> PlaceOrderRequest:
    return {
        "coin": coin,
        "is_buy": is_buy,
        "sz": sz,
        "px": px,
        "is_market": is_market,
        "ro": ro,
        "slippage": slippage,
    }


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
        self.mark_prices = {"BTC": 100_000.0, "ETH": 2_000.0}
        self.open_positions: list[Position] = []
        self.market_info_calls = 0
        self.mark_price_calls: list[str] = []
        self.mid_price_batches: list[tuple[str, ...]] = []
        self.mid_price_calls = 0
        self.position_accounts: list[str] = []

    async def _market_info(self, coin: str) -> _MarketInfo:
        markets = {
            "BTC": _MarketInfo("BTC", 0, 5, False, ""),
            "ETH": _MarketInfo("ETH", 1, 4, False, ""),
            "xyz:NVDA": _MarketInfo("xyz:NVDA", 110_002, 3, False, "xyz"),
            "@182": _MarketInfo("@182", 10_182, 2, True, ""),
        }
        return markets[coin]

    async def _market_infos(self, coins: tuple[str, ...]) -> tuple[_MarketInfo, ...]:
        self.market_info_calls += 1
        return tuple([await self._market_info(coin) for coin in coins])

    async def asset_id(self, coin: str) -> int:
        return (await self._market_info(coin)).asset

    async def mid_price(self, coin: str) -> float:
        self.mid_price_calls += 1
        return self.mids[coin]

    async def mark_price(self, coin: str) -> float:
        self.mark_price_calls.append(coin)
        return self.mark_prices[coin]

    async def _mid_prices(self, markets: tuple[_MarketInfo, ...]) -> tuple[float, ...]:
        coins = tuple(market.coin for market in markets)
        self.mid_price_batches.append(coins)
        return tuple(self.mids[coin] for coin in coins)

    async def positions(
        self, account_address: str, *, dexs: tuple[str, ...] = ("",)
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
        Account.from_key("0x" + "11" * 32),
        account_address=ADDRESS,
        vault_address=vault_address,
        network=network,
        exchange_url=exchange_url,
    )


def build_client(
    transport: RecordingTransport,
    *,
    network: Network = Network.MAINNET,
    exchange_url: str | None = None,
    vault_address: str | None = None,
) -> AsyncHyperliquid:
    client = AsyncHyperliquid(
        ADDRESS,
        "0x" + "11" * 32,
        vault_address=vault_address,
        network=network,
        exchange_url=exchange_url,
    )
    info = StubInfo()
    client._transport = cast(_HttpTransport, transport)
    client._info = cast(InfoClient, info)
    client.exchange._transport = cast(_HttpTransport, transport)
    return client


def test_exchange_client_uses_normal_dependency_construction() -> None:
    transport = RecordingTransport(DEFAULT_RESPONSE)

    client = ExchangeClient(
        cast(_HttpTransport, transport),
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
            Account.from_key("0x" + "11" * 32),
            account_address="invalid",
            vault_address=None,
            network=Network.MAINNET,
        )
    with pytest.raises(ValueError, match="vault_address"):
        ExchangeClient(
            cast(_HttpTransport, transport),
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
    client = build_client(transport)
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
        order_request("BTC", True, 0.01, 100_000),
        order_request("ETH", False, 0.2, 2_000, ro=True),
    )
    builder = Builder("0xABCDEFabcdefABCDEFabcdefABCDEFabcdefABCD", 10)

    response = await client.place_orders(
        orders, grouping=OrderGrouping.NA, builder=builder, expires_after=NONCE + 1_000
    )

    assert response == load_exchange_response("order_resting")
    assert sign_calls == 1
    assert cast(StubInfo, client._info).market_info_calls == 1
    assert len(transport.requests) == 1
    url, envelope = transport.requests[0]
    assert url == Network.MAINNET.exchange_url
    action = cast(JsonObject, envelope["action"])
    assert action["grouping"] == "na"
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
    client = build_client(transport, vault_address=VAULT_ADDRESS)
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

    await client.place_limit_order(order_request("BTC", True, 0.01, 100_000))

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
    assert all(envelope["vaultAddress"] is None for _, envelope in transport.requests)


async def test_vault_target_uses_protocol_specific_transfer_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = RecordingTransport(DEFAULT_RESPONSE)
    client = build_client(transport, vault_address=VAULT_ADDRESS)
    monkeypatch.setattr(exchange_module, "time_ns", lambda: NONCE * 1_000_000)

    await client.exchange.usd_transfer(1.15, ADDRESS)
    assert transport.requests[-1][1]["vaultAddress"] == VAULT_ADDRESS

    await client.exchange.usd_class_transfer(1.15)
    class_transfer = transport.requests[-1][1]
    assert cast(JsonObject, class_transfer["action"])["amount"] == (
        f"1.15 subaccount:{VAULT_ADDRESS}"
    )
    assert class_transfer["vaultAddress"] is None

    await client.send_asset(
        "USOL", 1.15, ADDRESS, source_dex="", destination_dex="spot"
    )
    send_asset = transport.requests[-1][1]
    assert cast(JsonObject, send_asset["action"])["fromSubAccount"] == VAULT_ADDRESS
    assert send_asset["vaultAddress"] is None


async def test_send_asset_cannot_override_constructor_target() -> None:
    transport = RecordingTransport(DEFAULT_RESPONSE)
    client = build_client(transport, vault_address=VAULT_ADDRESS)

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
    client = build_client(
        transport,
        network=Network.TESTNET,
        exchange_url="https://provider.example/exchange",
    )
    info = cast(StubInfo, client._info)
    info.mids["BTC"] = 100.0
    monkeypatch.setattr(exchange_module, "time_ns", lambda: NONCE * 1_000_000)

    await client.place_market_order(
        order_request("BTC", True, 0.1, 0, is_market=True, slippage=0.05)
    )

    _, envelope = transport.requests[0]
    action = cast(JsonObject, envelope["action"])
    encoded = cast(list[JsonObject], action["orders"])[0]
    assert encoded["p"] == "105"
    assert envelope["signature"] == sign_exchange_action(
        client.exchange._account, action, None, NONCE, Network.TESTNET.signature_source
    )


async def test_market_orders_use_one_batched_mid_price_lookup() -> None:
    client = build_client(RecordingTransport(load_exchange_response("order_filled")))
    info = cast(StubInfo, client._info)

    await client.place_orders(
        (
            order_request("BTC", True, 0.01, 0, is_market=True),
            order_request("ETH", False, 0.1, 0, is_market=True),
        )
    )

    assert info.mid_price_batches == [("BTC", "ETH")]
    assert info.mid_price_calls == 0


async def test_cancel_and_modify_commands_encode_without_alias_wrappers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = RecordingTransport(load_exchange_response("cancel_success"))
    client = build_client(transport)
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
    modify: ModifyOrderRequest = {
        "oid": 12,
        "coin": "BTC",
        "is_buy": False,
        "sz": 0.01,
        "px": 101_000,
    }
    await client.modify_orders((modify,))
    modify_action = cast(JsonObject, transport.requests[-1][1]["action"])
    assert modify_action["type"] == "batchModify"

    transport.response = {"status": "ok", "response": {"type": "default"}}
    response = await client.modify_order(modify)
    assert response == transport.response
    modify_action = cast(JsonObject, transport.requests[-1][1]["action"])
    assert modify_action["type"] == "modify"
    assert "modifies" not in modify_action


async def test_singular_cancel_and_trigger_actions_use_their_exact_contracts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = RecordingTransport(load_exchange_response("order_resting"))
    client = build_client(transport)
    monkeypatch.setattr(exchange_module, "time_ns", lambda: NONCE * 1_000_000)
    trigger = order_request("BTC", False, 0.01, 101_000)
    trigger["order_type"] = trigger_order_type(
        is_market=False, trigger_px="101000", tpsl=TriggerKind.TAKE_PROFIT
    )

    await client.place_trigger_order(trigger)
    assert cast(JsonObject, transport.requests[-1][1]["action"])["type"] == "order"

    transport.response = load_exchange_response("cancel_success")
    await client.cancel_order(CancelOrder("BTC", 12))
    assert transport.requests[-1][1]["action"] == {
        "type": "cancel",
        "cancels": [{"a": 0, "o": 12}],
    }

    cloid = Cloid("0x" + "12" * 16)
    await client.cancel_by_cloid(CancelByCloid("BTC", cloid))
    assert transport.requests[-1][1]["action"] == {
        "type": "cancelByCloid",
        "cancels": [{"asset": 0, "cloid": cloid}],
    }


async def test_public_market_batch_uses_one_mid_lookup_and_one_post() -> None:
    transport = RecordingTransport(load_exchange_response("order_filled"))
    client = build_client(transport)
    info = cast(StubInfo, client._info)

    await client.place_orders(
        (
            order_request("BTC", True, 0.01, 0, is_market=True),
            order_request("ETH", False, 0.1, 0, is_market=True),
        )
    )

    assert info.mid_price_batches == [("BTC", "ETH")]
    assert len(transport.requests) == 1


async def test_order_kind_contradictions_fail_before_metadata_lookup() -> None:
    transport = RecordingTransport(load_exchange_response("order_resting"))
    client = build_client(transport)
    info = cast(StubInfo, client._info)
    market = order_request("BTC", True, 0.01, 100_000, is_market=True)
    trigger = order_request("BTC", False, 0.01, 101_000, is_market=True)
    trigger["order_type"] = trigger_order_type(
        is_market=True, trigger_px="101000", tpsl=TriggerKind.TAKE_PROFIT
    )

    with pytest.raises(ValueError, match="is_market=False"):
        await client.place_limit_order(market)
    with pytest.raises(ValueError, match="is_market=False"):
        await client.place_trigger_order(trigger)
    assert info.market_info_calls == 0
    assert transport.requests == []


async def test_twap_methods_accept_their_exact_response_kinds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = RecordingTransport(load_exchange_response("twap_order_running"))
    client = build_client(transport)
    monkeypatch.setattr(exchange_module, "time_ns", lambda: NONCE * 1_000_000)

    placed = await client.place_twap("BTC", True, 0.01, 5)

    assert placed == load_exchange_response("twap_order_running")
    action = cast(JsonObject, transport.requests[0][1]["action"])
    assert "details" not in action
    assert cast(StubInfo, client._info).mark_price_calls == []
    transport.response = load_exchange_response("twap_cancel_success")

    cancelled = await client.cancel_twap("BTC", 77738308)

    assert cancelled == load_exchange_response("twap_cancel_success")


@pytest.mark.parametrize(
    ("trigger_px", "stop_px", "expected_details", "expected_mark_calls"),
    [
        (63_000.0, 65_000.0, {"t": {"p": "63000", "a": False}, "s": "65000"}, ["BTC"]),
        (101_000.0, None, {"t": {"p": "101000", "a": True}, "s": None}, ["BTC"]),
        (100_000.0, None, {"t": {"p": "100000", "a": False}, "s": None}, ["BTC"]),
        (None, 99_000.0, {"t": None, "s": "99000"}, []),
    ],
)
async def test_twap_advanced_prices_encode_exact_details(
    monkeypatch: pytest.MonkeyPatch,
    trigger_px: float | None,
    stop_px: float | None,
    expected_details: JsonObject,
    expected_mark_calls: list[str],
) -> None:
    transport = RecordingTransport(load_exchange_response("twap_order_running"))
    client = build_client(transport)
    monkeypatch.setattr(exchange_module, "time_ns", lambda: NONCE * 1_000_000)

    await client.place_twap(
        "BTC", True, 0.01, 5, trigger_px=trigger_px, stop_px=stop_px
    )

    action = cast(JsonObject, transport.requests[0][1]["action"])
    assert action == {
        "type": "twapOrder",
        "twap": {"a": 0, "b": True, "s": "0.01", "r": False, "m": 5, "t": False},
        "details": expected_details,
    }
    details = cast(JsonObject, action["details"])
    assert tuple(details) == ("t", "s")
    trigger = details["t"]
    if trigger is not None:
        assert tuple(cast(JsonObject, trigger)) == ("p", "a")
    assert cast(StubInfo, client._info).mark_price_calls == expected_mark_calls


@pytest.mark.parametrize(
    ("trigger_px", "stop_px"),
    [
        (float("nan"), None),
        (-1.0, None),
        (0.01, None),
        (None, float("inf")),
        (None, -1.0),
        (None, 0.01),
    ],
)
async def test_twap_invalid_advanced_price_fails_before_signing(
    trigger_px: float | None, stop_px: float | None
) -> None:
    transport = RecordingTransport(load_exchange_response("twap_order_running"))
    client = build_client(transport)

    with pytest.raises(ValueError):
        await client.place_twap(
            "BTC", True, 0.01, 5, trigger_px=trigger_px, stop_px=stop_px
        )

    assert client.exchange._last_nonce == 0
    assert cast(StubInfo, client._info).mark_price_calls == []
    assert transport.requests == []


async def test_twap_mark_price_failure_prevents_signing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = RecordingTransport(load_exchange_response("twap_order_running"))
    client = build_client(transport)

    async def fail_mark_price(_coin: str) -> float:
        raise ProtocolError("mark unavailable")

    monkeypatch.setattr(client._info, "mark_price", fail_mark_price)

    with pytest.raises(ProtocolError, match="mark unavailable"):
        await client.place_twap("BTC", True, 0.01, 5, trigger_px=100_000.0)

    assert client.exchange._last_nonce == 0
    assert transport.requests == []


@pytest.mark.parametrize("mark_px", [float("nan"), float("inf"), 0.0, -1.0])
async def test_twap_invalid_mark_price_prevents_signing(mark_px: float) -> None:
    transport = RecordingTransport(load_exchange_response("twap_order_running"))
    client = build_client(transport)
    info = cast(StubInfo, client._info)
    info.mark_prices["BTC"] = mark_px

    with pytest.raises(ProtocolError, match="mark price"):
        await client.place_twap("BTC", True, 0.01, 5, trigger_px=100_000.0)

    assert client.exchange._last_nonce == 0
    assert transport.requests == []


async def test_twap_below_market_precision_fails_before_signing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = RecordingTransport(load_exchange_response("twap_order_running"))
    client = build_client(transport)
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

    with pytest.raises(ValueError, match="order size is below market precision"):
        await client.place_twap("BTC", True, 0.000_001, 5)

    assert client.exchange._last_nonce == 0
    assert sign_calls == 0
    assert transport.requests == []


async def test_spot_twap_rejects_reduce_only_before_signing() -> None:
    transport = RecordingTransport(load_exchange_response("twap_order_running"))
    client = build_client(transport)

    with pytest.raises(ValueError, match="spot orders cannot be reduce-only"):
        await client.place_twap("@182", False, 0.01, 5, reduce_only=True)

    assert client.exchange._last_nonce == 0
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
    client = build_client(transport)
    monkeypatch.setattr(exchange_module, "time_ns", lambda: NONCE * 1_000_000)

    await client.exchange.schedule_cancel()
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
    await client.exchange.approve_agent(agent)
    envelope = transport.requests[-1][1]
    wire = cast(JsonObject, envelope["action"])
    signing_action: JsonObject = {
        "type": "approveAgent",
        "agentAddress": agent,
        "agentName": "",
        "nonce": NONCE + 3,
    }
    _, expected_signature = _sign_user_action(
        client.exchange._account, signing_action, _APPROVE_AGENT_SPEC, Network.MAINNET
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
    client = build_client(transport)
    monkeypatch.setattr(exchange_module, "time_ns", lambda: NONCE * 1_000_000)

    await client.spot_transfer(
        "USOL", 1.234_567, "0x2222222222222222222222222222222222222222"
    )
    action = cast(JsonObject, transport.requests[-1][1]["action"])
    assert action["token"] == "USOL:0x1234"
    assert action["amount"] == "1.23456"

    await client.exchange.usd_transfer(
        1.15, "0x2222222222222222222222222222222222222222"
    )
    action = cast(JsonObject, transport.requests[-1][1]["action"])
    assert action["amount"] == "1.15"

    await client.exchange.withdraw(1.15, destination=ADDRESS)
    action = cast(JsonObject, transport.requests[-1][1]["action"])
    assert action["type"] == "withdraw3"
    assert action["destination"] == ADDRESS

    await client.exchange.staking_deposit(0.01)
    assert cast(JsonObject, transport.requests[-1][1]["action"])["type"] == "cDeposit"

    await client.exchange.staking_withdraw(0.01)
    assert cast(JsonObject, transport.requests[-1][1]["action"])["type"] == "cWithdraw"

    await client.exchange.token_delegate(ADDRESS, 0.01)
    assert cast(JsonObject, transport.requests[-1][1]["action"])["type"] == (
        "tokenDelegate"
    )

    users = (
        "0xbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
        "0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    )
    await client.exchange.convert_to_multi_sig_user(users, 2)
    action = cast(JsonObject, transport.requests[-1][1]["action"])
    assert action["signers"] == (
        '{"authorizedUsers": '
        '["0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", '
        '"0xbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"], '
        '"threshold": 2}'
    )


async def test_authorization_actions_keep_the_documented_wire_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = RecordingTransport(DEFAULT_RESPONSE)
    client = build_exchange(transport)
    monkeypatch.setattr(exchange_module, "time_ns", lambda: NONCE * 1_000_000)

    await client.approve_builder_fee(ADDRESS, 0.000_01)
    await client.agent_enable_dex_abstraction()
    await client.agent_set_abstraction(AgentAbstraction.UNIFIED_ACCOUNT)

    assert [request[1]["action"] for request in transport.requests] == [
        {
            "type": "approveBuilderFee",
            "maxFeeRate": "0.001%",
            "builder": ADDRESS,
            "nonce": NONCE,
            "signatureChainId": "0x66eee",
            "hyperliquidChain": "Mainnet",
        },
        {"type": "agentEnableDexAbstraction"},
        {"type": "agentSetAbstraction", "abstraction": "u"},
    ]


async def test_agent_send_asset_reuses_the_envelope_nonce(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = RecordingTransport(DEFAULT_RESPONSE)
    client = build_client(transport, vault_address=VAULT_ADDRESS)
    monkeypatch.setattr(exchange_module, "time_ns", lambda: NONCE * 1_000_000)

    await client.agent_send_asset(
        "USOL",
        1.234_567,
        ADDRESS,
        source_dex="spot",
        destination_dex="xyz",
        expires_after=NONCE + 1_000,
    )

    envelope = transport.requests[-1][1]
    assert envelope["action"] == {
        "type": "agentSendAsset",
        "destination": ADDRESS,
        "sourceDex": "spot",
        "destinationDex": "xyz",
        "token": "USOL:0x1234",
        "amount": "1.23456",
        "fromSubAccount": VAULT_ADDRESS,
        "nonce": NONCE,
    }
    assert envelope["nonce"] == NONCE
    assert envelope["vaultAddress"] == VAULT_ADDRESS
    assert envelope["expiresAfter"] == NONCE + 1_000


async def test_send_to_evm_with_data_uses_the_documented_typed_action(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = RecordingTransport(DEFAULT_RESPONSE)
    client = build_client(transport, network=Network.TESTNET)
    monkeypatch.setattr(exchange_module, "time_ns", lambda: NONCE * 1_000_000)

    await client.send_to_evm_with_data(
        "USOL",
        1.234_567,
        ADDRESS,
        source_dex="spot",
        address_encoding="hex",
        destination_chain_id=42161,
        gas_limit=200_000,
        data="0x1234",
    )

    envelope = transport.requests[-1][1]
    assert envelope["action"] == {
        "type": "sendToEvmWithData",
        "token": "USOL:0x1234",
        "amount": "1.23456",
        "sourceDex": "spot",
        "destinationRecipient": ADDRESS,
        "addressEncoding": "hex",
        "destinationChainId": 42161,
        "gasLimit": 200_000,
        "data": "0x1234",
        "nonce": NONCE,
        "signatureChainId": "0x66eee",
        "hyperliquidChain": "Testnet",
    }
    assert envelope["nonce"] == NONCE


async def test_l1_transfer_and_outcome_actions_match_the_wire_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = RecordingTransport(DEFAULT_RESPONSE)
    client = build_exchange(transport)
    monkeypatch.setattr(exchange_module, "time_ns", lambda: NONCE * 1_000_000)

    await client.hip3_liquidator_transfer("xyz", 1_000, is_deposit=True)
    await client.split_outcome(1, 10)
    await client.merge_outcome(2)
    await client.merge_question(3, 5.25)
    await client.negate_outcome(3, 2, 1.5)

    assert [request[1]["action"] for request in transport.requests] == [
        {
            "type": "hip3LiquidatorTransfer",
            "dex": "xyz",
            "ntl": 1_000_000_000,
            "isDeposit": True,
        },
        {"type": "userOutcome", "splitOutcome": {"outcome": 1, "amount": "10"}},
        {"type": "userOutcome", "mergeOutcome": {"outcome": 2, "amount": None}},
        {"type": "userOutcome", "mergeQuestion": {"question": 3, "amount": "5.25"}},
        {
            "type": "userOutcome",
            "negateOutcome": {"question": 3, "outcome": 2, "amount": "1.5"},
        },
    ]


async def test_small_admin_actions_stay_flat_and_preserve_explicit_noop_nonce(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = RecordingTransport(DEFAULT_RESPONSE)
    client = build_exchange(transport)
    monkeypatch.setattr(exchange_module, "time_ns", lambda: NONCE * 1_000_000)

    await client.noop(NONCE - 1)
    await client.vote_risk_free_rate(0.04)
    await client.authorize_aqav2_role(42, "technical")
    await client.claim_rewards()

    assert transport.requests[0][1]["nonce"] == NONCE - 1
    assert [request[1]["action"] for request in transport.requests] == [
        {"type": "noop"},
        {"type": "validatorL1Stream", "riskFreeRate": "0.04"},
        {"type": "authorizeAqav2Role", "token": 42, "role": "technical"},
        {"type": "claimRewards"},
    ]


@pytest.mark.parametrize("amount", [999, 1_000.000_001])
async def test_hip3_liquidator_transfer_rejects_invalid_notional(amount: float) -> None:
    transport = RecordingTransport(DEFAULT_RESPONSE)
    client = build_exchange(transport)

    with pytest.raises(ValueError, match="multiple of 1000"):
        await client.hip3_liquidator_transfer("xyz", amount)

    assert transport.requests == []
