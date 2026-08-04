from typing import assert_type

from async_hyperliquid.info import InfoClient
from async_hyperliquid.types.info import (
    AccountState,
    AllMids,
    OpenOrders,
    Position,
    SpotToken,
)


async def check_info_client(info: InfoClient, account_address: str) -> None:
    assert_type(await info.all_mids(), AllMids)
    assert_type(await info.open_orders(account_address), OpenOrders)
    assert_type(await info.account_state(account_address), AccountState)
    assert_type(await info.positions(account_address), list[Position])
    assert_type(await info.spot_token_metadata("@0"), SpotToken)
    assert_type(await info.asset_id("BTC"), int)
