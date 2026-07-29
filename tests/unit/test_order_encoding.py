from copy import deepcopy

from eth_account import Account
from hyperliquid.utils.signing import action_hash as sdk_action_hash
from hyperliquid.utils.signing import sign_l1_action as sdk_sign_l1_action
import pytest

from async_hyperliquid._signing import (
    _USD_SEND_SPEC,
    _sign_user_action,
    encode_order,
    hash_action,
    sign_exchange_action,
)
from async_hyperliquid.types import (
    Cloid,
    JsonObject,
    LimitOrder,
    Network,
    Side,
    TimeInForce,
    TriggerKind,
    TriggerOrder,
)


NONCE = 1_700_000_000_000
ORDER_ACTION: JsonObject = {
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


def test_hash_action_matches_the_0_5_1_wheel_vectors() -> None:
    assert (
        hash_action(ORDER_ACTION, None, NONCE).hex()
        == "236183de2a0f86e0652b5f845213df4238e21bb5b0649e2be407d0349023d85e"
    )
    assert (
        hash_action(
            ORDER_ACTION,
            "0x2222222222222222222222222222222222222222",
            NONCE,
            NONCE + 1_000,
        ).hex()
        == "ac7a05a6b690e412b937be1bc2808a9ff152ea7d7658bbb8219ee3a37b4450f2"
    )


def test_exchange_signatures_match_both_0_5_1_network_vectors() -> None:
    wallet = Account.from_key("0x" + "11" * 32)

    assert sign_exchange_action(wallet, ORDER_ACTION, None, NONCE, "a") == {
        "r": "0xee5a0bc0779dffe0f2dd5c599646727e1c8bc61997f1681cd96483f852c22403",
        "s": "0x51e2e2e5b180bd3d9de19b07ad06da3c7679779021717f6ed482a1e96669205b",
        "v": 28,
    }
    assert sign_exchange_action(wallet, ORDER_ACTION, None, NONCE, "b") == {
        "r": "0xc85e55c3f4e502977cf70f67d0a2f8bd81bcb26aee35a2b9177cf80ccc99aad3",
        "s": "0x26ca51a08fb60df7ee0117deffc34e2fe8caa80561dd4e90e524c9d75afd0e65",
        "v": 27,
    }


def test_hashes_and_signatures_match_the_official_sdk_oracle() -> None:
    wallet = Account.from_key("0x" + "11" * 32)
    vault_address = "0x2222222222222222222222222222222222222222"
    expires_after = NONCE + 1_000

    assert hash_action(ORDER_ACTION, None, NONCE) == sdk_action_hash(
        ORDER_ACTION, None, NONCE, None
    )
    assert hash_action(
        ORDER_ACTION, vault_address, NONCE, expires_after
    ) == sdk_action_hash(ORDER_ACTION, vault_address, NONCE, expires_after)
    assert sign_exchange_action(
        wallet, ORDER_ACTION, None, NONCE, Network.MAINNET.signature_source
    ) == sdk_sign_l1_action(wallet, ORDER_ACTION, None, NONCE, None, True)
    assert sign_exchange_action(
        wallet, ORDER_ACTION, None, NONCE, Network.TESTNET.signature_source
    ) == sdk_sign_l1_action(wallet, ORDER_ACTION, None, NONCE, None, False)


def test_user_signed_action_matches_0_5_1_without_mutating_input() -> None:
    wallet = Account.from_key("0x" + "11" * 32)
    action: JsonObject = {
        "type": "usdSend",
        "amount": "12.34",
        "destination": "0x1234567890123456789012345678901234567890",
        "time": NONCE,
    }
    original = deepcopy(action)

    wire_action, signature = _sign_user_action(
        wallet, action, _USD_SEND_SPEC, Network.MAINNET
    )

    assert action == original
    assert wire_action == {
        **original,
        "signatureChainId": "0x66eee",
        "hyperliquidChain": "Mainnet",
    }
    assert signature == {
        "r": "0x6de7743bfa835b599baa4017ffd6e0ea52c866272c5a79485762dd1946af9146",
        "s": "0x540f3b338f885d1c65007a408de8c17de622cfde54342ea7e062d0fb1fa544e3",
        "v": 28,
    }


def test_limit_order_encoding_is_exact_and_does_not_mutate_command() -> None:
    cloid = Cloid("0x" + "12" * 16)
    order = LimitOrder(
        "BTC",
        Side.BUY,
        0.010_000_000_01,
        100_000.4,
        TimeInForce.ALO,
        client_order_id=cloid,
    )

    encoded = encode_order(order, asset=0, size_decimals=5)

    assert encoded == {
        "a": 0,
        "b": True,
        "p": "100000",
        "s": "0.01",
        "r": False,
        "t": {"limit": {"tif": "Alo"}},
        "c": str(cloid),
    }
    assert order.size == 0.010_000_000_01
    assert order.price == 100_000.4


@pytest.mark.parametrize(
    "order",
    [
        LimitOrder("BTC", Side.BUY, 0.000_001, 100_000),
        LimitOrder("BTC", Side.BUY, 0.01, 0.01),
    ],
)
def test_order_encoding_rejects_values_below_market_precision(
    order: LimitOrder,
) -> None:
    with pytest.raises(ValueError, match="market precision"):
        encode_order(order, asset=0, size_decimals=5)


def test_trigger_order_encoding_preserves_trigger_contract() -> None:
    order = TriggerOrder(
        "xyz:NVDA",
        Side.SELL,
        0.1254,
        177.064,
        180.125,
        TriggerKind.STOP_LOSS,
        is_market=True,
        reduce_only=True,
    )

    assert encode_order(order, asset=110_002, size_decimals=3) == {
        "a": 110_002,
        "b": False,
        "p": "177.06",
        "s": "0.125",
        "r": True,
        "t": {"trigger": {"isMarket": True, "triggerPx": "180.125", "tpsl": "sl"}},
    }
