import math
from typing import cast

from ..constants import OUTCOME_MAX_PRICE, OUTCOME_MIN_PRICE, OUTCOME_PRICE_DECIMALS
from ..types import TimeInForce
from ..types.exchange import (
    EncodedOrder,
    EncodedOrderType,
    LimitOrderType,
    ModifyOrderRequest,
    PlaceOrderRequest,
)


def _round_size(value: float, size_decimals: int) -> float | int:
    rounded = round(float(value), size_decimals)
    return int(rounded) if rounded.is_integer() else rounded


def _round_price(value: float, max_decimals: int) -> float | int:
    number = float(value)
    if number.is_integer():
        return int(number)
    rounded = round(float(f"{number:.5g}"), max_decimals)
    return int(rounded) if rounded.is_integer() else rounded


def _wire_float(value: float | int) -> str:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("wire number must be finite")
    rounded = f"{number:.8f}"
    if abs(float(rounded) - number) >= 1e-12:
        raise ValueError("wire number exceeds eight decimal places")
    return rounded.rstrip("0").rstrip(".") or "0"


def _normalize_price(
    value: float | str, *, max_decimals: int, is_outcome: bool
) -> float | int:
    price = float(value)
    if is_outcome and not OUTCOME_MIN_PRICE <= price <= OUTCOME_MAX_PRICE:
        raise ValueError("outcome price must be between 0.00001 and 0.99999 USDC")
    rounded = _round_price(
        price, OUTCOME_PRICE_DECIMALS if is_outcome else max_decimals
    )
    if rounded <= 0:
        raise ValueError("order value is below market precision")
    return rounded


def encode_order(
    order: PlaceOrderRequest | ModifyOrderRequest,
    *,
    asset: int,
    size_decimals: int,
    is_spot: bool,
    is_outcome: bool,
) -> EncodedOrder:
    max_decimals = (8 if is_spot else 6) - size_decimals
    price = _normalize_price(
        order["px"], max_decimals=max_decimals, is_outcome=is_outcome
    )
    size = _round_size(order["sz"], size_decimals)
    if size <= 0:
        raise ValueError("order value is below market precision")

    order_type = order.get("order_type")
    encoded_type: EncodedOrderType
    if order_type is None:
        encoded_type = {"limit": {"tif": TimeInForce.IOC.value}}
    elif "limit" in order_type:
        limit = cast(LimitOrderType, order_type)
        encoded_type = {"limit": {"tif": limit["limit"]["tif"].value}}
    else:
        trigger = order_type
        trigger_price = _normalize_price(
            trigger["trigger"]["triggerPx"],
            max_decimals=max_decimals,
            is_outcome=is_outcome,
        )
        encoded_type = {
            "trigger": {
                "isMarket": trigger["trigger"]["isMarket"],
                "triggerPx": _wire_float(trigger_price),
                "tpsl": trigger["trigger"]["tpsl"],
            }
        }

    encoded: EncodedOrder = {
        "a": asset,
        "b": order["is_buy"],
        "p": _wire_float(price),
        "s": _wire_float(size),
        "r": order.get("ro", False),
        "t": encoded_type,
    }
    cloid = order.get("cloid")
    if cloid is not None:
        encoded["c"] = str(cloid)
    return encoded
