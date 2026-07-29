import math
from dataclasses import dataclass
from typing import Literal, cast

from eth_account.messages import SignableMessage, encode_typed_data
from eth_account.signers.local import LocalAccount
from eth_utils.conversions import to_hex
from eth_utils.crypto import keccak
import msgpack

from .constants import PERP_DEX_ASSET_OFFSET, SIGNATURE_CHAIN_ID, SPOT_ASSET_OFFSET
from .types import JsonObject, LimitOrder, Network, Side, TriggerOrder
from .types.exchange import EncodedOrder, Signature


_ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"
_EXCHANGE_DOMAIN: dict[str, str | int] = {
    "chainId": 1337,
    "name": "Exchange",
    "verifyingContract": _ZERO_ADDRESS,
    "version": "1",
}
_EXCHANGE_MESSAGE_TYPES = {
    "Agent": [
        {"name": "source", "type": "string"},
        {"name": "connectionId", "type": "bytes32"},
    ]
}
_USER_DOMAIN: dict[str, str | int] = {
    "name": "HyperliquidSignTransaction",
    "version": "1",
    "chainId": int(SIGNATURE_CHAIN_ID, 16),
    "verifyingContract": _ZERO_ADDRESS,
}


@dataclass(frozen=True, slots=True)
class _UserSigningSpec:
    primary_type: str
    message_types: dict[str, list[dict[str, str]]]


def _spec(primary_type: str, fields: list[dict[str, str]]) -> _UserSigningSpec:
    return _UserSigningSpec(primary_type, {primary_type: fields})


_USD_SEND_SPEC = _spec(
    "HyperliquidTransaction:UsdSend",
    [
        {"name": "hyperliquidChain", "type": "string"},
        {"name": "destination", "type": "string"},
        {"name": "amount", "type": "string"},
        {"name": "time", "type": "uint64"},
    ],
)
_SPOT_SEND_SPEC = _spec(
    "HyperliquidTransaction:SpotSend",
    [
        {"name": "hyperliquidChain", "type": "string"},
        {"name": "destination", "type": "string"},
        {"name": "token", "type": "string"},
        {"name": "amount", "type": "string"},
        {"name": "time", "type": "uint64"},
    ],
)
_WITHDRAW_SPEC = _spec(
    "HyperliquidTransaction:Withdraw",
    [
        {"name": "hyperliquidChain", "type": "string"},
        {"name": "destination", "type": "string"},
        {"name": "amount", "type": "string"},
        {"name": "time", "type": "uint64"},
    ],
)
_USD_CLASS_TRANSFER_SPEC = _spec(
    "HyperliquidTransaction:UsdClassTransfer",
    [
        {"name": "hyperliquidChain", "type": "string"},
        {"name": "amount", "type": "string"},
        {"name": "toPerp", "type": "bool"},
        {"name": "nonce", "type": "uint64"},
    ],
)
_SEND_ASSET_SPEC = _spec(
    "HyperliquidTransaction:SendAsset",
    [
        {"name": "hyperliquidChain", "type": "string"},
        {"name": "destination", "type": "string"},
        {"name": "sourceDex", "type": "string"},
        {"name": "destinationDex", "type": "string"},
        {"name": "token", "type": "string"},
        {"name": "amount", "type": "string"},
        {"name": "fromSubAccount", "type": "string"},
        {"name": "nonce", "type": "uint64"},
    ],
)
_STAKING_TRANSFER_SPEC = _spec(
    "HyperliquidTransaction:CDeposit",
    [
        {"name": "hyperliquidChain", "type": "string"},
        {"name": "wei", "type": "uint64"},
        {"name": "nonce", "type": "uint64"},
    ],
)
_STAKING_WITHDRAW_SPEC = _spec(
    "HyperliquidTransaction:CWithdraw",
    [
        {"name": "hyperliquidChain", "type": "string"},
        {"name": "wei", "type": "uint64"},
        {"name": "nonce", "type": "uint64"},
    ],
)
_TOKEN_DELEGATE_SPEC = _spec(
    "HyperliquidTransaction:TokenDelegate",
    [
        {"name": "hyperliquidChain", "type": "string"},
        {"name": "validator", "type": "address"},
        {"name": "wei", "type": "uint64"},
        {"name": "isUndelegate", "type": "bool"},
        {"name": "nonce", "type": "uint64"},
    ],
)
_APPROVE_AGENT_SPEC = _spec(
    "HyperliquidTransaction:ApproveAgent",
    [
        {"name": "hyperliquidChain", "type": "string"},
        {"name": "agentAddress", "type": "address"},
        {"name": "agentName", "type": "string"},
        {"name": "nonce", "type": "uint64"},
    ],
)
_APPROVE_BUILDER_FEE_SPEC = _spec(
    "HyperliquidTransaction:ApproveBuilderFee",
    [
        {"name": "hyperliquidChain", "type": "string"},
        {"name": "maxFeeRate", "type": "string"},
        {"name": "builder", "type": "address"},
        {"name": "nonce", "type": "uint64"},
    ],
)
_CONVERT_TO_MULTI_SIG_USER_SPEC = _spec(
    "HyperliquidTransaction:ConvertToMultiSigUser",
    [
        {"name": "hyperliquidChain", "type": "string"},
        {"name": "signers", "type": "string"},
        {"name": "nonce", "type": "uint64"},
    ],
)
_USER_DEX_ABSTRACTION_SPEC = _spec(
    "HyperliquidTransaction:UserDexAbstraction",
    [
        {"name": "hyperliquidChain", "type": "string"},
        {"name": "user", "type": "address"},
        {"name": "enabled", "type": "bool"},
        {"name": "nonce", "type": "uint64"},
    ],
)
_USER_SET_ABSTRACTION_SPEC = _spec(
    "HyperliquidTransaction:UserSetAbstraction",
    [
        {"name": "hyperliquidChain", "type": "string"},
        {"name": "user", "type": "address"},
        {"name": "abstraction", "type": "string"},
        {"name": "nonce", "type": "uint64"},
    ],
)


def _signature(account: LocalAccount, signable_message: SignableMessage) -> Signature:
    signed = account.sign_message(signable_message)
    return {"r": to_hex(signed["r"]), "s": to_hex(signed["s"]), "v": signed["v"]}


def hash_action(
    action: JsonObject,
    vault_address: str | None,
    nonce: int,
    expires_after: int | None = None,
) -> bytes:
    packed = cast(bytes, msgpack.packb(action))
    data = packed + nonce.to_bytes(8, "big")
    if vault_address is None:
        data += b"\x00"
    else:
        data += b"\x01" + bytes.fromhex(vault_address.removeprefix("0x"))
    if expires_after is not None:
        data += b"\x00" + expires_after.to_bytes(8, "big")
    return keccak(data)


def sign_exchange_action(
    account: LocalAccount,
    action: JsonObject,
    vault_address: str | None,
    nonce: int,
    signature_source: Literal["a", "b"],
    expires_after: int | None = None,
) -> Signature:
    connection_id = hash_action(action, vault_address, nonce, expires_after)
    signable = encode_typed_data(
        domain_data=_EXCHANGE_DOMAIN,
        message_types=_EXCHANGE_MESSAGE_TYPES,
        message_data={"source": signature_source, "connectionId": connection_id},
    )
    return _signature(account, signable)


def _sign_user_action(
    account: LocalAccount, action: JsonObject, spec: _UserSigningSpec, network: Network
) -> tuple[JsonObject, Signature]:
    wire_action: JsonObject = {
        **action,
        "signatureChainId": SIGNATURE_CHAIN_ID,
        "hyperliquidChain": ("Mainnet" if network is Network.MAINNET else "Testnet"),
    }
    signable = encode_typed_data(
        domain_data=_USER_DOMAIN,
        message_types=spec.message_types,
        message_data=wire_action,
    )
    return wire_action, _signature(account, signable)


def _round_float(value: float, decimals: int) -> float:
    return round(float(f"{float(value):.8g}"), decimals)


def _round_price(value: float, decimals: int) -> float | int:
    rounded = _round_float(value, decimals)
    if abs(rounded - round(rounded)) < 1e-12:
        return int(round(rounded))
    if rounded >= 100_000:
        return int(rounded)
    return round(float(f"{rounded:.5g}"), decimals)


def _wire_float(value: float | int) -> str:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("wire number must be finite")
    rounded = f"{number:.8f}"
    if abs(float(rounded) - number) >= 1e-12:
        raise ValueError("wire number exceeds eight decimal places")
    return rounded.rstrip("0").rstrip(".") or "0"


def encode_order(
    order: LimitOrder | TriggerOrder, *, asset: int, size_decimals: int
) -> EncodedOrder:
    price_decimals = (
        8 if SPOT_ASSET_OFFSET <= asset < PERP_DEX_ASSET_OFFSET else 6
    ) - size_decimals
    encoded: EncodedOrder = {
        "a": asset,
        "b": order.side is Side.BUY,
        "p": _wire_float(_round_price(order.price, price_decimals)),
        "s": _wire_float(_round_float(order.size, size_decimals)),
        "r": order.reduce_only,
        "t": (
            {"limit": {"tif": order.time_in_force.value}}
            if isinstance(order, LimitOrder)
            else {
                "trigger": {
                    "isMarket": order.is_market,
                    "triggerPx": _wire_float(order.trigger_price),
                    "tpsl": order.trigger_kind.value,
                }
            }
        ),
    }
    if order.client_order_id is not None:
        encoded["c"] = str(order.client_order_id)
    return encoded
