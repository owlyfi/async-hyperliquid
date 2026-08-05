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
        raise AssertionError(
            f"targeted test-order cleanup request failed: response={response!r}"
        )
    if response["response"]["data"]["statuses"] != ["success"]:
        raise AssertionError(
            f"targeted test-order cleanup was not confirmed: response={response!r}"
        )


async def cleanup_order(
    client: AsyncHyperliquid, owner_address: str, coin: str, cloid: Cloid
) -> bool:
    failures: list[Exception] = []
    for attempt in range(2):
        try:
            response = await client.cancel_by_cloid(CancelByCloid(coin, cloid))
            _assert_targeted_cancel_succeeded(response)
            return True
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
            return False
        failures.append(AssertionError("test order remains open after cleanup"))

    raise ExceptionGroup(
        "targeted order cleanup failed "
        f"(owner_address={owner_address!r}, coin={coin!r}, cloid={cloid!r})",
        failures,
    )


async def cleanup_shared_cloid_orders(
    master_client: AsyncHyperliquid,
    master_owner_address: str,
    master_coin: str,
    subaccount_client: AsyncHyperliquid,
    subaccount_owner_address: str,
    subaccount_coin: str,
    cloid: Cloid,
    *,
    failure: BaseException | None,
    master_cleanup_required: bool,
    subaccount_cleanup_required: bool,
) -> None:
    failures: list[BaseException] = []
    if failure is not None:
        failures.append(failure)

    master_cancel_succeeded = False
    if master_cleanup_required:
        try:
            master_cancel_succeeded = await cleanup_order(
                master_client, master_owner_address, master_coin, cloid
            )
        except BaseException as cleanup_error:
            failures.append(cleanup_error)

    if master_cancel_succeeded and subaccount_cleanup_required:
        try:
            await assert_order_owner(subaccount_client, subaccount_owner_address, cloid)
        except BaseException as isolation_error:
            failures.append(isolation_error)

    if subaccount_cleanup_required:
        try:
            await cleanup_order(
                subaccount_client, subaccount_owner_address, subaccount_coin, cloid
            )
        except BaseException as cleanup_error:
            failures.append(cleanup_error)

    if len(failures) == 1:
        raise failures[0]
    if failures:
        raise BaseExceptionGroup("shared-cloid routing cleanup failed", failures)


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
