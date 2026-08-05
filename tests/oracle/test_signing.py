from copy import deepcopy
import os
from pathlib import Path
from typing import cast

from dotenv import dotenv_values
from eth_account import Account
from eth_account.signers.local import LocalAccount
from eth_utils import is_address, is_same_address, to_normalized_address
from hyperliquid.exchange import Exchange as SdkExchange
from hyperliquid.utils.constants import TESTNET_API_URL
from hyperliquid.utils.signing import sign_l1_action as sdk_sign_l1_action
from hyperliquid.utils.signing import OrderRequest as SdkOrderRequest
import pytest

import async_hyperliquid.exchange as exchange_module
from async_hyperliquid import AsyncHyperliquid
from async_hyperliquid._internal.http import _HttpTransport
from async_hyperliquid._internal.metadata import _MarketInfo
from async_hyperliquid.exchange import ExchangeClient
from async_hyperliquid.info import InfoClient
from async_hyperliquid.types import (
    JsonObject,
    JsonValue,
    Network,
    PlaceOrderRequest,
    TimeInForce,
    TriggerKind,
    limit_order_type,
    trigger_order_type,
)
from async_hyperliquid.types.exchange import OrderAction, Signature


NONCE = 1_750_000_000_000
TEST_KEY = "0x" + "11" * 32
VAULT_ADDRESS = "0x2222222222222222222222222222222222222222"
ORDER_ACTION: OrderAction = {
    "type": "order",
    "orders": [
        {
            "a": 0,
            "b": True,
            "p": "100000",
            "s": "0.01",
            "r": False,
            "t": {"limit": {"tif": "Gtc"}},
        }
    ],
    "grouping": "na",
}
BATCH_ORDER_ACTION: OrderAction = {
    "type": "order",
    "orders": [
        {
            "a": asset,
            "b": True,
            "p": "100000",
            "s": "0.01",
            "r": False,
            "t": {"limit": {"tif": "Gtc"}},
        }
        for asset in range(10)
    ],
    "grouping": "na",
}
EXPECTED_SIGNATURES: dict[tuple[bool, bool], Signature] = {
    (False, False): {
        "r": "0x78e220566a337906ef346c4047d45b27446058978f84e7a944311a33ed58e98a",
        "s": "0x71715923504615a8452afd9744c613dfdb0e8ff6af925e3c134255891d05eff8",
        "v": 28,
    },
    (False, True): {
        "r": "0x89692511b4358e3aa7e44aae50724575798b2a276f3a9046a5336a7a3962dbd4",
        "s": "0x5c3ff75d23a193115825d9102060e1227f14454e5d59af669a50e1fdb1b0eabd",
        "v": 27,
    },
    (True, False): {
        "r": "0xd4961f3ab0f52168b33a570edaf45475b59ec449004290437aab806156bd08f6",
        "s": "0x35999891a61433b22bc100154001551de9d6819ec6df03c31cbc51c44f9dbfd1",
        "v": 27,
    },
    (True, True): {
        "r": "0xb5f1149fdbd1b360c9b88cb91e2ba9eb26df101dfe7ef49487ea80457ee58db",
        "s": "0x77c11babfac735d6426decd9c539cb981c9c74a789e807e39d652545fcd08f2e",
        "v": 28,
    },
}
ORDER_RESPONSE: JsonObject = {
    "status": "ok",
    "response": {"type": "order", "data": {"statuses": [{"resting": {"oid": 1}}]}},
}


class RecordingTransport:
    def __init__(self) -> None:
        self.payload: JsonObject | None = None

    async def post_json(self, url: str, payload: JsonObject) -> JsonValue:
        self.payload = deepcopy(payload)
        return deepcopy(ORDER_RESPONSE)


class SdkInfo:
    def name_to_asset(self, coin: str) -> int:
        return int(coin.removeprefix("ASSET-"))


class AsyncInfo:
    async def _market_infos(self, coins: tuple[str, ...]) -> tuple[_MarketInfo, ...]:
        return tuple(
            _MarketInfo(
                coin=coin,
                asset=int(coin.removeprefix("ASSET-")),
                size_decimals=5,
                is_spot=False,
                dex="",
            )
            for coin in coins
        )


def _sdk_payload(
    account: LocalAccount,
    action: OrderAction,
    *,
    nonce: int,
    vault_address: str | None,
    expires_after: int | None,
    monkeypatch: pytest.MonkeyPatch,
) -> JsonObject:
    client = object.__new__(SdkExchange)
    client.vault_address = vault_address
    client.expires_after = expires_after
    captured: JsonObject | None = None

    def capture(path: str, payload: JsonObject) -> JsonObject:
        nonlocal captured
        if path != "/exchange":
            raise AssertionError("official SDK posted to an unexpected path")
        captured = deepcopy(payload)
        return payload

    client.post = capture
    monkeypatch.setattr("hyperliquid.exchange.logging.debug", lambda *args: None)
    signature = sdk_sign_l1_action(
        account, deepcopy(action), vault_address, nonce, expires_after, False
    )
    client._post_action(deepcopy(action), signature, nonce)
    if captured is None:
        raise AssertionError("official SDK did not build an Exchange payload")
    return captured


async def _async_payload(
    account: LocalAccount,
    action: OrderAction,
    *,
    nonce: int,
    vault_address: str | None,
    expires_after: int | None,
) -> JsonObject:
    transport = RecordingTransport()
    client = ExchangeClient(
        cast(_HttpTransport, transport),
        account,
        account_address=account.address,
        vault_address=vault_address,
        network=Network.TESTNET,
    )
    await client._submit_action(
        deepcopy(action), "order", expires_after=expires_after, nonce=nonce
    )
    if transport.payload is None:
        raise AssertionError("async-hyperliquid did not build an Exchange payload")
    return transport.payload


def _sdk_order_payload(
    account: LocalAccount,
    orders: list[SdkOrderRequest],
    *,
    account_address: str,
    vault_address: str | None,
    expires_after: int | None,
    monkeypatch: pytest.MonkeyPatch,
) -> JsonObject:
    client = object.__new__(SdkExchange)
    client.wallet = account
    client.account_address = account_address
    client.vault_address = vault_address
    client.expires_after = expires_after
    client.base_url = TESTNET_API_URL
    client.info = SdkInfo()
    captured: JsonObject | None = None

    def capture(path: str, payload: JsonObject) -> JsonObject:
        nonlocal captured
        if path != "/exchange":
            raise AssertionError("official SDK posted to an unexpected path")
        captured = deepcopy(payload)
        return payload

    client.post = capture
    monkeypatch.setattr("hyperliquid.exchange.logging.debug", lambda *args: None)
    monkeypatch.setattr("hyperliquid.exchange.get_timestamp_ms", lambda: NONCE)
    client.bulk_orders(orders)
    if captured is None:
        raise AssertionError("official SDK did not build an order payload")
    return captured


async def _async_order_payload(
    account_address: str,
    signing_key: str,
    orders: tuple[PlaceOrderRequest, ...],
    *,
    vault_address: str | None,
    expires_after: int | None,
    monkeypatch: pytest.MonkeyPatch,
) -> JsonObject:
    transport = RecordingTransport()
    client = AsyncHyperliquid(
        account_address,
        signing_key,
        vault_address=vault_address,
        network=Network.TESTNET,
    )
    client._transport = cast(_HttpTransport, transport)
    client._info = cast(InfoClient, AsyncInfo())
    client.exchange._transport = cast(_HttpTransport, transport)
    monkeypatch.setattr(exchange_module, "time_ns", lambda: NONCE * 1_000_000)

    await client.place_orders(orders, expires_after=expires_after)
    if transport.payload is None:
        raise AssertionError("async-hyperliquid did not build an order payload")
    return transport.payload


@pytest.mark.parametrize(
    ("action", "vault_address", "expires_after", "expected_signature"),
    [
        (ORDER_ACTION, None, None, EXPECTED_SIGNATURES[(False, False)]),
        (
            ORDER_ACTION,
            VAULT_ADDRESS,
            NONCE + 1_000,
            EXPECTED_SIGNATURES[(False, True)],
        ),
        (BATCH_ORDER_ACTION, None, None, EXPECTED_SIGNATURES[(True, False)]),
        (
            BATCH_ORDER_ACTION,
            VAULT_ADDRESS,
            NONCE + 1_000,
            EXPECTED_SIGNATURES[(True, True)],
        ),
    ],
)
async def test_order_payload_matches_official_sdk_exactly(
    action: OrderAction,
    vault_address: str | None,
    expires_after: int | None,
    expected_signature: Signature,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    account = Account.from_key(TEST_KEY)

    expected = _sdk_payload(
        account,
        action,
        nonce=NONCE,
        vault_address=vault_address,
        expires_after=expires_after,
        monkeypatch=monkeypatch,
    )
    actual = await _async_payload(
        account,
        action,
        nonce=NONCE,
        vault_address=vault_address,
        expires_after=expires_after,
    )

    vector = cast(
        JsonObject,
        {
            "action": action,
            "nonce": NONCE,
            "signature": expected_signature,
            "vaultAddress": vault_address,
            "expiresAfter": expires_after,
        },
    )
    if expected != vector:
        raise AssertionError("official SDK payload differs from committed vector")
    if actual != expected:
        raise AssertionError("async-hyperliquid payload differs from official SDK")


@pytest.mark.parametrize(
    ("order_count", "vault_address", "expires_after"),
    [(1, None, None), (10, VAULT_ADDRESS, NONCE + 1_000)],
)
async def test_native_order_builders_produce_the_same_final_payload(
    order_count: int,
    vault_address: str | None,
    expires_after: int | None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    account = Account.from_key(TEST_KEY)
    sdk_orders: list[SdkOrderRequest] = [
        {
            "coin": f"ASSET-{asset}",
            "is_buy": True,
            "sz": 0.01,
            "limit_px": 100_000.0,
            "order_type": {"limit": {"tif": "Gtc"}},
            "reduce_only": False,
        }
        for asset in range(order_count)
    ]
    async_orders: tuple[PlaceOrderRequest, ...] = tuple(
        cast(
            PlaceOrderRequest,
            {
                "coin": f"ASSET-{asset}",
                "is_buy": True,
                "sz": 0.01,
                "px": 100_000.0,
                "is_market": False,
                "ro": False,
                "order_type": limit_order_type(TimeInForce.GTC),
            },
        )
        for asset in range(order_count)
    )

    expected = _sdk_order_payload(
        account,
        sdk_orders,
        account_address=account.address,
        vault_address=vault_address,
        expires_after=expires_after,
        monkeypatch=monkeypatch,
    )
    actual = await _async_order_payload(
        account.address,
        TEST_KEY,
        async_orders,
        vault_address=vault_address,
        expires_after=expires_after,
        monkeypatch=monkeypatch,
    )

    if actual != expected:
        raise AssertionError(
            "native async-hyperliquid order payload differs from official SDK"
        )


async def test_trigger_order_payload_matches_official_sdk_exactly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    account = Account.from_key(TEST_KEY)
    sdk_order: SdkOrderRequest = {
        "coin": "ASSET-0",
        "is_buy": False,
        "sz": 0.01,
        "limit_px": 10_001.0,
        "order_type": {
            "trigger": {"triggerPx": 200_000.0, "isMarket": False, "tpsl": "tp"}
        },
        "reduce_only": False,
    }
    async_order: PlaceOrderRequest = {
        "coin": "ASSET-0",
        "is_buy": False,
        "sz": 0.01,
        "px": 10_001.0,
        "is_market": False,
        "order_type": trigger_order_type(
            is_market=False, trigger_px="200000.0", tpsl=TriggerKind.TAKE_PROFIT
        ),
    }

    expected = _sdk_order_payload(
        account,
        [sdk_order],
        account_address=account.address,
        vault_address=VAULT_ADDRESS,
        expires_after=None,
        monkeypatch=monkeypatch,
    )
    actual = await _async_order_payload(
        account.address,
        TEST_KEY,
        (async_order,),
        vault_address=VAULT_ADDRESS,
        expires_after=None,
        monkeypatch=monkeypatch,
    )

    assert actual == expected


def _local_value(name: str) -> str | None:
    configured = os.environ.get(name)
    if configured:
        return configured
    value = dotenv_values(Path(".env.local")).get(name)
    return value if isinstance(value, str) and value else None


def _local_account(private_key_name: str, address_name: str) -> LocalAccount:
    private_key = _local_value(private_key_name)
    address = _local_value(address_name)
    if not private_key or not address:
        raise pytest.skip.Exception(
            f"{private_key_name} and {address_name} are required"
        )
    try:
        account = Account.from_key(private_key)
    except (TypeError, ValueError):
        raise AssertionError(f"{private_key_name} is not a valid private key") from None
    if not is_address(address) or not is_same_address(account.address, address):
        raise AssertionError(f"{private_key_name} does not match {address_name}")
    return account


def _normalize_distinct_root_addresses(
    master_address: str, subaccount_address: str
) -> tuple[str, str]:
    if not is_address(master_address) or not is_address(subaccount_address):
        raise AssertionError("HL_ADDR and HL_SUB must be Ethereum addresses")
    normalized_master = to_normalized_address(master_address)
    normalized_subaccount = to_normalized_address(subaccount_address)
    if is_same_address(normalized_master, normalized_subaccount):
        raise AssertionError("root addresses must be different")
    return normalized_master, normalized_subaccount


def test_root_addresses_normalize_mixed_case() -> None:
    normalized = _normalize_distinct_root_addresses("0x" + "aB" * 20, "0x" + "Cd" * 20)

    if normalized != ("0x" + "ab" * 20, "0x" + "cd" * 20):
        raise AssertionError("root addresses were not normalized")


def test_root_addresses_reject_semantically_identical_values() -> None:
    with pytest.raises(AssertionError, match="must be different"):
        _normalize_distinct_root_addresses("0x" + "ab" * 20, "0x" + "AB" * 20)


async def test_subaccount_account_address_payload_matches_official_sdk_without_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    signing_key = _local_value("HL_SK")
    api_address = _local_value("HL_AK")
    master_address = _local_value("HL_ADDR")
    subaccount_address = _local_value("HL_SUB")
    if (
        not signing_key
        or not api_address
        or not master_address
        or not subaccount_address
    ):
        raise pytest.skip.Exception("HL_SK, HL_AK, HL_ADDR, and HL_SUB are required")

    try:
        account = Account.from_key(signing_key)
    except (TypeError, ValueError):
        raise AssertionError("HL_SK is not a valid private key") from None
    if not is_address(api_address) or not is_same_address(account.address, api_address):
        raise AssertionError("HL_SK does not match HL_AK")
    master_address, subaccount_address = _normalize_distinct_root_addresses(
        master_address, subaccount_address
    )

    sdk_orders: list[SdkOrderRequest] = [
        {
            "coin": "ASSET-0",
            "is_buy": True,
            "sz": 0.01,
            "limit_px": 100_000.0,
            "order_type": {"limit": {"tif": "Gtc"}},
            "reduce_only": False,
        }
    ]
    async_orders: tuple[PlaceOrderRequest, ...] = (
        {
            "coin": "ASSET-0",
            "is_buy": True,
            "sz": 0.01,
            "px": 100_000.0,
            "is_market": False,
            "ro": False,
            "order_type": limit_order_type(TimeInForce.GTC),
        },
    )
    sdk_payloads: list[JsonObject] = []
    async_payloads: list[JsonObject] = []

    for account_address in (master_address, subaccount_address):
        sdk_payloads.append(
            _sdk_order_payload(
                account,
                sdk_orders,
                account_address=account_address,
                vault_address=subaccount_address,
                expires_after=None,
                monkeypatch=monkeypatch,
            )
        )
        async_payloads.append(
            await _async_order_payload(
                account_address,
                signing_key,
                async_orders,
                vault_address=subaccount_address,
                expires_after=None,
                monkeypatch=monkeypatch,
            )
        )

    if async_payloads != sdk_payloads:
        raise AssertionError("async payloads differ from official SDK payloads")
    if async_payloads[0] != async_payloads[1]:
        raise AssertionError("master-root and subaccount-root payloads differ")
    if not all(
        payload.get("vaultAddress") == subaccount_address for payload in async_payloads
    ):
        raise AssertionError("payload vault address differs from HL_SUB")


@pytest.mark.parametrize(
    ("private_key_name", "address_name", "action", "use_subaccount", "expires_after"),
    [
        ("HL_PK", "HL_ADDR", ORDER_ACTION, False, None),
        ("HL_SK", "HL_AK", BATCH_ORDER_ACTION, True, NONCE + 2_000),
    ],
)
async def test_local_credentials_match_official_sdk_payload_without_network(
    private_key_name: str,
    address_name: str,
    action: OrderAction,
    use_subaccount: bool,
    expires_after: int | None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    account = _local_account(private_key_name, address_name)
    vault_address = _local_value("HL_SUB") if use_subaccount else None
    if use_subaccount and (vault_address is None or not is_address(vault_address)):
        raise pytest.skip.Exception(
            "HL_SUB is required and must be an Ethereum address"
        )

    expected = _sdk_payload(
        account,
        action,
        nonce=NONCE + 1,
        vault_address=vault_address,
        expires_after=expires_after,
        monkeypatch=monkeypatch,
    )
    actual = await _async_payload(
        account,
        action,
        nonce=NONCE + 1,
        vault_address=vault_address,
        expires_after=expires_after,
    )

    if actual != expected:
        raise AssertionError(f"{private_key_name} payload differs from official SDK")
