from collections.abc import Mapping

import pytest

from async_hyperliquid.types.info import UserRole
from tests.integration.live_config import (
    require_env,
    require_testnet,
    validate_live_credentials,
    validate_live_roles,
)


MASTER_KEY = "0x" + "11" * 32
MASTER_ADDRESS = "0x19E7E376E7C213B7E7e7e46cc70A5dd086DAff2A"
API_KEY = "0x" + "22" * 32
API_ADDRESS = "0x1563915e194D8CfBA1943570603F7606A3115508"
SUBACCOUNT_ADDRESS = "0x3333333333333333333333333333333333333333"


def live_environ(**overrides: str) -> Mapping[str, str]:
    values = {
        "HL_ADDR": MASTER_ADDRESS,
        "HL_PK": MASTER_KEY,
        "HL_AK": API_ADDRESS,
        "HL_SK": API_KEY,
        "HL_SUB": SUBACCOUNT_ADDRESS,
        "IS_MAINNET": "false",
    }
    values.update(overrides)
    return values


def test_required_env_names_only_the_missing_variable() -> None:
    with pytest.raises(
        pytest.UsageError, match=r"^missing required environment variable: HL_PK$"
    ):
        require_env("HL_PK", {})


def test_mainnet_exchange_configuration_fails_instead_of_downgrading_to_skip() -> None:
    with pytest.raises(
        pytest.UsageError, match=r"^Exchange integration is restricted to testnet$"
    ):
        require_testnet({"IS_MAINNET": "true"})


def test_testnet_configuration_is_accepted_case_insensitively() -> None:
    require_testnet({"IS_MAINNET": "FALSE"})


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"HL_ADDR": API_ADDRESS}, "HL_PK does not match HL_ADDR"),
        ({"HL_AK": MASTER_ADDRESS}, "HL_SK does not match HL_AK"),
        ({"HL_SUB": "not-an-address"}, "HL_SUB must be an Ethereum address"),
    ],
)
def test_live_credential_validation_reports_roles_without_secret_material(
    overrides: dict[str, str], message: str
) -> None:
    environ = live_environ(**overrides)

    with pytest.raises(pytest.UsageError, match=f"^{message}$") as error:
        validate_live_credentials(environ)

    rendered = str(error.value)
    assert MASTER_KEY not in rendered
    assert API_KEY not in rendered


def test_live_credential_validation_accepts_master_api_and_subaccount_roles() -> None:
    validate_live_credentials(live_environ())


def test_live_role_validation_accepts_owned_api_wallet_and_subaccount() -> None:
    validate_live_roles(
        MASTER_ADDRESS,
        {"role": "agent", "data": {"user": MASTER_ADDRESS}},
        {"role": "subAccount", "data": {"master": MASTER_ADDRESS}},
    )


@pytest.mark.parametrize(
    ("api_wallet_role", "subaccount_role", "message"),
    [
        (
            {"role": "user"},
            {"role": "subAccount", "data": {"master": MASTER_ADDRESS}},
            "HL_AK must be an API wallet for HL_ADDR",
        ),
        (
            {"role": "agent", "data": {"user": API_ADDRESS}},
            {"role": "subAccount", "data": {"master": MASTER_ADDRESS}},
            "HL_AK must be an API wallet for HL_ADDR",
        ),
        (
            {"role": "agent", "data": {"user": MASTER_ADDRESS}},
            {"role": "user"},
            "HL_SUB must be a subaccount of HL_ADDR",
        ),
        (
            {"role": "agent", "data": {"user": MASTER_ADDRESS}},
            {"role": "subAccount", "data": {"master": API_ADDRESS}},
            "HL_SUB must be a subaccount of HL_ADDR",
        ),
    ],
)
def test_live_role_validation_rejects_wrong_roles_or_owners(
    api_wallet_role: UserRole, subaccount_role: UserRole, message: str
) -> None:
    with pytest.raises(pytest.UsageError, match=f"^{message}$"):
        validate_live_roles(MASTER_ADDRESS, api_wallet_role, subaccount_role)
