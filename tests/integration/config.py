from collections.abc import Mapping
from typing import TypeGuard

from eth_account import Account
from eth_utils import is_address, is_same_address
import pytest

from async_hyperliquid.types.info import AgentUserRole, SubAccountUserRole, UserRole


def require_env(name: str, environ: Mapping[str, str]) -> str:
    value = environ.get(name)
    if not value:
        raise pytest.UsageError(f"missing required environment variable: {name}")
    return value


def require_testnet(environ: Mapping[str, str]) -> None:
    if environ.get("IS_MAINNET", "false").lower() == "true":
        raise pytest.UsageError("Exchange integration is restricted to testnet")


def _validate_key_pair(
    private_key_name: str, address_name: str, environ: Mapping[str, str]
) -> None:
    private_key = require_env(private_key_name, environ)
    address = require_env(address_name, environ)
    try:
        derived_address = Account.from_key(private_key).address
    except (TypeError, ValueError):
        raise pytest.UsageError(
            f"{private_key_name} must be a 32-byte private key"
        ) from None
    if not is_address(address) or not is_same_address(derived_address, address):
        raise pytest.UsageError(f"{private_key_name} does not match {address_name}")


def validate_credentials(environ: Mapping[str, str]) -> None:
    _validate_key_pair("HL_PK", "HL_ADDR", environ)
    _validate_key_pair("HL_SK", "HL_AK", environ)
    if not is_address(require_env("HL_SUB", environ)):
        raise pytest.UsageError("HL_SUB must be an Ethereum address")


def _is_agent_role(role: UserRole) -> TypeGuard[AgentUserRole]:
    return role["role"] == "agent"


def _is_subaccount_role(role: UserRole) -> TypeGuard[SubAccountUserRole]:
    return role["role"] == "subAccount"


def validate_roles(
    master_address: str, api_wallet_role: UserRole, subaccount_role: UserRole
) -> None:
    if not _is_agent_role(api_wallet_role):
        raise pytest.UsageError("HL_AK must be an API wallet for HL_ADDR")
    api_wallet_owner = api_wallet_role["data"]["user"]
    if not is_address(api_wallet_owner) or not is_same_address(
        api_wallet_owner, master_address
    ):
        raise pytest.UsageError("HL_AK must be an API wallet for HL_ADDR")

    if not _is_subaccount_role(subaccount_role):
        raise pytest.UsageError("HL_SUB must be a subaccount of HL_ADDR")
    subaccount_owner = subaccount_role["data"]["master"]
    if not is_address(subaccount_owner) or not is_same_address(
        subaccount_owner, master_address
    ):
        raise pytest.UsageError("HL_SUB must be a subaccount of HL_ADDR")
