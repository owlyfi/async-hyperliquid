from typing import Literal, assert_type

from async_hyperliquid import AsyncHyperliquid
from async_hyperliquid.exchange import ExchangeClient
from async_hyperliquid.types import (
    BaseOrderRequest,
    CancelByCloid,
    Cloid,
    ModifyOrderRequest,
    Network,
    PlaceOrderRequest,
    TimeInForce,
    limit_order_type,
)
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
    order: PlaceOrderRequest = {
        "coin": "BTC",
        "is_buy": True,
        "sz": 0.01,
        "px": 100_000.0,
        "is_market": False,
        "cloid": cloid,
        "order_type": limit_order_type(TimeInForce.GTC),
    }
    modify: ModifyOrderRequest = {
        "oid": cloid,
        "coin": "BTC",
        "is_buy": False,
        "sz": 0.01,
        "px": 101_000.0,
        "cloid": cloid,
    }
    base_order: BaseOrderRequest = order
    base_modify: BaseOrderRequest = modify
    cancel = CancelByCloid("BTC", cloid)

    assert_type(Network.MAINNET.signature_source, Literal["a", "b"])
    assert_type(base_order["coin"], str)
    assert_type(base_order["is_buy"], bool)
    assert_type(base_order["sz"], float)
    assert_type(base_order["px"], float)
    assert_type(base_order.get("cloid"), Cloid | None)
    assert_type(base_modify.get("cloid"), Cloid | None)
    assert_type(cancel.cloid, Cloid)


async def check_twap_response_types(client: AsyncHyperliquid) -> None:
    assert_type(await client.place_twap("BTC", True, 0.01, 5), PlaceTwapResponse)
    assert_type(
        await client.place_twap(
            "BTC", True, 0.01, 5, trigger_px=105_000.0, stop_px=95_000.0
        ),
        PlaceTwapResponse,
    )
    assert_type(await client.cancel_twap("BTC", 1), CancelTwapResponse)


async def check_default_response_types(exchange: ExchangeClient) -> None:
    assert_type(await exchange.schedule_cancel(), DefaultActionResponse)
    assert_type(
        await exchange.usd_transfer(1, "0x1111111111111111111111111111111111111111"),
        DefaultActionResponse,
    )
