from typing import cast
from uuid import uuid4

from async_hyperliquid import AsyncHyperliquid
from async_hyperliquid.types import (
    CancelByCloid,
    CancelOrderResponse,
    Cloid,
    JsonObject,
    PlaceOrderRequest,
    PlaceOrderResponse,
)


def _resting_oid(response: PlaceOrderResponse) -> int:
    assert response["status"] == "ok"
    status = cast(JsonObject, response["response"]["data"]["statuses"][0])
    resting = cast(JsonObject, status["resting"])
    oid = resting["oid"]
    assert isinstance(oid, int)
    return oid


def _assert_targeted_cancel_succeeded(response: CancelOrderResponse) -> None:
    if response["status"] != "ok":
        raise AssertionError("targeted test-order cleanup request failed")
    if response["response"]["data"]["statuses"] != ["success"]:
        raise AssertionError("targeted test-order cleanup was not confirmed")


async def _cleanup_subaccount_order(
    client: AsyncHyperliquid, subaccount_address: str, cloid: Cloid
) -> None:
    failures: list[Exception] = []
    for attempt in range(2):
        try:
            response = await client.cancel_by_cloid(CancelByCloid("BTC", cloid))
            _assert_targeted_cancel_succeeded(response)
            return
        except Exception as error:
            failures.append(error)

        try:
            status = await client.info.order_status(subaccount_address, cloid)
        except Exception as error:
            failures.append(error)
            continue

        if status["status"] == "unknownOid":
            if attempt == 1:
                failures.append(
                    AssertionError("test order status remains unknown after cleanup")
                )
                break
            continue
        order_status = status["order"]["status"]
        if order_status == "filled":
            failures.append(AssertionError("test order filled before cleanup"))
            break
        if order_status != "open":
            return
        failures.append(AssertionError("test order remains open after cleanup"))

    raise ExceptionGroup("targeted subaccount order cleanup failed", failures)


async def assert_subaccount_order(
    client: AsyncHyperliquid, subaccount_address: str, order: PlaceOrderRequest
) -> None:
    cloid = Cloid.from_int(uuid4().int)
    order["cloid"] = cloid
    failure: BaseException | None = None
    try:
        response = await client.place_limit_order(order)
        _resting_oid(response)
        status = await client.info.order_status(subaccount_address, cloid)
        assert status["status"] == "order"
    except BaseException as error:
        failure = error
    finally:
        try:
            await _cleanup_subaccount_order(client, subaccount_address, cloid)
        except BaseException as cleanup_error:
            if failure is not None:
                raise BaseExceptionGroup(
                    "subaccount order test and cleanup both failed",
                    [failure, cleanup_error],
                ) from None
            raise
    if failure is not None:
        raise failure
