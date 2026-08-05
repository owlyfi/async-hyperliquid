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
    error = status.get("error")
    if isinstance(error, str):
        raise AssertionError(error)
    resting = cast(JsonObject, status["resting"])
    oid = resting["oid"]
    assert isinstance(oid, int)
    return oid


def requires_order_cleanup(response: PlaceOrderResponse) -> bool:
    assert response["status"] == "ok"
    status = response["response"]["data"]["statuses"][0]
    return not (isinstance(status, dict) and isinstance(status.get("error"), str))


def _assert_targeted_cancel_succeeded(response: CancelOrderResponse) -> None:
    if response["status"] != "ok":
        raise AssertionError("targeted test-order cleanup request failed")
    if response["response"]["data"]["statuses"] != ["success"]:
        raise AssertionError("targeted test-order cleanup was not confirmed")


async def cleanup_order(
    client: AsyncHyperliquid, owner_address: str, coin: str, cloid: Cloid
) -> None:
    failures: list[Exception] = []
    for attempt in range(2):
        try:
            response = await client.cancel_by_cloid(CancelByCloid(coin, cloid))
            _assert_targeted_cancel_succeeded(response)
            return
        except Exception as error:
            failures.append(error)

        try:
            status = await client.info.order_status(owner_address, cloid)
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

    raise ExceptionGroup("targeted order cleanup failed", failures)


async def assert_order_owner(
    client: AsyncHyperliquid,
    owner_address: str,
    cloid: Cloid,
    *,
    excluded_owner_address: str | None = None,
) -> None:
    owner_status = await client.info.order_status(owner_address, cloid)
    assert owner_status["status"] == "order"
    assert owner_status["order"]["status"] == "open"

    if excluded_owner_address is not None:
        excluded_status = await client.info.order_status(excluded_owner_address, cloid)
        assert excluded_status["status"] == "unknownOid"


async def place_and_assert_order_owner(
    client: AsyncHyperliquid,
    owner_address: str,
    excluded_owner_address: str,
    order: PlaceOrderRequest,
) -> None:
    cloid = Cloid.from_int(uuid4().int)
    order["cloid"] = cloid
    failure: BaseException | None = None
    cleanup_required = True
    try:
        response = await client.place_limit_order(order)
        cleanup_required = requires_order_cleanup(response)
        _resting_oid(response)
        await assert_order_owner(
            client, owner_address, cloid, excluded_owner_address=excluded_owner_address
        )
    except BaseException as error:
        failure = error
    finally:
        if cleanup_required:
            try:
                await cleanup_order(client, owner_address, order["coin"], cloid)
            except BaseException as cleanup_error:
                if failure is not None:
                    raise BaseExceptionGroup(
                        "order routing test and cleanup both failed",
                        [failure, cleanup_error],
                    ) from None
                raise
    if failure is not None:
        raise failure
