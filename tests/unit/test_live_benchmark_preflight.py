from collections.abc import Mapping

from eth_account import Account
import pytest

from benchmarks.live.models import BenchmarkFailure
from benchmarks.live.preflight import Credentials, validate_roles


TEST_KEY = "0x" + "11" * 32
TEST_API_WALLET = Account.from_key(TEST_KEY).address
TEST_MASTER = "0x" + "22" * 20
TEST_SUBACCOUNT = "0x" + "33" * 20


def _environment(**overrides: str) -> Mapping[str, str]:
    values = {
        "IS_MAINNET": "false",
        "HL_ADDR": TEST_MASTER,
        "HL_AK": TEST_API_WALLET,
        "HL_SK": TEST_KEY,
        "HL_SUB": TEST_SUBACCOUNT,
    }
    values.update(overrides)
    return values


def test_credentials_require_explicit_testnet_and_matching_api_key() -> None:
    credentials = Credentials.from_environ(_environment(IS_MAINNET=" False "))

    assert credentials.master_address == TEST_MASTER.lower()
    assert credentials.api_wallet_address == TEST_API_WALLET.lower()
    assert credentials.subaccount_address == TEST_SUBACCOUNT.lower()
    assert repr(credentials) == "Credentials(<redacted testnet credentials>)"


@pytest.mark.parametrize("value", ["", "true", "1", "yes"])
def test_credentials_reject_any_non_testnet_guard(value: str) -> None:
    with pytest.raises(BenchmarkFailure, match="IS_MAINNET must be false"):
        Credentials.from_environ(_environment(IS_MAINNET=value))


def test_credentials_report_missing_variable_name_without_values() -> None:
    environment = dict(_environment())
    del environment["HL_SUB"]

    with pytest.raises(BenchmarkFailure, match="missing HL_SUB") as raised:
        Credentials.from_environ(environment)

    assert TEST_KEY not in str(raised.value)
    assert TEST_MASTER not in str(raised.value)


def test_credentials_reject_mismatched_api_wallet() -> None:
    with pytest.raises(BenchmarkFailure, match="HL_SK does not match HL_AK"):
        Credentials.from_environ(_environment(HL_AK="0x" + "44" * 20))


@pytest.mark.parametrize("name", ["HL_ADDR", "HL_AK", "HL_SUB"])
def test_credentials_reject_invalid_addresses(name: str) -> None:
    with pytest.raises(BenchmarkFailure, match=f"{name} must be an Ethereum address"):
        Credentials.from_environ(_environment(**{name: "not-an-address"}))


def test_roles_must_belong_to_the_master_account() -> None:
    validate_roles(
        TEST_MASTER,
        {"role": "agent", "data": {"user": TEST_MASTER}},
        {"role": "subAccount", "data": {"master": TEST_MASTER}},
    )


@pytest.mark.parametrize(
    ("api_role", "sub_role", "message"),
    [
        (
            {"role": "missing"},
            {"role": "subAccount", "data": {"master": TEST_MASTER}},
            "HL_AK must be an API wallet",
        ),
        (
            {"role": "agent", "data": {"user": "0x" + "55" * 20}},
            {"role": "subAccount", "data": {"master": TEST_MASTER}},
            "HL_AK must belong to HL_ADDR",
        ),
        (
            {"role": "agent", "data": {"user": TEST_MASTER}},
            {"role": "missing"},
            "HL_SUB must be a subaccount",
        ),
        (
            {"role": "agent", "data": {"user": TEST_MASTER}},
            {"role": "subAccount", "data": {"master": "0x" + "55" * 20}},
            "HL_SUB must belong to HL_ADDR",
        ),
    ],
)
def test_roles_fail_closed(api_role: object, sub_role: object, message: str) -> None:
    with pytest.raises(BenchmarkFailure, match=message):
        validate_roles(TEST_MASTER, api_role, sub_role)
