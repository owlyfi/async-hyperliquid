from typing import cast

import pytest

from async_hyperliquid._internal.http import _HttpTransport
from async_hyperliquid.info import InfoClient
from async_hyperliquid.types import JsonObject, JsonValue
from tests.integration import test_info as live_tests
from tests.integration.info_client import IntegrationInfoClient
from tests.unit.test_info import ADDRESS, RecordingTransport, load_responses


def fills(*entries: tuple[int, int]) -> list[JsonValue]:
    fill = cast(JsonObject, cast(list[JsonValue], load_responses()["userFills"])[0])
    return [dict(fill, time=time, tid=tid) for time, tid in entries]


RECENT = fills((4, 40), (3, 30), (3, 31), (2, 20), (1, 10))
REVERSED = fills((3, 31), (3, 30), (2, 20))


def client(transport: RecordingTransport) -> IntegrationInfoClient:
    return cast(
        IntegrationInfoClient,
        InfoClient._from_transport(
            cast(_HttpTransport, transport), info_url="https://provider.example/info"
        ),
    )


async def test_reversed_live_check_uses_complete_reference_window() -> None:
    transport = RecordingTransport({"userFills": RECENT, "userFillsByTime": REVERSED})

    await live_tests.test_user_fills_reversed(client(transport), ADDRESS)

    assert transport.requests[-1][1] == {
        "type": "userFillsByTime",
        "user": ADDRESS,
        "aggregateByTime": False,
        "startTime": 2,
        "endTime": 3,
        "reversed": True,
    }


@pytest.mark.parametrize(
    "response",
    [
        pytest.param([], id="empty"),
        pytest.param([{}], id="malformed-single"),
        pytest.param(fills((1, 10), (0, 0)), id="old-descending-page"),
        pytest.param(fills((3, 30)), id="missing-fills"),
        pytest.param(fills((2, 20), (3, 30), (3, 31)), id="wrong-direction"),
        pytest.param(fills((4, 31), (3, 30), (2, 20)), id="outside-window"),
        pytest.param(fills((3, 30), (3, 30), (2, 20)), id="duplicate-fill"),
    ],
)
async def test_reversed_live_check_rejects_wrong_page(response: JsonValue) -> None:
    transport = RecordingTransport({"userFills": RECENT, "userFillsByTime": response})

    with pytest.raises((AssertionError, KeyError)):
        await live_tests.test_user_fills_reversed(client(transport), ADDRESS)


@pytest.mark.parametrize(
    "reference", [[], fills((4, 40)), fills((4, 40), (3, 30), (2, 20))]
)
async def test_reversed_live_check_skips_incomplete_reference(
    reference: JsonValue,
) -> None:
    transport = RecordingTransport({"userFills": reference, "userFillsByTime": []})

    with pytest.raises(pytest.skip.Exception):
        await live_tests.test_user_fills_reversed(client(transport), ADDRESS)
    assert [payload["type"] for _, payload in transport.requests] == ["userFills"]
