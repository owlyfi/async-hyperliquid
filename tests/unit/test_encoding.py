from copy import deepcopy

from eth_account import Account
from hyperliquid.utils.signing import action_hash as sdk_action_hash
from hyperliquid.utils.signing import sign_l1_action as sdk_sign_l1_action
import pytest

from async_hyperliquid._internal.encoding import _round_price, _round_size, encode_order
from async_hyperliquid._internal.signing import (
    _USD_SEND_SPEC,
    _sign_user_action,
    hash_action,
    sign_exchange_action,
)
from async_hyperliquid.types import (
    Cloid,
    JsonObject,
    Network,
    PlaceOrderRequest,
    TimeInForce,
    TriggerKind,
    limit_order_type,
    trigger_order_type,
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


@pytest.mark.parametrize(
    ("value", "max_decimals", "expected"),
    [
        (10_001.0, 1, 10_001),
        (0.002001, 6, 0.002001),
        (123_456.0, 1, 123_456),
        (123_456.6, 1, 123_460),
        (1_234.56, 6, 1_234.6),
        (0.0012345, 6, 0.001234),
        (0.012345, 5, 0.01235),
        (0.0001234, 8, 0.0001234),
        (0.0001234, 5, 0.00012),
    ],
)
def test_round_price_obeys_tick_size(
    value: float, max_decimals: int, expected: float | int
) -> None:
    assert _round_price(value, max_decimals) == expected


@pytest.mark.parametrize(
    ("value", "size_decimals", "expected"),
    [
        (1.001, 3, 1.001),
        (1.0001, 3, 1.0),
        (1.23456, 3, 1.235),
        (100_000_001.0, 0, 100_000_001),
    ],
)
def test_round_size_obeys_lot_size(
    value: float, size_decimals: int, expected: float | int
) -> None:
    assert _round_size(value, size_decimals) == expected


def _outcome_order(px: float, sz: float = 1.0) -> PlaceOrderRequest:
    return {
        "coin": "#10",
        "is_buy": True,
        "sz": sz,
        "px": px,
        "is_market": False,
        "order_type": limit_order_type(TimeInForce.GTC),
    }


@pytest.mark.parametrize(
    ("px", "expected"),
    [(0.00001, "0.00001"), (0.4, "0.4"), (0.400014, "0.40001"), (0.99999, "0.99999")],
)
def test_encode_outcome_uses_fixed_price_tick(px: float, expected: str) -> None:
    encoded = encode_order(
        _outcome_order(px),
        asset=100_000_010,
        size_decimals=0,
        is_spot=True,
        is_outcome=True,
    )

    assert encoded["p"] == expected


@pytest.mark.parametrize("px", [0.000009, 1.0])
def test_encode_outcome_rejects_price_outside_binary_domain(px: float) -> None:
    with pytest.raises(ValueError, match="outcome price"):
        encode_order(
            _outcome_order(px),
            asset=100_000_010,
            size_decimals=0,
            is_spot=True,
            is_outcome=True,
        )


def test_encode_outcome_does_not_gate_minimum_notional() -> None:
    encoded = encode_order(
        _outcome_order(0.4, sz=1.0),
        asset=100_000_010,
        size_decimals=0,
        is_spot=True,
        is_outcome=True,
    )

    assert float(encoded["p"]) * float(encoded["s"]) == 0.4


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


@pytest.mark.parametrize("network", [Network.MAINNET, Network.TESTNET])
@pytest.mark.parametrize(
    ("vault_address", "expires_after"),
    [
        (None, None),
        (None, NONCE + 1_000),
        ("0x2222222222222222222222222222222222222222", None),
        ("0x2222222222222222222222222222222222222222", NONCE + 1_000),
    ],
)
def test_exchange_signature_matrix_matches_official_sdk(
    network: Network, vault_address: str | None, expires_after: int | None
) -> None:
    wallet = Account.from_key("0x" + "11" * 32)

    actual = sign_exchange_action(
        wallet,
        ORDER_ACTION,
        vault_address,
        NONCE,
        network.signature_source,
        expires_after,
    )
    expected = sdk_sign_l1_action(
        wallet,
        ORDER_ACTION,
        vault_address,
        NONCE,
        expires_after,
        network is Network.MAINNET,
    )

    assert actual == expected


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


def test_limit_order_encoding_is_exact_and_does_not_mutate_request() -> None:
    cloid = Cloid("0x" + "12" * 16)
    order: PlaceOrderRequest = {
        "coin": "BTC",
        "is_buy": True,
        "sz": 0.010_000_000_01,
        "px": 100_000.4,
        "is_market": False,
        "ro": False,
        "order_type": limit_order_type(TimeInForce.ALO),
        "cloid": cloid,
    }
    original = deepcopy(order)

    encoded = encode_order(
        order, asset=0, size_decimals=5, is_spot=False, is_outcome=False
    )

    assert encoded == {
        "a": 0,
        "b": True,
        "p": "100000",
        "s": "0.01",
        "r": False,
        "t": {"limit": {"tif": "Alo"}},
        "c": str(cloid),
    }
    assert order == original


def test_missing_order_type_defaults_to_ioc_limit() -> None:
    order: PlaceOrderRequest = {
        "coin": "BTC",
        "is_buy": False,
        "sz": 0.01,
        "px": 99_000.0,
        "is_market": False,
    }

    assert encode_order(
        order, asset=0, size_decimals=5, is_spot=False, is_outcome=False
    )["t"] == {"limit": {"tif": "Ioc"}}


def test_order_encoding_rejects_size_below_market_precision() -> None:
    order: PlaceOrderRequest = {
        "coin": "BTC",
        "is_buy": True,
        "sz": 0.000_001,
        "px": 100_000.0,
        "is_market": False,
    }

    with pytest.raises(ValueError, match="order size is below market precision"):
        encode_order(order, asset=0, size_decimals=5, is_spot=False, is_outcome=False)


@pytest.mark.parametrize("size", [float("nan"), float("inf"), 0.0, -0.01])
def test_order_encoding_rejects_non_positive_or_non_finite_size(size: float) -> None:
    order: PlaceOrderRequest = {
        "coin": "BTC",
        "is_buy": True,
        "sz": size,
        "px": 100_000.0,
        "is_market": False,
    }

    with pytest.raises(ValueError, match="size must be finite and greater than zero"):
        encode_order(order, asset=0, size_decimals=5, is_spot=False, is_outcome=False)


def test_order_encoding_rejects_price_below_market_precision() -> None:
    order: PlaceOrderRequest = {
        "coin": "BTC",
        "is_buy": True,
        "sz": 0.01,
        "px": 0.01,
        "is_market": False,
    }

    with pytest.raises(ValueError, match="order value is below market precision"):
        encode_order(order, asset=0, size_decimals=5, is_spot=False, is_outcome=False)


def test_spot_order_encoding_rejects_reduce_only() -> None:
    order: PlaceOrderRequest = {
        "coin": "@182",
        "is_buy": False,
        "sz": 0.01,
        "px": 4_000.0,
        "is_market": False,
        "ro": True,
    }

    with pytest.raises(ValueError, match="spot orders cannot be reduce-only"):
        encode_order(
            order, asset=10_182, size_decimals=2, is_spot=True, is_outcome=False
        )


def test_perp_reduce_only_below_minimum_notional_still_encodes() -> None:
    order: PlaceOrderRequest = {
        "coin": "BTC",
        "is_buy": False,
        "sz": 0.000_01,
        "px": 100_000.0,
        "is_market": False,
        "ro": True,
    }

    encoded = encode_order(
        order, asset=0, size_decimals=5, is_spot=False, is_outcome=False
    )

    assert float(encoded["p"]) * float(encoded["s"]) == 1.0
    assert encoded["r"] is True


def test_spot_non_reduce_only_below_minimum_notional_still_encodes() -> None:
    order: PlaceOrderRequest = {
        "coin": "@0",
        "is_buy": True,
        "sz": 0.01,
        "px": 1.0,
        "is_market": False,
    }

    encoded = encode_order(
        order, asset=10_000, size_decimals=2, is_spot=True, is_outcome=False
    )

    assert float(encoded["p"]) * float(encoded["s"]) == 0.01
    assert encoded["r"] is False


def test_trigger_order_encoding_preserves_trigger_contract() -> None:
    order: PlaceOrderRequest = {
        "coin": "xyz:NVDA",
        "is_buy": False,
        "sz": 0.1254,
        "px": 177.064,
        "is_market": False,
        "ro": True,
        "order_type": trigger_order_type(
            is_market=True, trigger_px="180.1250", tpsl=TriggerKind.STOP_LOSS
        ),
    }

    assert encode_order(
        order, asset=110_002, size_decimals=3, is_spot=False, is_outcome=False
    ) == {
        "a": 110_002,
        "b": False,
        "p": "177.06",
        "s": "0.125",
        "r": True,
        "t": {"trigger": {"isMarket": True, "triggerPx": "180.12", "tpsl": "sl"}},
    }


def test_btc_trigger_price_obeys_tick_size() -> None:
    order: PlaceOrderRequest = {
        "coin": "BTC",
        "is_buy": False,
        "sz": 0.01,
        "px": 10_001.0,
        "is_market": False,
        "order_type": trigger_order_type(
            is_market=True, trigger_px="180.125", tpsl=TriggerKind.STOP_LOSS
        ),
    }

    encoded = encode_order(
        order, asset=0, size_decimals=5, is_spot=False, is_outcome=False
    )

    assert encoded["t"] == {
        "trigger": {"isMarket": True, "triggerPx": "180.1", "tpsl": "sl"}
    }


@pytest.mark.parametrize("trigger_px", ["0.000009", "1"])
def test_outcome_trigger_rejects_price_outside_binary_domain(trigger_px: str) -> None:
    order = _outcome_order(0.4)
    order["order_type"] = trigger_order_type(
        is_market=True, trigger_px=trigger_px, tpsl=TriggerKind.STOP_LOSS
    )

    with pytest.raises(ValueError, match="outcome price"):
        encode_order(
            order, asset=100_000_010, size_decimals=0, is_spot=True, is_outcome=True
        )
