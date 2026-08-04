import asyncio
from collections.abc import Sequence

from ..errors import ProtocolError
from ..types import JsonObject, JsonValue


def expect_object(value: JsonValue, request_type: str) -> JsonObject:
    if not isinstance(value, dict):
        raise ProtocolError(f"{request_type} response must be an object")
    return value


def expect_optional_object(value: JsonValue, request_type: str) -> JsonObject | None:
    if value is None:
        return None
    return expect_object(value, request_type)


def expect_list(value: JsonValue, request_type: str) -> list[JsonValue]:
    if not isinstance(value, list):
        raise ProtocolError(f"{request_type} response must be a list")
    return value


def expect_optional_list(value: JsonValue, request_type: str) -> list[JsonValue] | None:
    if value is None:
        return None
    return expect_list(value, request_type)


def expect_bool(value: JsonValue, request_type: str) -> bool:
    if not isinstance(value, bool):
        raise ProtocolError(f"{request_type} response must be a boolean")
    return value


def expect_int(value: JsonValue, request_type: str) -> int:
    if type(value) is not int:
        raise ProtocolError(f"{request_type} response must be an integer")
    return value


def expect_string(value: JsonValue, request_type: str) -> str:
    if not isinstance(value, str):
        raise ProtocolError(f"{request_type} response must be a string")
    return value


def expect_pair(
    value: JsonValue, request_type: str
) -> tuple[JsonObject, list[JsonValue]]:
    pair = expect_list(value, request_type)
    if len(pair) != 2:
        raise ProtocolError(f"{request_type} response must contain two items")
    return (expect_object(pair[0], request_type), expect_list(pair[1], request_type))


async def wait_for_tasks(tasks: Sequence[asyncio.Task[object]]) -> None:
    try:
        await asyncio.gather(*tasks)
    except BaseException:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise


def context_price(
    contexts: list[JsonValue], index: int, field: str, request_type: str
) -> float:
    if not 0 <= index < len(contexts):
        raise ProtocolError(f"{request_type} is missing a market context")
    context = expect_object(contexts[index], request_type)
    return price_from_context(context, field, request_type)


def context_price_by_coin(
    contexts: list[JsonValue], coin: str, field: str, request_type: str
) -> float:
    for value in contexts:
        context = expect_object(value, request_type)
        if context.get("coin") == coin:
            return price_from_context(context, field, request_type)
    raise ProtocolError(f"{request_type} is missing a market context for {coin}")


def price_from_context(context: JsonObject, field: str, request_type: str) -> float:
    value = context.get(field)
    if not isinstance(value, str):
        raise ProtocolError(f"{request_type} contains a malformed price")
    try:
        return float(value)
    except ValueError:
        raise ProtocolError(f"{request_type} contains an invalid price") from None
