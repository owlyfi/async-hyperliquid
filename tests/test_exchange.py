import asyncio

import pytest

from tests.conftest import get_is_mainnet
from async_hyperliquid import AsyncHyperliquid
from async_hyperliquid.utils.types import Cloid, LimitOrder

is_mainnet = get_is_mainnet()
is_testnet = not is_mainnet


@pytest.mark.asyncio(loop_scope="session")
@pytest.mark.skipif(is_testnet, reason="Only test on mainnet")
@pytest.mark.parametrize("coin", ["BTC", "xyz:NVDA", "flx:TSLA", "vntl:OPENAI"])
async def test_update_leverage(hl: AsyncHyperliquid, coin: str):
    leverage = 1
    resp = await hl.update_leverage(leverage, coin, is_cross=False)

    assert resp["status"] == "ok"


@pytest.mark.asyncio(loop_scope="session")
async def test_spot_order(hl: AsyncHyperliquid):
    # coin = "BTC/USDC"
    coin = "@142"  # @142 is the coin name for symbol BTC/USDC
    buy_value = 10 + 0.3
    buy_price = 10_000.0
    buy_sz = buy_value / buy_price
    order_req = {
        "coin": coin,
        "is_buy": True,
        "sz": buy_sz,
        "px": buy_price,
        "is_market": False,
        "order_type": LimitOrder.ALO.value,
    }

    resp = await hl.place_order(**order_req)
    print(resp)
    assert resp["status"] == "ok"

    oid = resp["response"]["data"]["statuses"][0]["resting"]["oid"]
    assert oid

    resp = await hl.cancel_order(coin, oid)
    print(resp)
    assert resp["status"] == "ok"
    assert resp["response"]["data"]["statuses"][0] == "success"


@pytest.mark.asyncio(loop_scope="session")
async def test_perp_order(hl: AsyncHyperliquid):
    coin = "BTC"
    px = 105_001.0
    sz = 0.0001
    order_req = {
        "coin": coin,
        "is_buy": True,
        "sz": sz,
        "px": px,
        "is_market": True,
        "order_type": LimitOrder.ALO.value,
    }

    resp = await hl.place_order(**order_req)
    print(resp)
    assert resp["status"] == "ok"

    oid = resp["response"]["data"]["statuses"][0]["resting"]["oid"]
    assert oid

    resp = await hl.cancel_order(coin, oid)
    print(resp)
    assert resp["status"] == "ok"
    assert resp["response"]["data"]["statuses"][0] == "success"


@pytest.mark.asyncio(loop_scope="session")
async def test_perp_dex_order(hl: AsyncHyperliquid):
    coin = "xyz:NVDA"

    payload = {
        "coin": coin,
        "is_buy": True,
        "sz": 0.1,
        "px": 170,
        "is_market": False,
        "order_type": LimitOrder.ALO.value,
    }
    resp = await hl.place_order(**payload)

    print(resp)

    assert resp["status"] == "ok"
    assert isinstance(resp["response"], dict)


@pytest.mark.asyncio(loop_scope="session")
async def test_update_isolated_margin(hl: AsyncHyperliquid):
    res = await hl.update_leverage(2, "ETH", is_cross=False)
    print("Isolated leverage updated resp:", res)

    value = 10 + 0.3
    price = 2670.0
    size = value / price
    order_req = {
        "coin": "ETH",
        "is_buy": True,
        "sz": round(size, 4),
        "px": price,
        "is_market": False,
        "order_type": LimitOrder.GTC.value,
    }
    res = await hl.place_order(**order_req)
    print(res)


@pytest.mark.asyncio(loop_scope="session")
async def test_batch_place_orders(hl: AsyncHyperliquid):
    coin = "BTC"
    is_buy = True
    sz = 0.001
    px = 105_000
    tp_px = px + 5_000
    sl_px = px - 5_000
    o1 = {
        "coin": coin,
        "is_buy": is_buy,
        "sz": sz,
        "px": px,
        "ro": False,
        "order_type": LimitOrder.ALO.value,
    }
    # Take profit
    tp_order_type = {
        "trigger": {"isMarket": False, "triggerPx": tp_px, "tpsl": "tp"}
    }
    o2 = {
        "coin": coin,
        "is_buy": not is_buy,
        "sz": sz,
        "px": px,
        "ro": True,
        "order_type": tp_order_type,
    }
    # Stop loss
    sl_order_type = {
        "trigger": {"isMarket": False, "triggerPx": sl_px, "tpsl": "sl"}
    }
    o3 = {
        "coin": coin,
        "is_buy": not is_buy,
        "sz": sz,
        "px": px,
        "ro": True,
        "order_type": sl_order_type,
    }

    resp = await hl.batch_place_orders([o1], is_market=True)  # type: ignore
    print("\nBatch place market orders response: ", resp)
    assert resp["status"] == "ok"

    orders = [o2, o3]
    resp = await hl.batch_place_orders(orders, grouping="positionTpsl")  # type: ignore
    print("Batch place orders with 'positionTpsl' response: ", resp)
    assert resp["status"] == "ok"

    resp = await hl.close_all_positions()
    print("Close all positions response: ", resp)
    assert resp["status"] == "ok"

    orders = [o1, o2, o3]
    resp = await hl.batch_place_orders(orders, grouping="normalTpsl")  # type: ignore
    print("Batch place orders with 'normalTpsl' response: ", resp)

    orders = await hl.get_user_open_orders(is_frontend=True)
    cancels = []
    for o in orders:
        coin = o["coin"]
        oid = o["oid"]
        cancels.append((coin, oid))
    resp = await hl.batch_cancel_orders(cancels)
    print("Batch cancel orders response: ", resp)
    assert resp["status"] == "ok"


@pytest.mark.asyncio(loop_scope="session")
async def test_modify_order(hl: AsyncHyperliquid):
    cloid = Cloid.from_str("0x00000000000000000000000000000001")
    coin = "BTC"
    px = 120_000
    sz = 0.0001
    order_type = LimitOrder.ALO.value

    payload = {
        "coin": coin,
        "is_buy": False,
        "sz": sz,
        "px": px,
        "ro": False,
        "order_type": LimitOrder.GTC.value,
    }

    resp = await hl.place_order(**payload, is_market=False)
    print(resp)
    assert resp["status"] == "ok"
    assert resp["response"]["type"] == "order"

    oid = resp["response"]["data"]["statuses"][0]["resting"]["oid"]

    # increase $1 for order px, set tif to "ALO" and set cloid
    px = px + 1
    payload = {
        **payload,
        "oid": oid,
        "px": px,
        "cloid": cloid,
        "order_type": order_type,
    }
    resp = await hl.modify_order(**payload)
    print(resp)
    assert resp["status"] == "ok"
    assert resp["response"]["type"] == "order"
    order_info = resp["response"]["data"]["statuses"][0]["resting"]
    assert "oid" in order_info
    ret_oid = order_info["oid"]
    assert ret_oid != oid

    assert "cloid" in order_info
    ret_cloid = order_info["cloid"]
    assert ret_cloid == cloid.to_raw()


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
async def test_approve_builder_fee(hl: AsyncHyperliquid):
    # Builder fees charged can be at most 0.1% on perps and 1% on spot.
    fee_rate = 5.5 * 1 / 10_000  # 5.5 bps
    assert fee_rate <= 0.001
    builder = "0xbcc2c3ccc4282990d4c979c3c7cb6148c4dd266a"
    resp = await hl.approve_builder_fee(fee_rate, builder)
    print(resp)


@pytest.mark.asyncio(loop_scope="session")
async def test_place_order_with_builder(hl: AsyncHyperliquid):
    # 5.5 bps
    # fee_rate = 5.5 * 10 * 1 / 10_000
    builder = {
        "b": "0xbcc2c3ccc4282990d4c979c3c7cb6148c4dd266a",
        "f": 55,  # 5.5 bps, 0.055%
    }

    coin = "xyz:NVDA"
    payload = {
        "coin": coin,
        "is_buy": True,
        "sz": 0.1,
        "px": 175,
        "is_market": False,
        "order_type": LimitOrder.ALO.value,
        "builder": builder,
    }
    resp = await hl.place_order(**payload)
    print(resp)
