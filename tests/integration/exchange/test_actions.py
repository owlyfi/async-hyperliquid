import os

import pytest

from async_hyperliquid import AsyncHyperliquid
from async_hyperliquid.types import (
    UserAbstraction,
    AgentAbstraction,
    DefaultActionResponse,
)

pytestmark = [
    pytest.mark.exchange,
    pytest.mark.destructive_exchange,
    pytest.mark.asyncio(loop_scope="session"),
]


def _capability(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise pytest.skip.Exception(
            f"set {name} to enable this testnet protocol capability"
        )
    return value


def _assert_ok(response: DefaultActionResponse) -> None:
    assert response["status"] == "ok"


async def test_set_referrer_code(master_hl: AsyncHyperliquid) -> None:
    _assert_ok(
        await master_hl.exchange.set_referrer_code(_capability("HL_REFERRER_CODE"))
    )


async def test_create_sub_account(master_hl: AsyncHyperliquid) -> None:
    _assert_ok(
        await master_hl.exchange.create_sub_account(_capability("HL_SUBACCOUNT_NAME"))
    )


async def test_vault_transfer(master_hl: AsyncHyperliquid) -> None:
    vault = _capability("HL_TEST_VAULT")
    amount = float(_capability("HL_TEST_VAULT_AMOUNT"))
    try:
        _assert_ok(await master_hl.exchange.vault_transfer(vault, amount))
    finally:
        _assert_ok(
            await master_hl.exchange.vault_transfer(vault, amount, is_deposit=False)
        )


async def test_hip3_liquidator_transfer(api_hl: AsyncHyperliquid) -> None:
    dex = _capability("HL_HIP3_LIQUIDATOR_DEX")
    try:
        _assert_ok(await api_hl.exchange.hip3_liquidator_transfer(dex, 1_000))
    finally:
        _assert_ok(
            await api_hl.exchange.hip3_liquidator_transfer(dex, 1_000, is_deposit=False)
        )


async def test_reserve_request_weight(master_hl: AsyncHyperliquid) -> None:
    _capability("RUN_PAID_ACTION_TESTS")
    _assert_ok(await master_hl.exchange.reserve_request_weight(1))


async def test_noop(api_hl: AsyncHyperliquid) -> None:
    _assert_ok(await api_hl.exchange.noop())


async def test_use_big_blocks(master_hl: AsyncHyperliquid) -> None:
    _assert_ok(await master_hl.exchange.use_big_blocks(True))


async def test_usd_transfer(master_hl: AsyncHyperliquid, master_address: str) -> None:
    _capability("RUN_TRANSFER_TESTS")
    _assert_ok(await master_hl.exchange.usd_transfer(0.01, master_address))


async def test_spot_transfer(master_hl: AsyncHyperliquid, master_address: str) -> None:
    coin = _capability("HL_TEST_SPOT_COIN")
    amount = float(_capability("HL_TEST_SPOT_AMOUNT"))
    _assert_ok(await master_hl.spot_transfer(coin, amount, master_address))


async def test_withdraw(master_hl: AsyncHyperliquid, master_address: str) -> None:
    _capability("RUN_WITHDRAW_TESTS")
    _assert_ok(await master_hl.exchange.withdraw(1.01, destination=master_address))


async def test_usd_class_transfer(master_hl: AsyncHyperliquid) -> None:
    _capability("RUN_TRANSFER_TESTS")
    try:
        _assert_ok(await master_hl.exchange.usd_class_transfer(0.01, to_perp=True))
    finally:
        _assert_ok(await master_hl.exchange.usd_class_transfer(0.01, to_perp=False))


async def test_send_asset(master_hl: AsyncHyperliquid, master_address: str) -> None:
    coin = _capability("HL_TEST_SPOT_COIN")
    amount = float(_capability("HL_TEST_SPOT_AMOUNT"))
    _assert_ok(
        await master_hl.send_asset(
            coin, amount, master_address, source_dex="spot", destination_dex="spot"
        )
    )


async def test_agent_send_asset(api_hl: AsyncHyperliquid, master_address: str) -> None:
    coin = _capability("HL_TEST_SPOT_COIN")
    amount = float(_capability("HL_TEST_SPOT_AMOUNT"))
    _assert_ok(
        await api_hl.agent_send_asset(
            coin, amount, master_address, source_dex="spot", destination_dex="spot"
        )
    )


async def test_send_to_evm_with_data(
    master_hl: AsyncHyperliquid, master_address: str
) -> None:
    coin = _capability("HL_TEST_SPOT_COIN")
    amount = float(_capability("HL_TEST_SPOT_AMOUNT"))
    _assert_ok(
        await master_hl.send_to_evm_with_data(
            coin,
            amount,
            master_address,
            source_dex="spot",
            address_encoding="hex",
            destination_chain_id=998,
            gas_limit=200_000,
            data="0x",
        )
    )


async def test_staking_deposit(master_hl: AsyncHyperliquid) -> None:
    amount = float(_capability("HL_TEST_STAKING_AMOUNT"))
    try:
        _assert_ok(await master_hl.exchange.staking_deposit(amount))
    finally:
        _assert_ok(await master_hl.exchange.staking_withdraw(amount))


async def test_staking_withdraw(master_hl: AsyncHyperliquid) -> None:
    amount = float(_capability("HL_TEST_STAKING_AMOUNT"))
    _assert_ok(await master_hl.exchange.staking_withdraw(amount))


async def test_token_delegate(master_hl: AsyncHyperliquid) -> None:
    validator = _capability("HL_TEST_VALIDATOR")
    amount = float(_capability("HL_TEST_DELEGATION_AMOUNT"))
    try:
        _assert_ok(await master_hl.exchange.token_delegate(validator, amount))
    finally:
        _assert_ok(
            await master_hl.exchange.token_delegate(validator, amount, undelegate=True)
        )


async def test_approve_agent(
    master_hl: AsyncHyperliquid, api_wallet_address: str
) -> None:
    _assert_ok(
        await master_hl.exchange.approve_agent(api_wallet_address, name="integration")
    )


async def test_approve_builder_fee(master_hl: AsyncHyperliquid) -> None:
    builder = _capability("HL_TEST_BUILDER")
    _assert_ok(await master_hl.exchange.approve_builder_fee(builder, 0))


async def test_convert_to_multi_sig_user(
    master_hl: AsyncHyperliquid, master_address: str, api_wallet_address: str
) -> None:
    _capability("RUN_MULTISIG_CONVERSION_TEST")
    _assert_ok(
        await master_hl.exchange.convert_to_multi_sig_user(
            (master_address, api_wallet_address), 1
        )
    )


async def test_user_dex_abstraction(
    master_hl: AsyncHyperliquid, master_address: str
) -> None:
    enabled = await master_hl.info.user_dex_abstraction(master_address)
    _assert_ok(await master_hl.exchange.user_dex_abstraction(enabled=enabled))


async def test_user_set_abstraction(
    master_hl: AsyncHyperliquid, master_address: str
) -> None:
    current = await master_hl.info.user_abstraction(master_address)
    if current not in {member.value for member in UserAbstraction}:
        raise pytest.skip.Exception(
            "testnet account abstraction is not directly settable"
        )
    _assert_ok(await master_hl.exchange.user_set_abstraction(UserAbstraction(current)))


async def test_agent_enable_dex_abstraction(api_hl: AsyncHyperliquid) -> None:
    _capability("RUN_AGENT_ABSTRACTION_TESTS")
    _assert_ok(await api_hl.exchange.agent_enable_dex_abstraction())


async def test_agent_set_abstraction(api_hl: AsyncHyperliquid) -> None:
    abstraction = AgentAbstraction(_capability("HL_AGENT_ABSTRACTION"))
    _assert_ok(await api_hl.exchange.agent_set_abstraction(abstraction))


async def test_split_outcome(master_hl: AsyncHyperliquid) -> None:
    outcome = int(_capability("HL_TEST_OUTCOME"))
    amount = float(_capability("HL_TEST_OUTCOME_AMOUNT"))
    try:
        _assert_ok(await master_hl.exchange.split_outcome(outcome, amount))
    finally:
        _assert_ok(await master_hl.exchange.merge_outcome(outcome, amount))


async def test_merge_outcome(master_hl: AsyncHyperliquid) -> None:
    outcome = int(_capability("HL_TEST_OUTCOME"))
    _assert_ok(await master_hl.exchange.merge_outcome(outcome))


async def test_merge_question(master_hl: AsyncHyperliquid) -> None:
    question = int(_capability("HL_TEST_QUESTION"))
    _assert_ok(await master_hl.exchange.merge_question(question))


async def test_negate_outcome(master_hl: AsyncHyperliquid) -> None:
    question = int(_capability("HL_TEST_QUESTION"))
    outcome = int(_capability("HL_TEST_OUTCOME"))
    amount = float(_capability("HL_TEST_OUTCOME_AMOUNT"))
    _assert_ok(await master_hl.exchange.negate_outcome(question, outcome, amount))


async def test_vote_risk_free_rate(master_hl: AsyncHyperliquid) -> None:
    _capability("RUN_VALIDATOR_ACTION_TESTS")
    _assert_ok(await master_hl.exchange.vote_risk_free_rate(0.04))


async def test_authorize_aqav2_role(master_hl: AsyncHyperliquid) -> None:
    token = int(_capability("HL_TEST_AQAV2_TOKEN"))
    _assert_ok(await master_hl.exchange.authorize_aqav2_role(token, "technical"))


async def test_claim_rewards(master_hl: AsyncHyperliquid) -> None:
    _assert_ok(await master_hl.exchange.claim_rewards())
