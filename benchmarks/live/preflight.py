from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import cast

from eth_account import Account
from eth_utils import is_address, is_same_address, to_normalized_address

from .models import BenchmarkFailure


_REQUIRED_VARIABLES = ("HL_ADDR", "HL_AK", "HL_SK", "HL_SUB")


@dataclass(frozen=True, slots=True, repr=False)
class Credentials:
    master_address: str
    api_wallet_address: str
    signing_key: str
    subaccount_address: str

    def __repr__(self) -> str:
        return "Credentials(<redacted testnet credentials>)"

    @classmethod
    def from_environ(cls, environ: Mapping[str, str]) -> Credentials:
        if environ.get("IS_MAINNET", "").strip().casefold() != "false":
            raise BenchmarkFailure("IS_MAINNET must be false for live benchmarks")

        values: dict[str, str] = {}
        for name in _REQUIRED_VARIABLES:
            value = environ.get(name)
            if not value:
                raise BenchmarkFailure(f"missing {name} for live benchmarks")
            values[name] = value

        for name in ("HL_ADDR", "HL_AK", "HL_SUB"):
            if not is_address(values[name]):
                raise BenchmarkFailure(f"{name} must be an Ethereum address")

        try:
            derived_address = Account.from_key(values["HL_SK"]).address
        except (TypeError, ValueError):
            raise BenchmarkFailure("HL_SK must be a 32-byte private key") from None
        if not is_same_address(derived_address, values["HL_AK"]):
            raise BenchmarkFailure("HL_SK does not match HL_AK")

        return cls(
            master_address=to_normalized_address(values["HL_ADDR"]),
            api_wallet_address=to_normalized_address(values["HL_AK"]),
            signing_key=values["HL_SK"],
            subaccount_address=to_normalized_address(values["HL_SUB"]),
        )


def _mapping(value: object) -> Mapping[str, object] | None:
    if not isinstance(value, Mapping):
        return None
    return cast(Mapping[str, object], value)


def validate_roles(master_address: str, api_role: object, sub_role: object) -> None:
    api = _mapping(api_role)
    if api is None or api.get("role") != "agent":
        raise BenchmarkFailure("HL_AK must be an API wallet")
    api_data = _mapping(api.get("data"))
    api_owner = None if api_data is None else api_data.get("user")
    if (
        not isinstance(api_owner, str)
        or not is_address(api_owner)
        or not is_same_address(api_owner, master_address)
    ):
        raise BenchmarkFailure("HL_AK must belong to HL_ADDR")

    subaccount = _mapping(sub_role)
    if subaccount is None or subaccount.get("role") != "subAccount":
        raise BenchmarkFailure("HL_SUB must be a subaccount")
    subaccount_data = _mapping(subaccount.get("data"))
    subaccount_owner = (
        None if subaccount_data is None else subaccount_data.get("master")
    )
    if (
        not isinstance(subaccount_owner, str)
        or not is_address(subaccount_owner)
        or not is_same_address(subaccount_owner, master_address)
    ):
        raise BenchmarkFailure("HL_SUB must belong to HL_ADDR")
