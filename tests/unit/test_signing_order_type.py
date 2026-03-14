import pytest
from eth_account import Account
from eth_account.messages import encode_typed_data
from eth_utils.conversions import to_hex

from async_hyperliquid.utils.constants import SIGNATURE_CHAIN_ID, USD_SEND_SIGN_TYPES
from async_hyperliquid.utils.signing import (
    ensure_order_type,
    hash_action,
    sign_action,
    sign_user_signed_action,
    user_signed_payload,
)


def test_ensure_order_type_rejects_malformed_dual_variant() -> None:
    malformed = {
        "limit": {"tif": "Ioc"},
        "trigger": {"isMarket": False, "triggerPx": "100", "tpsl": "tp"},
    }
    with pytest.raises(ValueError, match="Invalid order type"):
        ensure_order_type(malformed)  # type: ignore[arg-type]


def test_user_signed_payload_reuses_static_templates() -> None:
    action_one = {"signatureChainId": SIGNATURE_CHAIN_ID, "nonce": 1}
    action_two = {"signatureChainId": SIGNATURE_CHAIN_ID, "nonce": 2}

    payload_one = user_signed_payload(
        "HyperliquidTransaction:UsdSend", USD_SEND_SIGN_TYPES, action_one
    )
    payload_two = user_signed_payload(
        "HyperliquidTransaction:UsdSend", USD_SEND_SIGN_TYPES, action_two
    )

    assert payload_one["domain"] is payload_two["domain"]
    assert payload_one["types"] is payload_two["types"]
    assert payload_one["message"] is action_one
    assert payload_two["message"] is action_two


def test_sign_action_matches_legacy_full_message_path() -> None:
    wallet = Account.from_key("0x" + ("11" * 32))
    action = {
        "type": "order",
        "orders": [
            {
                "a": 0,
                "b": True,
                "p": "110000",
                "s": "0.1",
                "r": False,
                "t": {"limit": {"tif": "Alo"}},
            }
        ],
        "grouping": "na",
    }
    nonce = 1_700_000_000_000

    current = sign_action(wallet, action, None, nonce, True)

    legacy_message = {
        "domain": {
            "chainId": 1337,
            "name": "Exchange",
            "verifyingContract": "0x0000000000000000000000000000000000000000",
            "version": "1",
        },
        "types": {
            "Agent": [
                {"name": "source", "type": "string"},
                {"name": "connectionId", "type": "bytes32"},
            ],
            "EIP712Domain": [
                {"name": "name", "type": "string"},
                {"name": "version", "type": "string"},
                {"name": "chainId", "type": "uint256"},
                {"name": "verifyingContract", "type": "address"},
            ],
        },
        "primaryType": "Agent",
        "message": {
            "source": "a",
            "connectionId": hash_action(action, None, nonce, None),
        },
    }
    legacy_encoded = encode_typed_data(full_message=legacy_message)
    legacy_signed = wallet.sign_message(legacy_encoded)
    legacy = {
        "r": to_hex(legacy_signed["r"]),
        "s": to_hex(legacy_signed["s"]),
        "v": legacy_signed["v"],
    }

    assert current == legacy


def test_sign_user_signed_action_matches_legacy_full_message_path() -> None:
    wallet = Account.from_key("0x" + ("22" * 32))
    action = {
        "type": "usdSend",
        "amount": "12.34",
        "destination": "0x1234567890123456789012345678901234567890",
        "time": 1_700_000_000_000,
    }

    current = sign_user_signed_action(
        wallet,
        action.copy(),
        USD_SEND_SIGN_TYPES,
        "HyperliquidTransaction:UsdSend",
        True,
    )

    legacy_action = {
        **action,
        "signatureChainId": SIGNATURE_CHAIN_ID,
        "hyperliquidChain": "Mainnet",
    }
    legacy_encoded = encode_typed_data(
        full_message={
            "domain": {
                "name": "HyperliquidSignTransaction",
                "version": "1",
                "chainId": int(SIGNATURE_CHAIN_ID, 16),
                "verifyingContract": "0x0000000000000000000000000000000000000000",
            },
            "types": {
                "HyperliquidTransaction:UsdSend": USD_SEND_SIGN_TYPES,
                "EIP712Domain": [
                    {"name": "name", "type": "string"},
                    {"name": "version", "type": "string"},
                    {"name": "chainId", "type": "uint256"},
                    {"name": "verifyingContract", "type": "address"},
                ],
            },
            "primaryType": "HyperliquidTransaction:UsdSend",
            "message": legacy_action,
        }
    )
    legacy_signed = wallet.sign_message(legacy_encoded)
    legacy = {
        "r": to_hex(legacy_signed["r"]),
        "s": to_hex(legacy_signed["s"]),
        "v": legacy_signed["v"],
    }

    assert current == legacy
