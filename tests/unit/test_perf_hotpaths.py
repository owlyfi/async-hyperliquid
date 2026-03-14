import asyncio
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest

from async_hyperliquid import AsyncHyperliquid
from async_hyperliquid.utils.constants import SPOT_OFFSET


def build_stub_hl() -> Any:
    return cast(Any, object.__new__(AsyncHyperliquid))


class StartBarrier:
    def __init__(self, required: int) -> None:
        self.required = required
        self.started = 0
        self._ready = asyncio.Event()

    async def wait(self) -> None:
        self.started += 1
        if self.started >= self.required:
            self._ready.set()
        await asyncio.wait_for(self._ready.wait(), timeout=0.1)


@pytest.mark.asyncio
async def test_get_metas_fetches_spot_and_perp_concurrently() -> None:
    hl = build_stub_hl()
    barrier = StartBarrier(required=2)

    async def get_perp_meta() -> dict[str, list[dict[str, str]]]:
        await barrier.wait()
        return {"universe": [{"name": "BTC"}]}

    async def get_spot_meta() -> dict[str, list[Any]]:
        await barrier.wait()
        return {"universe": [], "tokens": []}

    hl.info = SimpleNamespace(get_perp_meta=get_perp_meta, get_spot_meta=get_spot_meta)

    metas = await hl.get_metas()

    assert metas["perp"] == {"universe": [{"name": "BTC"}]}
    assert metas["spot"] == {"universe": [], "tokens": []}


@pytest.mark.asyncio
async def test_get_all_metas_fetches_base_and_dex_metas_concurrently() -> None:
    hl = build_stub_hl()
    phase_one = StartBarrier(required=3)
    phase_two = StartBarrier(required=2)

    async def get_all_dex_name() -> list[str]:
        await phase_one.wait()
        return ["", "dex-a", "dex-b"]

    async def get_perp_meta(dex: str = "") -> dict[str, list[dict[str, str]]]:
        if dex:
            await phase_two.wait()
            return {"universe": [{"name": dex.upper()}]}
        await phase_one.wait()
        return {"universe": [{"name": "BTC"}]}

    async def get_spot_meta() -> dict[str, list[Any]]:
        await phase_one.wait()
        return {"universe": [], "tokens": []}

    hl.get_all_dex_name = get_all_dex_name
    hl.info = SimpleNamespace(get_perp_meta=get_perp_meta, get_spot_meta=get_spot_meta)

    metas = await hl.get_all_metas()

    assert metas["perp"] == {"universe": [{"name": "BTC"}]}
    assert metas["spot"] == {"universe": [], "tokens": []}
    assert metas["dexs"] == {
        "dex-a": {"universe": [{"name": "DEX-A"}]},
        "dex-b": {"universe": [{"name": "DEX-B"}]},
    }


@pytest.mark.asyncio
async def test_get_all_market_prices_fetches_both_contexts_concurrently() -> None:
    hl = build_stub_hl()
    barrier = StartBarrier(required=2)
    init_metas = AsyncMock()
    setattr(hl, "init_metas", init_metas)
    setattr(hl, "coin_assets", {"BTC": 0, "PURR/USDC": SPOT_OFFSET})

    async def get_spot_meta_ctx() -> tuple[dict[str, Any], list[dict[str, str]]]:
        await barrier.wait()
        return ({"universe": []}, [{"markPx": "1.25"}])

    async def get_perp_meta_ctx() -> tuple[dict[str, Any], list[dict[str, str]]]:
        await barrier.wait()
        return ({"universe": []}, [{"markPx": "105000"}])

    hl.info = SimpleNamespace(
        get_spot_meta_ctx=get_spot_meta_ctx, get_perp_meta_ctx=get_perp_meta_ctx
    )

    prices = await hl.get_all_market_prices()

    init_metas.assert_awaited_once()
    assert prices == {"BTC": 105000.0, "PURR/USDC": 1.25}


@pytest.mark.asyncio
async def test_get_coin_sz_decimals_resolves_coin_name_once() -> None:
    hl = build_stub_hl()
    get_coin_name = AsyncMock(return_value="BTC")
    setattr(hl, "get_coin_name", get_coin_name)
    setattr(hl, "coin_assets", {"BTC": 7})
    setattr(hl, "asset_sz_decimals", {7: 4})

    sz_decimals = await hl.get_coin_sz_decimals("BTC")

    assert sz_decimals == 4
    get_coin_name.assert_awaited_once_with("BTC")


@pytest.mark.asyncio
async def test_cancel_orders_resolves_assets_concurrently() -> None:
    hl = build_stub_hl()
    barrier = StartBarrier(required=3)

    async def get_coin_asset(coin: str) -> int:
        await barrier.wait()
        return {"BTC": 1, "ETH": 2, "SOL": 3}[coin]

    exchange = SimpleNamespace(post_action=AsyncMock(return_value={"status": "ok"}))
    setattr(hl, "get_coin_asset", get_coin_asset)
    setattr(hl, "exchange", exchange)
    setattr(hl, "vault", None)
    setattr(hl, "expires", None)

    resp = await hl.cancel_orders([("BTC", 1), ("ETH", 2), ("SOL", 3)])

    assert resp == {"status": "ok"}
    exchange.post_action.assert_awaited_once_with(
        {
            "type": "cancel",
            "cancels": [{"a": 1, "o": 1}, {"a": 2, "o": 2}, {"a": 3, "o": 3}],
        },
        vault=None,
        expires=None,
    )
