import asyncio

import pytest

from async_hyperliquid import AsyncHyperliquid


@pytest.mark.asyncio(loop_scope="session")
async def test_twap_order(hl: AsyncHyperliquid):
    coin = "kBONK"
    is_buy = True
    sz = 32451
    ro = False
    minutes = 30
    randomize = False

    resp = await hl.place_twap(coin, is_buy, sz, minutes, ro, randomize)
    print(resp)
    assert resp["status"] == "ok"
    assert resp["response"]["type"] == "twapOrder"

    twap_id = resp["response"]["data"]["status"]["running"]["twapId"]
    assert twap_id > 0

    # sleep for one minute to get clear results
    print("Sleeping one minute to cancel twap and close all positions")
    await asyncio.sleep(60)

    # cancel twap
    resp = await hl.cancel_twap(coin, twap_id)
    print(resp)
    assert resp["status"] == "ok"
    assert resp["response"]["type"] == "twapCancel"
    assert resp["response"]["data"]["status"] == "success"

    # close all positions
    resp = await hl.close_all_positions()
    print(resp)


@pytest.mark.asyncio(loop_scope="session")
async def test_use_big_block(hl: AsyncHyperliquid):
    resp = await hl.use_big_block(True)
    print(resp, end=" ")


@pytest.mark.asyncio(loop_scope="session")
async def test_usd_transfer(hl: AsyncHyperliquid):
    # This action requires account private key
    amount = 10.01
    dest = ""  # Setup another account on testnet
    resp = await hl.usd_transfer(amount, dest)
    print(resp, end=" ")
    assert resp["status"] == "ok"


@pytest.mark.asyncio(loop_scope="session")
async def test_spot_transfer(hl: AsyncHyperliquid):
    # This action requires account private key
    coin = "HYPE/USDC"
    amount = 0.000000016
    dest = ""  # Setup another account on testnet
    resp = await hl.spot_transfer(coin, amount, dest)
    print(resp, end=" ")
    assert resp["status"] == "ok"


@pytest.mark.asyncio(loop_scope="session")
async def test_withdraw(hl: AsyncHyperliquid):
    # This action requires account private key
    amount = 12.126
    resp = await hl.initiate_withdrawal(amount)
    print(resp, end=" ")
    assert resp["status"] == "ok"


@pytest.mark.asyncio(loop_scope="session")
async def test_usd_class_transfer(hl: AsyncHyperliquid):
    # This action requires account private key
    amount = 10.356
    to_perp = True
    resp = await hl.usd_class_transfer(amount, to_perp)
    print(resp)
    assert resp["status"] == "ok"
    await asyncio.sleep(5)

    to_perp = False
    resp = await hl.usd_class_transfer(amount, to_perp)
    print(resp)
    assert resp["status"] == "ok"


@pytest.mark.asyncio(loop_scope="session")
async def test_vault_transfer(hl: AsyncHyperliquid):
    hlp = "0xa15099a30bbf2e68942d6f4c43d70d04faeab0a0"
    amount = 10.123
    is_deposit = True
    resp = await hl.vault_transfer(hlp, amount, is_deposit)
    print(resp)
    assert resp["status"] == "ok"


@pytest.mark.asyncio(loop_scope="session")
async def test_staking_deposit(hl: AsyncHyperliquid):
    amount = 0.01
    resp = await hl.staking_deposit(amount)
    print(resp)
    assert resp["status"] == "ok"


@pytest.mark.asyncio(loop_scope="session")
async def test_staking_withdraw(hl: AsyncHyperliquid):
    amount = 0.01
    resp = await hl.staking_withdraw(amount)
    print(resp)
    assert resp["status"] == "ok"


@pytest.mark.asyncio(loop_scope="session")
async def test_token_delegate(hl: AsyncHyperliquid):
    # This action requires account private key
    validator = "0x4dbf394da4b348b88e8090d22051af83e4cbaef4"  # Hypurr3
    amount = 0.01
    is_undelegate = False
    resp = await hl.token_delegate(validator, amount, is_undelegate)
    print(resp)
    assert resp["status"] == "ok"


@pytest.mark.asyncio(loop_scope="session")
async def test_user_dex_abstraction(hl: AsyncHyperliquid):
    resp = await hl.user_dex_abstraction()
    print(resp)


@pytest.mark.asyncio(loop_scope="session")
async def test_agent_enable_dex_abstraction(hl: AsyncHyperliquid):
    resp = await hl.agent_enable_dex_abstraction()
    print(resp)


@pytest.mark.asyncio(loop_scope="session")
async def test_user_set_abstraction(hl: AsyncHyperliquid):
    abstraction = await hl.get_user_abstraction()
    print(abstraction)
    if abstraction not in {
        "disabled",
        "unifiedAccount",
        "portfolioMargin",
        "default",
        "dexAbstraction",
    }:
        pytest.skip(
            "Current abstraction is not directly settable by user_set_abstraction"
        )

    resp = await hl.user_set_abstraction(abstraction)  # type: ignore
    print(resp)
    assert resp["status"] == "ok"


@pytest.mark.asyncio(loop_scope="session")
async def test_agent_set_abstraction(hl: AsyncHyperliquid):
    abstraction = await hl.get_user_abstraction()
    mapping = {"disabled": "i", "unifiedAccount": "u", "portfolioMargin": "p"}
    if abstraction not in mapping:
        pytest.skip(
            "Current abstraction is not directly settable by agent_set_abstraction"
        )

    resp = await hl.agent_set_abstraction(mapping[abstraction])  # type: ignore[arg-type]
    print(resp)
    assert resp["status"] == "ok"


@pytest.mark.asyncio(loop_scope="session")
async def test_approve_builder_fee(hl: AsyncHyperliquid):
    # Builder fees charged can be at most 0.1% on perps and 1% on spot.
    fee_rate = 5.5 * 1 / 10_000  # 5.5 bps
    assert fee_rate <= 0.001
    builder = "0xbcc2c3ccc4282990d4c979c3c7cb6148c4dd266a"
    resp = await hl.approve_builder_fee(fee_rate, builder)
    print(resp)
