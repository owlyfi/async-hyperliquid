from collections.abc import Sequence
from typing import cast

import pytest

from async_hyperliquid import AsyncHyperliquid
from async_hyperliquid.types import (
    CancelByCloid,
    CancelOrder,
    CancelOrderResponse,
    Cloid,
    PlaceOrderRequest,
    PlaceOrderResponse,
    TimeInForce,
    limit_order_type,
)
from async_hyperliquid.types.info import OrderStatus
from tests.integration.exchange.order_checks import (
    cleanup_order,
    place_and_assert_order_owner,
)


_RESTING_RESPONSE = cast(
    PlaceOrderResponse,
    {
        "status": "ok",
        "response": {"type": "order", "data": {"statuses": [{"resting": {"oid": 1}}]}},
    },
)
_ORDER_ERROR_RESPONSE = cast(
    PlaceOrderResponse,
    {
        "status": "ok",
        "response": {
            "type": "order",
            "data": {"statuses": [{"error": "Insufficient margin to place order."}]},
        },
    },
)
_CANCEL_SUCCESS = cast(
    CancelOrderResponse,
    {"status": "ok", "response": {"type": "cancel", "data": {"statuses": ["success"]}}},
)
_OPEN_ORDER_STATUS = cast(OrderStatus, {"status": "order", "order": {"status": "open"}})
_UNKNOWN_ORDER_STATUS = cast(OrderStatus, {"status": "unknownOid"})
_FILLED_ORDER_STATUS = cast(
    OrderStatus, {"status": "order", "order": {"status": "filled"}}
)
_CANCELED_ORDER_STATUS = cast(
    OrderStatus, {"status": "order", "order": {"status": "canceled"}}
)


class SubaccountOrderInfoStub:
    def __init__(self, statuses: Sequence[OrderStatus | Exception]) -> None:
        self._statuses = list(statuses)
        self.order_status_calls = 0

    async def order_status(
        self, account_address: str, order_id: int | str
    ) -> OrderStatus:
        self.order_status_calls += 1
        if not self._statuses:
            raise AssertionError("unexpected order-status reconciliation")
        result = self._statuses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


class SubaccountOrderClientStub:
    def __init__(
        self,
        submit: PlaceOrderResponse | Exception,
        cancels: Sequence[CancelOrderResponse | Exception],
        statuses: Sequence[OrderStatus | Exception],
    ) -> None:
        self.info = SubaccountOrderInfoStub(statuses)
        self._submit = submit
        self._cancels = list(cancels)
        self.submitted_cloid: Cloid | None = None
        self.cancelled_cloids: list[Cloid] = []
        self.cancelled_coins: list[str] = []
        self.mass_cancel_calls = 0

    async def place_limit_order(self, order: PlaceOrderRequest) -> PlaceOrderResponse:
        self.submitted_cloid = order.get("cloid")
        if isinstance(self._submit, Exception):
            raise self._submit
        return self._submit

    async def cancel_by_cloid(self, order: CancelByCloid) -> CancelOrderResponse:
        self.cancelled_cloids.append(order.cloid)
        self.cancelled_coins.append(order.coin)
        result = self._cancels.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    async def cancel_orders(self, orders: Sequence[CancelOrder]) -> CancelOrderResponse:
        self.mass_cancel_calls += 1
        raise AssertionError("subaccount cleanup must be targeted by cloid")


def _order() -> PlaceOrderRequest:
    return {
        "coin": "BTC",
        "is_buy": True,
        "sz": 0.001,
        "px": 50_000.0,
        "is_market": False,
        "order_type": limit_order_type(TimeInForce.ALO),
    }


async def test_cleanup_handles_ambiguous_submit_by_cloid() -> None:
    submit_error = ConnectionError("ambiguous submit")
    client = SubaccountOrderClientStub(submit_error, (_CANCEL_SUCCESS,), ())

    with pytest.raises(ConnectionError) as raised:
        await place_and_assert_order_owner(
            cast(AsyncHyperliquid, client), "test-subaccount", "test-master", _order()
        )

    assert raised.value is submit_error
    assert isinstance(client.submitted_cloid, Cloid)
    assert client.cancelled_cloids == [client.submitted_cloid]
    assert client.mass_cancel_calls == 0


async def test_explicit_submit_rejection_does_not_attempt_cleanup() -> None:
    client = SubaccountOrderClientStub(_ORDER_ERROR_RESPONSE, (), ())

    with pytest.raises(AssertionError, match="Insufficient margin to place order"):
        await place_and_assert_order_owner(
            cast(AsyncHyperliquid, client), "test-subaccount", "test-master", _order()
        )

    assert client.cancelled_cloids == []
    assert client.info.order_status_calls == 0


async def test_cleanup_targets_the_submitted_market() -> None:
    cloid = Cloid.from_int(1)
    client = SubaccountOrderClientStub(_RESTING_RESPONSE, (_CANCEL_SUCCESS,), ())

    await cleanup_order(
        cast(AsyncHyperliquid, client), "test-subaccount", "PURR/USDC", cloid
    )

    assert client.cancelled_coins == ["PURR/USDC"]


async def test_cleanup_retries_once_after_inconclusive_failure() -> None:
    client = SubaccountOrderClientStub(
        _RESTING_RESPONSE,
        (ConnectionError("first cleanup failed"), _CANCEL_SUCCESS),
        (_OPEN_ORDER_STATUS, _UNKNOWN_ORDER_STATUS, _OPEN_ORDER_STATUS),
    )

    await place_and_assert_order_owner(
        cast(AsyncHyperliquid, client), "test-subaccount", "test-master", _order()
    )

    assert isinstance(client.submitted_cloid, Cloid)
    assert client.cancelled_cloids == [client.submitted_cloid, client.submitted_cloid]
    assert client.info.order_status_calls == 3
    assert client.mass_cancel_calls == 0


async def test_cleanup_preserves_original_and_cleanup_failures() -> None:
    submit_error = ValueError("submit failed")
    client = SubaccountOrderClientStub(
        submit_error,
        (ConnectionError("cleanup failed"), ConnectionError("retry failed")),
        (_OPEN_ORDER_STATUS, _OPEN_ORDER_STATUS),
    )

    with pytest.raises(BaseExceptionGroup) as raised:
        await place_and_assert_order_owner(
            cast(AsyncHyperliquid, client), "test-subaccount", "test-master", _order()
        )

    original, cleanup = raised.value.exceptions
    assert original is submit_error
    assert isinstance(cleanup, ExceptionGroup)
    assert sum(isinstance(error, ConnectionError) for error in cleanup.exceptions) == 2
    assert client.cancelled_cloids == [client.submitted_cloid, client.submitted_cloid]
    assert client.info.order_status_calls == 2
    assert client.mass_cancel_calls == 0


async def test_cleanup_second_unknown_is_inconclusive() -> None:
    submit_error = ConnectionError("ambiguous submit")
    client = SubaccountOrderClientStub(
        submit_error,
        (ConnectionError("cleanup failed"), ConnectionError("retry failed")),
        (_UNKNOWN_ORDER_STATUS, _UNKNOWN_ORDER_STATUS),
    )

    with pytest.raises(BaseExceptionGroup) as raised:
        await place_and_assert_order_owner(
            cast(AsyncHyperliquid, client), "test-subaccount", "test-master", _order()
        )

    original, cleanup = raised.value.exceptions
    assert original is submit_error
    assert isinstance(cleanup, ExceptionGroup)
    assert sum(isinstance(error, ConnectionError) for error in cleanup.exceptions) == 2
    assert any(isinstance(error, AssertionError) for error in cleanup.exceptions)
    assert len(client.cancelled_cloids) == 2
    assert client.info.order_status_calls == 2


async def test_cleanup_filled_status_is_failure() -> None:
    client = SubaccountOrderClientStub(
        _RESTING_RESPONSE,
        (ConnectionError("cleanup failed"),),
        (
            _OPEN_ORDER_STATUS,
            _UNKNOWN_ORDER_STATUS,
            _OPEN_ORDER_STATUS,
            _FILLED_ORDER_STATUS,
        ),
    )

    with pytest.raises(ExceptionGroup) as raised:
        await place_and_assert_order_owner(
            cast(AsyncHyperliquid, client), "test-subaccount", "test-master", _order()
        )

    assert any(isinstance(error, AssertionError) for error in raised.value.exceptions)
    assert len(client.cancelled_cloids) == 2
    assert client.info.order_status_calls == 4


async def test_cleanup_non_open_terminal_status_is_complete() -> None:
    client = SubaccountOrderClientStub(
        _RESTING_RESPONSE,
        (ConnectionError("cleanup failed"),),
        (
            _OPEN_ORDER_STATUS,
            _UNKNOWN_ORDER_STATUS,
            _OPEN_ORDER_STATUS,
            _CANCELED_ORDER_STATUS,
        ),
    )

    await place_and_assert_order_owner(
        cast(AsyncHyperliquid, client), "test-subaccount", "test-master", _order()
    )

    assert len(client.cancelled_cloids) == 2
    assert client.info.order_status_calls == 4
