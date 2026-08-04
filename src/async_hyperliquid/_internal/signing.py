from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, cast

from eth_account.messages import SignableMessage, encode_typed_data
from eth_account.signers.local import LocalAccount
from eth_utils.conversions import to_hex
from eth_utils.crypto import keccak
import msgpack

from ..constants import SIGNATURE_CHAIN_ID
from ..types import JsonObject, Network
from ..types.exchange import Signature


if TYPE_CHECKING:
    from eth_typing import Hash32


_ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"
# EIP-712 hashes dynamic strings into 32-byte ABI words; the zero address is
# also one all-zero ABI word. Only the Agent connection id varies per action.
_EXCHANGE_DOMAIN_HASH = keccak(
    keccak(
        b"EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)"
    )
    + keccak(b"Exchange")
    + keccak(b"1")
    + (1337).to_bytes(32, "big")
    + bytes(32)
)
_EXCHANGE_AGENT_TYPE_HASH = keccak(b"Agent(string source,bytes32 connectionId)")
_EXCHANGE_SOURCE_HASH = {"a": keccak(b"a"), "b": keccak(b"b")}
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
_SEND_TO_EVM_WITH_DATA_SPEC = _spec(
    "HyperliquidTransaction:SendToEvmWithData",
    [
        {"name": "hyperliquidChain", "type": "string"},
        {"name": "token", "type": "string"},
        {"name": "amount", "type": "string"},
        {"name": "sourceDex", "type": "string"},
        {"name": "destinationRecipient", "type": "string"},
        {"name": "addressEncoding", "type": "string"},
        {"name": "destinationChainId", "type": "uint32"},
        {"name": "gasLimit", "type": "uint64"},
        {"name": "data", "type": "bytes"},
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
    agent_hash = keccak(
        _EXCHANGE_AGENT_TYPE_HASH
        + _EXCHANGE_SOURCE_HASH[signature_source]
        + connection_id
    )
    message_hash = keccak(b"\x19\x01" + _EXCHANGE_DOMAIN_HASH + agent_hash)
    signed = account.unsafe_sign_hash(cast("Hash32", message_hash))
    return {"r": to_hex(signed["r"]), "s": to_hex(signed["s"]), "v": signed["v"]}


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
