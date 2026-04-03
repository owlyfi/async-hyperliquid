from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest

from async_hyperliquid import AsyncHyperliquid
from async_hyperliquid.info import InfoAPI


def build_stub_hl() -> Any:
    session = cast(Any, SimpleNamespace(closed=False, close=AsyncMock()))
    return AsyncHyperliquid(
        "0x1111111111111111111111111111111111111111",
        "0x" + ("11" * 32),
        session=session,
    )


@pytest.mark.asyncio
async def test_info_api_get_all_perp_metas_posts_expected_payload() -> None:
    session = cast(Any, SimpleNamespace())
    api = InfoAPI("https://api.example.com", session)
    post = AsyncMock(return_value=[{"universe": []}])
    api.post = post  # type: ignore[method-assign]

    resp = await api.get_all_perp_metas()

    assert resp == [{"universe": []}]
    post.assert_awaited_once_with({"type": "allPerpMetas"})


@pytest.mark.asyncio
async def test_get_supported_quote_assets_collects_unique_quote_tokens() -> None:
    hl = build_stub_hl()
    get_spot_meta = AsyncMock(
        return_value={
            "tokens": [{"name": "USDC"}, {"name": "USDT0"}, {"name": "USDH"}],
            "universe": [
                {"tokens": (4, 0)},
                {"tokens": (5, 1)},
                {"tokens": (6, 0)},
                {"tokens": (7, 2)},
            ],
        }
    )
    hl.info = SimpleNamespace(get_spot_meta=get_spot_meta)

    quote_assets = await hl.get_supported_quote_assets()

    assert quote_assets == {"USDC", "USDT0", "USDH"}
    get_spot_meta.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_get_hip3_dex_quote_assets_maps_dexs_to_collateral_tokens() -> None:
    hl = build_stub_hl()
    get_spot_meta = AsyncMock(
        return_value={
            "tokens": [{"name": "USDC"}, {"name": "USDT0"}, {"name": "USDH"}],
            "universe": [],
        }
    )
    get_all_perp_metas = AsyncMock(
        return_value=[
            {"universe": [{"name": "BTC"}]},
            {"universe": [{"name": "xyz:NVDA"}], "collateralToken": 0},
            {"universe": [{"name": "flx:TSLA"}], "collateralToken": 1},
            {"universe": [{"name": "vntl:OPENAI"}], "collateralToken": 2},
        ]
    )
    hl.info = SimpleNamespace(
        get_spot_meta=get_spot_meta, get_all_perp_metas=get_all_perp_metas
    )

    dex_quote_assets = await hl.get_hip3_dex_quote_assets()

    assert dex_quote_assets == {"xyz": "USDC", "flx": "USDT0", "vntl": "USDH"}
    get_spot_meta.assert_awaited_once_with()
    get_all_perp_metas.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_get_hip3_dex_quote_assets_skips_malformed_metadata() -> None:
    hl = build_stub_hl()
    hl.info = SimpleNamespace(
        get_spot_meta=AsyncMock(
            return_value={"tokens": [{"name": "USDC"}], "universe": []}
        ),
        get_all_perp_metas=AsyncMock(
            return_value=[
                {"universe": [{"name": "BTC"}]},
                {"universe": [], "collateralToken": 0},
                {"universe": [{"name": "xyz:NVDA"}]},
                {"universe": [{"name": "flx:TSLA"}], "collateralToken": 9},
                {"universe": [{"name": "vntl:OPENAI"}], "collateralToken": 0},
            ]
        ),
    )

    dex_quote_assets = await hl.get_hip3_dex_quote_assets()

    assert dex_quote_assets == {"vntl": "USDC"}
