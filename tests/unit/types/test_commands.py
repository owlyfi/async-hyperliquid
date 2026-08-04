from dataclasses import FrozenInstanceError

import pytest

import async_hyperliquid.types as types
from async_hyperliquid.types import (
    BaseOrderRequest,
    Builder,
    CancelByCloid,
    CancelOrder,
    Cloid,
    ModifyOrderRequest,
    PlaceOrderRequest,
    TimeInForce,
    TriggerKind,
    limit_order_type,
    trigger_order_type,
)


def test_limit_order_option_uses_the_documented_nested_contract() -> None:
    assert limit_order_type(TimeInForce.GTC) == {"limit": {"tif": "Gtc"}}


def test_trigger_order_option_uses_the_documented_nested_contract() -> None:
    assert trigger_order_type(
        is_market=True, trigger_px="101500.25", tpsl=TriggerKind.TAKE_PROFIT
    ) == {"trigger": {"isMarket": True, "triggerPx": "101500.25", "tpsl": "tp"}}


def test_place_and_modify_requests_share_one_base_vocabulary() -> None:
    cloid = Cloid("0x" + "12" * 16)
    place: PlaceOrderRequest = {
        "coin": "BTC",
        "is_buy": True,
        "sz": 0.01,
        "px": 100_000.0,
        "cloid": cloid,
        "is_market": False,
        "ro": False,
        "order_type": limit_order_type(TimeInForce.ALO),
    }
    modify: ModifyOrderRequest = {
        "coin": "BTC",
        "is_buy": False,
        "sz": 0.02,
        "px": 99_000.0,
        "cloid": cloid,
        "oid": 42,
        "ro": True,
    }
    base_place: BaseOrderRequest = place
    base_modify: BaseOrderRequest = modify

    assert tuple(base_place)[:5] == ("coin", "is_buy", "sz", "px", "cloid")
    assert base_modify["cloid"] is cloid


def test_builder_is_a_small_immutable_value() -> None:
    builder = Builder(
        address="0x1111111111111111111111111111111111111111", fee_tenths_bps=55
    )

    assert not hasattr(builder, "__dict__")
    with pytest.raises(FrozenInstanceError):
        builder.fee_tenths_bps = 1


def test_builder_rejects_negative_fee() -> None:
    with pytest.raises(ValueError, match="fee_tenths_bps"):
        Builder(address="0x1111111111111111111111111111111111111111", fee_tenths_bps=-1)


def test_cancel_commands_use_protocol_identifier_names() -> None:
    cloid = Cloid("0x" + "12" * 16)

    cancel = CancelOrder(coin="BTC", oid=7)
    cancel_by_cloid = CancelByCloid(coin="BTC", cloid=cloid)

    assert cancel.oid == 7
    assert cancel_by_cloid.cloid is cloid


def test_order_input_side_enum_is_not_part_of_the_public_api() -> None:
    assert "Side" not in types.__all__
    assert not hasattr(types, "Side")


def test_redundant_order_command_classes_are_not_exported() -> None:
    for name in ("LimitOrder", "TriggerOrder", "MarketOrder", "ModifyOrder"):
        assert name not in types.__all__
        assert not hasattr(types, name)
