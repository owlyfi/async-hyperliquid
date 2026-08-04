from typing import cast

import pytest

from async_hyperliquid import AsyncHyperliquid
from async_hyperliquid.types import CancelOrder, LimitOrder, Side, TimeInForce
from async_hyperliquid.types.exchange import RestingStatus


@pytest.mark.asyncio(loop_scope="session")
async def test_testnet_limit_order_can_be_reconciled_and_cancelled(
    hl: AsyncHyperliquid,
) -> None:
    response = await hl.exchange.place_limit_order(
        LimitOrder("BTC", Side.BUY, size=10, price=1, time_in_force=TimeInForce.ALO)
    )
    assert response["status"] == "ok", response["response"]
    first = response["response"]["data"]["statuses"][0]
    assert "resting" in first, f"test order did not rest: {first}"
    resting = cast(RestingStatus, first)
    order_id = resting["resting"]["oid"]

    try:
        assert order_id > 0
    finally:
        cancelled = await hl.exchange.cancel_orders((CancelOrder("BTC", order_id),))

    assert cancelled["status"] == "ok"
