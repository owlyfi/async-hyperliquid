import math
from decimal import ROUND_DOWN, Decimal
from typing import Literal, TypeAlias, cast

from ..errors import ProtocolError
from ..types import JsonValue
from ..types.exchange import ActionResponse
from .encoding import _wire_float


ResponseType: TypeAlias = Literal[
    "order", "cancel", "twapOrder", "twapCancel", "default"
]


def format_token_amount(amount: float, decimals: int) -> str:
    units = amount_in_units(amount, decimals)
    factor = 10**decimals
    whole, fraction = divmod(units, factor)
    if not decimals:
        return str(whole)
    return f"{whole}.{fraction:0{decimals}d}".rstrip("0").rstrip(".")


def amount_in_units(amount: float, decimals: int) -> int:
    if not math.isfinite(amount) or amount <= 0:
        raise ValueError("amount must be finite and greater than zero")
    units = int(
        Decimal(str(amount)).scaleb(decimals).to_integral_value(rounding=ROUND_DOWN)
    )
    if units == 0:
        raise ValueError("amount is below the token precision")
    return units


def exact_signed_units(amount: float, decimals: int) -> int:
    if not math.isfinite(amount):
        raise ValueError("amount must be finite")
    scaled = Decimal(str(amount)).scaleb(decimals)
    integral = scaled.to_integral_value(rounding=ROUND_DOWN)
    if scaled != integral:
        raise ValueError("amount exceeds USD precision")
    return int(integral)


def positive_wire_amount(amount: float) -> str:
    if not math.isfinite(amount) or amount <= 0:
        raise ValueError("amount must be finite and greater than zero")
    return _wire_float(amount)


def _is_error_status(value: JsonValue) -> bool:
    return (
        isinstance(value, dict) and "error" in value and isinstance(value["error"], str)
    )


def _is_order_status(value: JsonValue) -> bool:
    if value in ("waitingForFill", "waitingForTrigger"):
        return True
    if not isinstance(value, dict):
        return False
    discriminators = tuple(
        key for key in ("error", "resting", "filled") if key in value
    )
    if len(discriminators) != 1:
        return False
    if discriminators[0] == "error":
        return _is_error_status(value)
    if discriminators[0] == "resting":
        resting = value["resting"]
        return (
            isinstance(resting, dict)
            and "oid" in resting
            and type(resting["oid"]) is int
        )
    if discriminators[0] == "filled":
        filled = value["filled"]
        return (
            isinstance(filled, dict)
            and all(key in filled for key in ("avgPx", "oid", "totalSz"))
            and isinstance(filled["avgPx"], str)
            and type(filled["oid"]) is int
            and isinstance(filled["totalSz"], str)
        )
    return False


def _is_twap_order_status(value: JsonValue) -> bool:
    if not isinstance(value, dict):
        return False
    discriminators = tuple(key for key in ("error", "running") if key in value)
    if len(discriminators) != 1:
        return False
    if discriminators[0] == "error":
        return _is_error_status(value)
    running = value["running"]
    return (
        isinstance(running, dict)
        and "twapId" in running
        and type(running["twapId"]) is int
    )


def expect_action_response(
    value: JsonValue, expected_type: ResponseType
) -> ActionResponse:
    if not isinstance(value, dict):
        raise ProtocolError("exchange response must be an object")

    status = value.get("status")
    response = value.get("response")
    if status == "err":
        if not isinstance(response, str):
            raise ProtocolError("exchange error response must be a string")
        return cast(ActionResponse, value)

    if status != "ok" or not isinstance(response, dict):
        raise ProtocolError("exchange response has an invalid status")
    if response.get("type") != expected_type:
        raise ProtocolError("exchange response has an unexpected type")

    if expected_type == "default":
        return cast(ActionResponse, value)

    data = response.get("data")
    if not isinstance(data, dict):
        raise ProtocolError("exchange response has malformed data")

    if expected_type in {"order", "cancel"}:
        statuses = data.get("statuses")
        if not isinstance(statuses, list) or not statuses:
            raise ProtocolError("exchange response has malformed statuses")
        if expected_type == "order":
            valid = all(_is_order_status(status) for status in statuses)
        else:
            valid = all(
                status == "success" or _is_error_status(status) for status in statuses
            )
    else:
        twap_status = data.get("status")
        valid = (
            _is_twap_order_status(twap_status)
            if expected_type == "twapOrder"
            else twap_status == "success" or _is_error_status(twap_status)
        )
    if not valid:
        raise ProtocolError("exchange response has a malformed acknowledgement")
    return cast(ActionResponse, value)
