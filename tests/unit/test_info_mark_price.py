from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest

from async_hyperliquid import AsyncHyperliquid
from async_hyperliquid.utils.constants import SPOT_OFFSET


def build_stub_hl() -> Any:
    return cast(Any, object.__new__(AsyncHyperliquid))


@pytest.mark.asyncio
async def test_get_mark_price_reads_base_perp_ctx() -> None:
    hl = build_stub_hl()
    setattr(hl, "coin_assets", {"BTC": 0})
    setattr(hl, "get_coin_name", AsyncMock(return_value="BTC"))

    get_perp_meta_ctx = AsyncMock(
        return_value=[
            {"universe": [{"name": "BTC", "szDecimals": 5, "maxLeverage": 50}]},
            [{"markPx": "105000"}],
        ]
    )
    get_spot_meta_ctx = AsyncMock()
    hl.info = SimpleNamespace(
        get_perp_meta_ctx=get_perp_meta_ctx, get_spot_meta_ctx=get_spot_meta_ctx
    )

    mark_px = await hl.get_mark_price("BTC")

    assert mark_px == 105000.0
    hl.get_coin_name.assert_awaited_once_with("BTC")
    get_perp_meta_ctx.assert_awaited_once_with("")
    get_spot_meta_ctx.assert_not_called()


@pytest.mark.asyncio
async def test_get_mark_price_reads_spot_ctx() -> None:
    hl = build_stub_hl()
    setattr(hl, "coin_assets", {"@142": SPOT_OFFSET + 142})
    setattr(hl, "get_coin_name", AsyncMock(return_value="@142"))

    get_perp_meta_ctx = AsyncMock()
    get_spot_meta_ctx = AsyncMock(
        return_value=[
            {
                "tokens": [],
                "universe": [
                    {
                        "name": "@142",
                        "tokens": (197, 0),
                        "index": 2,
                        "isCanonical": False,
                    }
                ],
            },
            [{"markPx": "1.11"}, {"markPx": "2.22"}, {"markPx": "101000"}],
        ]
    )
    hl.info = SimpleNamespace(
        get_perp_meta_ctx=get_perp_meta_ctx, get_spot_meta_ctx=get_spot_meta_ctx
    )

    mark_px = await hl.get_mark_price("UBTC/USDC")

    assert mark_px == 101000.0
    hl.get_coin_name.assert_awaited_once_with("UBTC/USDC")
    get_spot_meta_ctx.assert_awaited_once_with()
    get_perp_meta_ctx.assert_not_called()


@pytest.mark.asyncio
async def test_get_mark_price_reads_external_dex_ctx_without_meta_cache() -> None:
    hl = build_stub_hl()

    get_perp_meta_ctx = AsyncMock(
        return_value=[
            {"universe": [{"name": "xyz:NVDA", "szDecimals": 3, "maxLeverage": 10}]},
            [{"markPx": "177.06"}],
        ]
    )
    hl.info = SimpleNamespace(
        get_perp_meta_ctx=get_perp_meta_ctx, get_spot_meta_ctx=AsyncMock()
    )

    mark_px = await hl.get_mark_price("xyz:NVDA")

    assert mark_px == 177.06
    get_perp_meta_ctx.assert_awaited_once_with("xyz")


@pytest.mark.asyncio
async def test_get_market_price_delegates_to_get_mark_price() -> None:
    hl = build_stub_hl()
    get_mark_price = AsyncMock(return_value=123.45)
    setattr(hl, "get_mark_price", get_mark_price)

    mark_px = await hl.get_market_price("BTC")

    assert mark_px == 123.45
    get_mark_price.assert_awaited_once_with("BTC")
