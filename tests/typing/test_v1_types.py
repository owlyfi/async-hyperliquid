from typing import Literal, assert_type

from async_hyperliquid.exchange import ExchangeClient
from async_hyperliquid.types import CancelByCloid, Cloid, LimitOrder, Network, Side
from async_hyperliquid.types.exchange import (
    CancelOrderResponse,
    CancelTwapResponse,
    DefaultActionResponse,
    PlaceOrderResponse,
    PlaceTwapResponse,
)
from async_hyperliquid.types.info import (
    AllMids,
    L2Book,
    L2Level,
    PerpMetaAndContexts,
    SpotMetaAndContexts,
    UserRateLimit,
)


def check_v1_contract_types(
    mids: AllMids,
    book: L2Book,
    rate_limit: UserRateLimit,
    perp_meta: PerpMetaAndContexts,
    spot_meta: SpotMetaAndContexts,
    order_response: PlaceOrderResponse,
    cancel_response: CancelOrderResponse,
) -> None:
    assert_type(mids["BTC"], str)
    assert_type(book["levels"], list[list[L2Level]])
    assert_type(rate_limit["nRequestsSurplus"], int)
    assert_type(perp_meta[0]["universe"][0]["szDecimals"], int)
    assert_type(spot_meta[0]["tokens"][0]["tokenId"], str)
    assert_type(order_response["status"], Literal["ok", "err"])
    assert_type(cancel_response["status"], Literal["ok", "err"])


def check_v1_command_types() -> None:
    cloid = Cloid("0x" + "12" * 16)
    order = LimitOrder("BTC", Side.BUY, 0.01, 100_000.0)
    cancel = CancelByCloid("BTC", cloid)

    assert_type(Network.MAINNET.signature_source, Literal["a", "b"])
    assert_type(order.client_order_id, Cloid | None)
    assert_type(cancel.client_order_id, Cloid)


async def check_twap_response_types(exchange: ExchangeClient) -> None:
    assert_type(await exchange.place_twap("BTC", Side.BUY, 0.01, 5), PlaceTwapResponse)
    assert_type(await exchange.cancel_twap("BTC", 1), CancelTwapResponse)


async def check_default_response_types(exchange: ExchangeClient) -> None:
    assert_type(await exchange.schedule_cancel(), DefaultActionResponse)
    assert_type(
        await exchange.usd_transfer(1, "0x1111111111111111111111111111111111111111"),
        DefaultActionResponse,
    )
