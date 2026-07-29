from dataclasses import FrozenInstanceError, fields

import pytest

from async_hyperliquid.types import (
    BuilderFee,
    CancelByCloid,
    CancelOrder,
    Cloid,
    LimitOrder,
    MarketOrder,
    ModifyOrder,
    Side,
    TimeInForce,
    TriggerKind,
    TriggerOrder,
)


def test_limit_order_is_small_immutable_and_wire_independent() -> None:
    order = LimitOrder(coin="BTC", side=Side.BUY, size=0.01, price=100_000.0)

    assert order.time_in_force is TimeInForce.GTC
    assert order.reduce_only is False
    assert order.client_order_id is None
    assert not hasattr(order, "__dict__")
    assert "builder_fee" not in {field.name for field in fields(order)}
    with pytest.raises(FrozenInstanceError):
        order.price = 1.0


def test_reusable_commands_do_not_use_an_inheritance_hierarchy() -> None:
    for command in (
        LimitOrder,
        TriggerOrder,
        MarketOrder,
        CancelOrder,
        CancelByCloid,
        ModifyOrder,
        BuilderFee,
    ):
        assert command.__bases__ == (object,)


@pytest.mark.parametrize("value", [0.0, -1.0, float("inf"), float("nan")])
def test_limit_order_requires_positive_finite_size_and_price(value: float) -> None:
    with pytest.raises(ValueError):
        LimitOrder(coin="BTC", side=Side.BUY, size=value, price=1.0)
    with pytest.raises(ValueError):
        LimitOrder(coin="BTC", side=Side.BUY, size=1.0, price=value)


def test_trigger_and_modify_commands_compose_without_wrappers() -> None:
    trigger = TriggerOrder(
        coin="BTC",
        side=Side.SELL,
        size=0.01,
        price=99_000.0,
        trigger_price=100_000.0,
        trigger_kind=TriggerKind.STOP_LOSS,
    )
    command = ModifyOrder(order_id=123, order=trigger)

    assert command.order is trigger
    assert command.order_id == 123


@pytest.mark.parametrize("slippage", [-0.1, 1.1, float("inf"), float("nan")])
def test_market_order_rejects_invalid_slippage(slippage: float) -> None:
    with pytest.raises(ValueError):
        MarketOrder(coin="ETH", side=Side.BUY, size=0.1, slippage=slippage)


def test_cancel_by_cloid_keeps_the_validated_string() -> None:
    cloid = Cloid("0x" + "12" * 16)

    cancel = CancelByCloid(coin="BTC", client_order_id=cloid)

    assert cancel.client_order_id is cloid


def test_integer_wire_values_reject_negative_numbers() -> None:
    order = LimitOrder("BTC", Side.BUY, 0.01, 100_000.0)

    with pytest.raises(ValueError):
        CancelOrder("BTC", -1)
    with pytest.raises(ValueError):
        ModifyOrder(-1, order)
    with pytest.raises(ValueError):
        BuilderFee("0x1111111111111111111111111111111111111111", -1)
