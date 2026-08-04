import math
from typing import cast

from .types import TimeInForce
from .types.exchange import (
    EncodedOrder,
    EncodedOrderType,
    LimitOrderType,
    ModifyOrderRequest,
    PlaceOrderRequest,
)


def _round_float(value: float, decimals: int) -> float:
    return round(float(f"{float(value):.8g}"), decimals)


def _round_price(value: float, decimals: int) -> float | int:
    rounded = _round_float(value, decimals)
    if abs(rounded - round(rounded)) < 1e-12:
        return int(round(rounded))
    if rounded >= 100_000:
        return int(rounded)
    return round(float(f"{rounded:.5g}"), decimals)


def _wire_float(value: float | int) -> str:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("wire number must be finite")
    rounded = f"{number:.8f}"
    if abs(float(rounded) - number) >= 1e-12:
        raise ValueError("wire number exceeds eight decimal places")
    return rounded.rstrip("0").rstrip(".") or "0"


def encode_order(
    order: PlaceOrderRequest | ModifyOrderRequest,
    *,
    asset: int,
    size_decimals: int,
    is_spot: bool,
) -> EncodedOrder:
    price_decimals = (8 if is_spot else 6) - size_decimals
    price = _round_price(order["px"], price_decimals)
    size = _round_float(order["sz"], size_decimals)
    if price <= 0 or size <= 0:
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
        encoded_type = {
            "trigger": {
                "isMarket": trigger["trigger"]["isMarket"],
                "triggerPx": trigger["trigger"]["triggerPx"],
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
