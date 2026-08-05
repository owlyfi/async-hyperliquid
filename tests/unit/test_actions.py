import asyncio
from copy import deepcopy
from typing import Literal, cast

from eth_account import Account
import pytest

import async_hyperliquid.exchange as exchange_module
from async_hyperliquid._internal.http import _HttpTransport
from async_hyperliquid.errors import HttpError, IndeterminateActionError, ProtocolError
from async_hyperliquid.exchange import ExchangeClient
from async_hyperliquid.types import JsonObject, JsonValue, Network
from async_hyperliquid.types.exchange import (
    EncodedCancel,
    EncodedLimitOrderType,
    EncodedOrder,
    EncodedTwapDetails,
    EncodedTwapOrder,
)


ADDRESS = "0x1111111111111111111111111111111111111111"
NONCE = 1_700_000_000_000
ORDER_TYPE = EncodedLimitOrderType(limit={"tif": "Ioc"})
ORDER = EncodedOrder(a=0, b=True, p="100000", s="0.01", r=False, t=ORDER_TYPE)
TWAP = EncodedTwapOrder(a=0, b=True, s="0.01", r=False, m=5, t=False)


class OutcomeTransport:
    def __init__(self, outcome: JsonValue | BaseException) -> None:
        self.outcome = outcome
        self.calls = 0
        self.requests: list[JsonObject] = []

    async def post_json(self, url: str, payload: JsonObject) -> JsonValue:
        self.calls += 1
        self.requests.append(deepcopy(payload))
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        return deepcopy(self.outcome)


def build_exchange(transport: OutcomeTransport) -> ExchangeClient:
    return ExchangeClient(
        cast(_HttpTransport, transport),
        Account.from_key("0x" + "11" * 32),
        account_address=ADDRESS,
        vault_address=None,
        network=Network.MAINNET,
    )


async def test_twap_action_attaches_advanced_details(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = OutcomeTransport(
        {
            "status": "ok",
            "response": {
                "type": "twapOrder",
                "data": {"status": {"running": {"twapId": 1}}},
            },
        }
    )
    client = build_exchange(transport)
    monkeypatch.setattr(exchange_module, "time_ns", lambda: NONCE * 1_000_000)
    details = EncodedTwapDetails(t={"p": "63000", "a": False}, s="65000")

    await client._submit_twap(TWAP, details=details)

    assert transport.requests[0]["action"] == {
        "type": "twapOrder",
        "twap": TWAP,
        "details": {"t": {"p": "63000", "a": False}, "s": "65000"},
    }


@pytest.mark.parametrize(
    "outcome",
    [
        asyncio.TimeoutError(),
        HttpError(),
        HttpError(503),
        ProtocolError("invalid JSON"),
        [],
        {"status": "wat"},
        {"status": "ok", "response": {"type": "cancel", "data": {"statuses": []}}},
    ],
)
async def test_untrusted_action_outcome_is_indeterminate_and_never_retried(
    monkeypatch: pytest.MonkeyPatch, outcome: JsonValue | BaseException
) -> None:
    transport = OutcomeTransport(outcome)
    client = build_exchange(transport)
    monkeypatch.setattr(exchange_module, "time_ns", lambda: NONCE * 1_000_000)

    with pytest.raises(IndeterminateActionError) as caught:
        await client._submit_orders((ORDER,))

    assert caught.value.action_type == "order"
    assert caught.value.nonce == NONCE
    assert transport.calls == 1
    rendered = f"{caught.value!r}\n{caught.value}"
    assert "signature" not in rendered
    assert "orders" not in rendered


async def test_cancellation_is_preserved_and_not_retried(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = OutcomeTransport(asyncio.CancelledError())
    client = build_exchange(transport)
    monkeypatch.setattr(exchange_module, "time_ns", lambda: NONCE * 1_000_000)

    with pytest.raises(asyncio.CancelledError):
        await client._submit_orders((ORDER,))

    assert transport.calls == 1


async def test_trusted_exchange_error_is_returned() -> None:
    transport = OutcomeTransport({"status": "err", "response": "rejected"})
    client = build_exchange(transport)

    assert await client._submit_orders((ORDER,)) == {
        "status": "err",
        "response": "rejected",
    }


@pytest.mark.parametrize(
    "outcome",
    [
        asyncio.TimeoutError(),
        HttpError(503),
        [],
        {"status": "wat"},
        {"status": "ok", "response": {"type": "order"}},
    ],
)
async def test_default_action_failure_is_indeterminate_and_never_retried(
    monkeypatch: pytest.MonkeyPatch, outcome: JsonValue | BaseException
) -> None:
    transport = OutcomeTransport(outcome)
    client = build_exchange(transport)
    monkeypatch.setattr(exchange_module, "time_ns", lambda: NONCE * 1_000_000)

    with pytest.raises(IndeterminateActionError) as caught:
        await client.claim_rewards()

    assert caught.value.action_type == "claimRewards"
    assert transport.calls == 1


@pytest.mark.parametrize(
    ("action_kind", "outcome"),
    [
        ("order", {"status": "ok", "response": {"type": "order"}}),
        (
            "order",
            {
                "status": "ok",
                "response": {
                    "type": "order",
                    "data": {"statuses": [{"resting": {"oid": True}}]},
                },
            },
        ),
        (
            "order",
            {
                "status": "ok",
                "response": {
                    "type": "order",
                    "data": {
                        "statuses": [
                            {"filled": {"avgPx": 100, "oid": 1, "totalSz": "0.01"}}
                        ]
                    },
                },
            },
        ),
        (
            "cancel",
            {"status": "ok", "response": {"type": "cancel", "data": {"statuses": [1]}}},
        ),
        (
            "twapOrder",
            {
                "status": "ok",
                "response": {
                    "type": "twapOrder",
                    "data": {"status": {"running": {"twapId": "1"}}},
                },
            },
        ),
        (
            "twapCancel",
            {
                "status": "ok",
                "response": {"type": "twapCancel", "data": {"status": {"error": 1}}},
            },
        ),
    ],
)
async def test_malformed_success_acknowledgement_is_indeterminate(
    monkeypatch: pytest.MonkeyPatch,
    action_kind: Literal["order", "cancel", "twapOrder", "twapCancel"],
    outcome: JsonValue,
) -> None:
    transport = OutcomeTransport(outcome)
    client = build_exchange(transport)
    monkeypatch.setattr(exchange_module, "time_ns", lambda: NONCE * 1_000_000)

    with pytest.raises(IndeterminateActionError):
        if action_kind == "order":
            await client._submit_orders((ORDER,))
        elif action_kind == "cancel":
            await client._submit_cancels((EncodedCancel(a=0, o=1),))
        elif action_kind == "twapOrder":
            await client._submit_twap(TWAP)
        else:
            await client._submit_twap_cancel(0, 1)

    assert transport.calls == 1


@pytest.mark.parametrize(
    ("action_kind", "outcome"),
    [
        (
            "order",
            {
                "status": "ok",
                "response": {
                    "type": "order",
                    "data": {
                        "statuses": [
                            {
                                "resting": {"oid": 1, "serverMeta": "v2"},
                                "serverMeta": "v2",
                            }
                        ]
                    },
                },
            },
        ),
        (
            "order",
            {
                "status": "ok",
                "response": {
                    "type": "order",
                    "data": {
                        "statuses": [
                            {
                                "filled": {
                                    "avgPx": "100",
                                    "oid": 1,
                                    "totalSz": "0.01",
                                    "serverMeta": "v2",
                                }
                            }
                        ]
                    },
                },
            },
        ),
        (
            "cancel",
            {
                "status": "ok",
                "response": {
                    "type": "cancel",
                    "data": {"statuses": [{"error": "not found", "code": 404}]},
                },
            },
        ),
        (
            "twapOrder",
            {
                "status": "ok",
                "response": {
                    "type": "twapOrder",
                    "data": {
                        "status": {
                            "running": {"twapId": 1, "serverMeta": "v2"},
                            "serverMeta": "v2",
                        }
                    },
                },
            },
        ),
        (
            "twapCancel",
            {
                "status": "ok",
                "response": {
                    "type": "twapCancel",
                    "data": {"status": {"error": "not found", "code": 404}},
                },
            },
        ),
    ],
)
async def test_success_acknowledgement_allows_additive_fields(
    action_kind: Literal["order", "cancel", "twapOrder", "twapCancel"],
    outcome: JsonValue,
) -> None:
    transport = OutcomeTransport(outcome)
    client = build_exchange(transport)

    if action_kind == "order":
        result = await client._submit_orders((ORDER,))
    elif action_kind == "cancel":
        result = await client._submit_cancels((EncodedCancel(a=0, o=1),))
    elif action_kind == "twapOrder":
        result = await client._submit_twap(TWAP)
    else:
        result = await client._submit_twap_cancel(0, 1)

    assert result == outcome
    assert transport.calls == 1


@pytest.mark.parametrize("status", ["waitingForFill", "waitingForTrigger"])
async def test_order_acknowledgement_accepts_string_status(status: str) -> None:
    outcome: JsonValue = {
        "status": "ok",
        "response": {
            "type": "order",
            "data": {"statuses": [{"resting": {"oid": 1}}, status]},
        },
    }
    transport = OutcomeTransport(outcome)
    client = build_exchange(transport)

    result = await client._submit_orders((ORDER,))

    assert result == outcome
    assert transport.calls == 1


async def test_concurrent_nonces_are_unique_when_clock_repeats(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = OutcomeTransport(
        {
            "status": "ok",
            "response": {
                "type": "order",
                "data": {"statuses": [{"resting": {"oid": 1}}]},
            },
        }
    )
    client = build_exchange(transport)
    monkeypatch.setattr(exchange_module, "time_ns", lambda: NONCE * 1_000_000)

    results = await asyncio.gather(
        *(client._submit_orders((ORDER,)) for _ in range(20))
    )

    assert len(results) == 20
    assert transport.calls == 20
    assert sorted(cast(int, request["nonce"]) for request in transport.requests) == [
        NONCE + offset for offset in range(20)
    ]
