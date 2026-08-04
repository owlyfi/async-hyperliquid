import asyncio
from copy import deepcopy
from typing import Literal, cast

from eth_account import Account
import pytest

import async_hyperliquid.exchange as exchange_module
from async_hyperliquid._http import _HttpTransport
from async_hyperliquid.errors import HttpError, IndeterminateActionError, ProtocolError
from async_hyperliquid.exchange import ExchangeClient
from async_hyperliquid.info import InfoClient
from async_hyperliquid.types import (
    CancelOrder,
    JsonObject,
    JsonValue,
    LimitOrder,
    Network,
    Side,
)
from async_hyperliquid.types.info import Position, SpotToken


ADDRESS = "0x1111111111111111111111111111111111111111"
NONCE = 1_700_000_000_000


class StubInfo:
    async def _market_info(self, coin: str) -> tuple[int, int]:
        return 0, 5

    async def _market_infos(
        self, coins: tuple[str, ...]
    ) -> tuple[tuple[int, int], ...]:
        return tuple((0, 5) for _ in coins)

    async def asset_id(self, coin: str) -> int:
        return (await self._market_info(coin))[0]

    async def mid_price(self, coin: str) -> float:
        return 100.0

    async def positions(
        self, account_address: str, *, perp_dexes: tuple[str, ...] = ("",)
    ) -> list[Position]:
        return []

    async def spot_token_metadata(self, coin: str) -> SpotToken:
        raise AssertionError("not used")


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
        cast(InfoClient, StubInfo()),
        Account.from_key("0x" + "11" * 32),
        account_address=ADDRESS,
        vault_address=None,
        network=Network.MAINNET,
    )


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
        await client.place_limit_order(LimitOrder("BTC", Side.BUY, 0.01, 100_000))

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
        await client.place_limit_order(LimitOrder("BTC", Side.BUY, 0.01, 100_000))

    assert transport.calls == 1


async def test_trusted_exchange_error_is_returned() -> None:
    transport = OutcomeTransport({"status": "err", "response": "rejected"})
    client = build_exchange(transport)

    assert await client.place_limit_order(
        LimitOrder("BTC", Side.BUY, 0.01, 100_000)
    ) == {"status": "err", "response": "rejected"}


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
            await client.place_limit_order(LimitOrder("BTC", Side.BUY, 0.01, 100_000))
        elif action_kind == "cancel":
            await client.cancel_orders((CancelOrder("BTC", 1),))
        elif action_kind == "twapOrder":
            await client.place_twap("BTC", Side.BUY, 0.01, 5)
        else:
            await client.cancel_twap("BTC", 1)

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
        result = await client.place_limit_order(
            LimitOrder("BTC", Side.BUY, 0.01, 100_000)
        )
    elif action_kind == "cancel":
        result = await client.cancel_orders((CancelOrder("BTC", 1),))
    elif action_kind == "twapOrder":
        result = await client.place_twap("BTC", Side.BUY, 0.01, 5)
    else:
        result = await client.cancel_twap("BTC", 1)

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
        *(
            client.place_limit_order(LimitOrder("BTC", Side.BUY, 0.01, 100_000))
            for _ in range(20)
        )
    )

    assert len(results) == 20
    assert transport.calls == 20
    assert sorted(cast(int, request["nonce"]) for request in transport.requests) == [
        NONCE + offset for offset in range(20)
    ]
