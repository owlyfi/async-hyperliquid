import asyncio
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from async_hyperliquid import AsyncHyperliquid
from async_hyperliquid.utils.constants import PERP_DEX_OFFSET, SPOT_OFFSET


def build_stub_hl() -> Any:
    session = SimpleNamespace(closed=False, close=AsyncMock())
    return AsyncHyperliquid(
        "0x1111111111111111111111111111111111111111",
        "0x" + ("11" * 32),
        session=session,  # type: ignore[arg-type]
    )


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


def init_spot_meta_stub() -> Any:
    hl = build_stub_hl()
    setattr(hl, "coin_assets", {})
    setattr(hl, "coin_names", {})
    setattr(hl, "coin_symbols", {})
    setattr(hl, "asset_sz_decimals", {})
    setattr(hl, "spot_tokens", {})
    return hl


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

    async def get_perp_meta(dex: str = "") -> dict[str, Any]:
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
async def test_experimental_get_all_metas_fetches_aggregated_perp_metas_concurrently() -> (
    None
):
    hl = build_stub_hl()
    barrier = StartBarrier(required=2)

    async def get_all_perp_metas() -> list[dict[str, Any]]:
        await barrier.wait()
        return [
            {"universe": [{"name": "BTC"}]},
            {"universe": [{"name": "dex-a:NVDA"}]},
            {"universe": [{"name": "dex-b:TSLA"}]},
        ]

    async def get_spot_meta() -> dict[str, list[Any]]:
        await barrier.wait()
        return {"universe": [], "tokens": []}

    hl.info = SimpleNamespace(
        get_all_perp_metas=get_all_perp_metas, get_spot_meta=get_spot_meta
    )

    metas = await hl.experimental_get_all_metas()

    assert metas["perp"] == {"universe": [{"name": "BTC"}]}
    assert metas["spot"] == {"universe": [], "tokens": []}
    assert metas["dexs"] == {
        "dex-a": {"universe": [{"name": "dex-a:NVDA"}]},
        "dex-b": {"universe": [{"name": "dex-b:TSLA"}]},
    }


@pytest.mark.asyncio
async def test_get_coin_name_coalesces_concurrent_cold_meta_init() -> None:
    hl = build_stub_hl()
    barrier = StartBarrier(required=3)
    calls = {"all_perp": 0, "spot": 0, "dex": 0}
    setattr(hl, "coin_assets", {})
    setattr(hl, "coin_names", {})
    setattr(hl, "coin_symbols", {})
    setattr(hl, "asset_sz_decimals", {})
    setattr(hl, "spot_tokens", {})
    setattr(hl, "perp_dexs", [""])

    async def get_all_perp_metas() -> list[dict[str, Any]]:
        calls["all_perp"] += 1
        await barrier.wait()
        return [{"universe": [{"name": "BTC", "szDecimals": 5}]}]

    async def get_spot_meta() -> dict[str, list[Any]]:
        calls["spot"] += 1
        await barrier.wait()
        return {"universe": [], "tokens": []}

    async def get_perp_dexs() -> list[None]:
        calls["dex"] += 1
        await barrier.wait()
        return [None]

    hl.info = SimpleNamespace(
        get_all_perp_metas=get_all_perp_metas,
        get_spot_meta=get_spot_meta,
        get_perp_dexs=get_perp_dexs,
    )

    coin_names = await asyncio.gather(*(hl.get_coin_name("BTC") for _ in range(3)))

    assert coin_names == ["BTC", "BTC", "BTC"]
    assert calls == {"all_perp": 1, "spot": 1, "dex": 1}


@pytest.mark.asyncio
async def test_init_metas_refreshes_after_first_load() -> None:
    hl = build_stub_hl()
    phase = {"value": 1}
    calls = {"all_perp": 0, "spot": 0, "dex": 0}
    setattr(hl, "coin_assets", {})
    setattr(hl, "coin_names", {})
    setattr(hl, "coin_symbols", {})
    setattr(hl, "asset_sz_decimals", {})
    setattr(hl, "spot_tokens", {})
    setattr(hl, "perp_dexs", [""])

    async def get_all_perp_metas() -> list[dict[str, Any]]:
        calls["all_perp"] += 1
        if phase["value"] == 1:
            return [{"universe": [{"name": "BTC", "szDecimals": 5}]}]
        return [
            {
                "universe": [
                    {"name": "BTC", "szDecimals": 5},
                    {"name": "ETH", "szDecimals": 4},
                ]
            }
        ]

    async def get_spot_meta() -> dict[str, list[Any]]:
        calls["spot"] += 1
        return {"universe": [], "tokens": []}

    async def get_perp_dexs() -> list[None]:
        calls["dex"] += 1
        return [None]

    hl.info = SimpleNamespace(
        get_all_perp_metas=get_all_perp_metas,
        get_spot_meta=get_spot_meta,
        get_perp_dexs=get_perp_dexs,
    )

    await hl.init_metas()

    assert hl.coin_assets == {"BTC": 0}

    phase["value"] = 2
    await hl.init_metas()

    assert hl.coin_assets == {"BTC": 0, "ETH": 1}
    assert calls == {"all_perp": 2, "spot": 2, "dex": 2}


@pytest.mark.asyncio
async def test_get_coin_name_refreshes_warm_meta_cache_on_miss() -> None:
    hl = build_stub_hl()
    phase = {"value": 1}
    calls = {"all_perp": 0, "spot": 0, "dex": 0}
    setattr(hl, "coin_assets", {})
    setattr(hl, "coin_names", {})
    setattr(hl, "coin_symbols", {})
    setattr(hl, "asset_sz_decimals", {})
    setattr(hl, "spot_tokens", {})
    setattr(hl, "perp_dexs", [""])

    async def get_all_perp_metas() -> list[dict[str, Any]]:
        calls["all_perp"] += 1
        if phase["value"] == 1:
            return [{"universe": [{"name": "BTC", "szDecimals": 5}]}]
        return [
            {
                "universe": [
                    {"name": "BTC", "szDecimals": 5},
                    {"name": "ETH", "szDecimals": 4},
                ]
            }
        ]

    async def get_spot_meta() -> dict[str, list[Any]]:
        calls["spot"] += 1
        return {"universe": [], "tokens": []}

    async def get_perp_dexs() -> list[None]:
        calls["dex"] += 1
        return [None]

    hl.info = SimpleNamespace(
        get_all_perp_metas=get_all_perp_metas,
        get_spot_meta=get_spot_meta,
        get_perp_dexs=get_perp_dexs,
    )

    await hl.init_metas()
    phase["value"] = 2

    coin_name = await hl.get_coin_name("ETH")

    assert coin_name == "ETH"
    assert hl.coin_assets == {"BTC": 0, "ETH": 1}
    assert calls == {"all_perp": 2, "spot": 2, "dex": 2}


@pytest.mark.asyncio
async def test_init_metas_uses_aggregated_perp_metas_for_configured_dexs() -> None:
    hl = build_stub_hl()
    setattr(hl, "coin_assets", {})
    setattr(hl, "coin_names", {})
    setattr(hl, "coin_symbols", {})
    setattr(hl, "asset_sz_decimals", {})
    setattr(hl, "spot_tokens", {})
    setattr(hl, "perp_dexs", ["", "dex-a", "dex-b"])

    hl.get_all_dex_name = AsyncMock(return_value=["", "dex-a", "dex-b"])
    get_perp_meta = AsyncMock()
    hl.info = SimpleNamespace(
        get_all_perp_metas=AsyncMock(
            return_value=[
                {"universe": [{"name": "BTC", "szDecimals": 5}]},
                {"universe": [{"name": "dex-a:NVDA", "szDecimals": 3}]},
                {"universe": [{"name": "dex-b:TSLA", "szDecimals": 2}]},
            ]
        ),
        get_spot_meta=AsyncMock(return_value={"universe": [], "tokens": []}),
        get_perp_meta=get_perp_meta,
    )

    await hl.init_metas()

    assert hl.coin_assets["BTC"] == 0
    assert hl.coin_assets["dex-a:NVDA"] == PERP_DEX_OFFSET
    assert hl.coin_assets["dex-b:TSLA"] == PERP_DEX_OFFSET + 10000
    get_perp_meta.assert_not_awaited()


@pytest.mark.asyncio
async def test_init_metas_ignores_untracked_tail_dexs_in_dex_list() -> None:
    hl = build_stub_hl()
    setattr(hl, "coin_assets", {})
    setattr(hl, "coin_names", {})
    setattr(hl, "coin_symbols", {})
    setattr(hl, "asset_sz_decimals", {})
    setattr(hl, "spot_tokens", {})
    setattr(hl, "perp_dexs", ["", "dex-a"])

    hl.get_all_dex_name = AsyncMock(return_value=["", "dex-a", "newdex"])
    hl.info = SimpleNamespace(
        get_all_perp_metas=AsyncMock(
            return_value=[
                {"universe": [{"name": "BTC", "szDecimals": 5}]},
                {"universe": [{"name": "dex-a:NVDA", "szDecimals": 3}]},
            ]
        ),
        get_spot_meta=AsyncMock(return_value={"universe": [], "tokens": []}),
        get_perp_meta=AsyncMock(),
    )

    await hl.init_metas()

    assert hl.perp_dexs == ["", "dex-a"]
    assert hl.coin_assets["BTC"] == 0
    assert hl.coin_assets["dex-a:NVDA"] == PERP_DEX_OFFSET
    assert "newdex" not in hl.coin_assets


@pytest.mark.asyncio
async def test_init_metas_warns_and_refetches_missing_configured_dex() -> None:
    hl = build_stub_hl()
    setattr(hl, "coin_assets", {})
    setattr(hl, "coin_names", {})
    setattr(hl, "coin_symbols", {})
    setattr(hl, "asset_sz_decimals", {})
    setattr(hl, "spot_tokens", {})
    setattr(hl, "perp_dexs", ["", "dex-a", "dex-b"])

    hl.get_all_dex_name = AsyncMock(return_value=["", "dex-a", "dex-b", "newdex"])
    get_perp_meta = AsyncMock(
        return_value={"universe": [{"name": "dex-a:NVDA", "szDecimals": 3}]}
    )
    hl.info = SimpleNamespace(
        get_all_perp_metas=AsyncMock(
            return_value=[
                {"universe": [{"name": "BTC", "szDecimals": 5}]},
                {"universe": [{"name": "dex-b:TSLA", "szDecimals": 2}]},
            ]
        ),
        get_spot_meta=AsyncMock(return_value={"universe": [], "tokens": []}),
        get_perp_meta=get_perp_meta,
    )

    with pytest.warns(
        UserWarning, match="allPerpMetas missing configured perp metadata for: dex-a"
    ):
        await hl.init_metas()

    assert hl.coin_assets["BTC"] == 0
    assert hl.coin_assets["dex-a:NVDA"] == PERP_DEX_OFFSET
    assert hl.coin_assets["dex-b:TSLA"] == PERP_DEX_OFFSET + 10000
    get_perp_meta.assert_awaited_once_with("dex-a")


@pytest.mark.asyncio
async def test_init_metas_fails_and_keeps_old_cache_when_configured_dex_missing_from_dex_list() -> (
    None
):
    hl = build_stub_hl()
    setattr(
        hl,
        "coin_assets",
        {"BTC": 0, "dex-a:OLD": PERP_DEX_OFFSET, "dex-b:OLD": PERP_DEX_OFFSET + 10000},
    )
    setattr(
        hl,
        "coin_names",
        {"BTC": "BTC", "dex-a:OLD": "dex-a:OLD", "dex-b:OLD": "dex-b:OLD"},
    )
    setattr(
        hl,
        "coin_symbols",
        {"BTC": "BTC", "dex-a:OLD": "dex-a:OLD", "dex-b:OLD": "dex-b:OLD"},
    )
    setattr(
        hl, "asset_sz_decimals", {0: 5, PERP_DEX_OFFSET: 3, PERP_DEX_OFFSET + 10000: 2}
    )
    setattr(hl, "spot_tokens", {})
    setattr(hl, "perp_dexs", ["", "dex-a", "dex-b"])

    hl.get_all_dex_name = AsyncMock(return_value=["", "dex-b"])
    get_perp_meta = AsyncMock()
    hl.info = SimpleNamespace(
        get_all_perp_metas=AsyncMock(
            return_value=[
                {"universe": [{"name": "BTC", "szDecimals": 5}]},
                {"universe": [{"name": "dex-b:NEW", "szDecimals": 4}]},
            ]
        ),
        get_spot_meta=AsyncMock(return_value={"universe": [], "tokens": []}),
        get_perp_meta=get_perp_meta,
    )

    with pytest.raises(
        ValueError,
        match="Configured perp dexes missing from perpDexs; refusing metadata refresh because DEX offsets are no longer trustworthy: dex-a",
    ):
        await hl.init_metas()

    assert hl.coin_assets["BTC"] == 0
    assert hl.coin_assets["dex-a:OLD"] == PERP_DEX_OFFSET
    assert hl.coin_assets["dex-b:OLD"] == PERP_DEX_OFFSET + 10000
    assert "dex-b:NEW" not in hl.coin_assets
    get_perp_meta.assert_not_awaited()


@pytest.mark.asyncio
async def test_init_metas_raises_when_configured_dex_missing_from_dex_list_without_cached_metadata() -> (
    None
):
    hl = build_stub_hl()
    setattr(hl, "coin_assets", {})
    setattr(hl, "coin_names", {})
    setattr(hl, "coin_symbols", {})
    setattr(hl, "asset_sz_decimals", {})
    setattr(hl, "spot_tokens", {})
    setattr(hl, "perp_dexs", ["", "dex-a"])

    hl.get_all_dex_name = AsyncMock(return_value=["", "newdex"])
    get_perp_meta = AsyncMock()
    hl.info = SimpleNamespace(
        get_all_perp_metas=AsyncMock(
            return_value=[
                {"universe": [{"name": "BTC", "szDecimals": 5}]},
                {"universe": [{"name": "dex-a:NEW", "szDecimals": 4}]},
            ]
        ),
        get_spot_meta=AsyncMock(return_value={"universe": [], "tokens": []}),
        get_perp_meta=get_perp_meta,
    )

    with pytest.raises(
        ValueError,
        match="Configured perp dexes missing from perpDexs; refusing metadata refresh because DEX offsets are no longer trustworthy: dex-a",
    ):
        await hl.init_metas()

    assert hl.coin_assets == {}
    get_perp_meta.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("all_dex_names", [["dex-a"], ["dex-a", ""]])
async def test_init_metas_fails_when_perp_dexs_missing_base_entry(
    all_dex_names: list[str],
) -> None:
    hl = build_stub_hl()
    setattr(hl, "coin_assets", {"BTC": 0, "dex-a:OLD": PERP_DEX_OFFSET})
    setattr(hl, "coin_names", {"BTC": "BTC", "dex-a:OLD": "dex-a:OLD"})
    setattr(hl, "coin_symbols", {"BTC": "BTC", "dex-a:OLD": "dex-a:OLD"})
    setattr(hl, "asset_sz_decimals", {0: 5, PERP_DEX_OFFSET: 3})
    setattr(hl, "spot_tokens", {})
    setattr(hl, "perp_dexs", ["", "dex-a"])

    hl.get_all_dex_name = AsyncMock(return_value=all_dex_names)
    get_perp_meta = AsyncMock()
    hl.info = SimpleNamespace(
        get_all_perp_metas=AsyncMock(
            return_value=[
                {"universe": [{"name": "BTC", "szDecimals": 5}]},
                {"universe": [{"name": "dex-a:NVDA", "szDecimals": 3}]},
            ]
        ),
        get_spot_meta=AsyncMock(return_value={"universe": [], "tokens": []}),
        get_perp_meta=get_perp_meta,
    )

    with pytest.raises(
        ValueError,
        match="perpDexs must start with the base perp dex; refusing metadata refresh because DEX offsets are no longer trustworthy",
    ):
        await hl.init_metas()

    assert hl.coin_assets == {"BTC": 0, "dex-a:OLD": PERP_DEX_OFFSET}
    assert hl.asset_sz_decimals == {0: 5, PERP_DEX_OFFSET: 3}
    get_perp_meta.assert_not_awaited()


@pytest.mark.asyncio
async def test_init_metas_fails_when_perp_dexs_contains_duplicate_dex_names() -> None:
    hl = build_stub_hl()
    setattr(hl, "coin_assets", {"BTC": 0, "dex-a:OLD": PERP_DEX_OFFSET})
    setattr(hl, "coin_names", {"BTC": "BTC", "dex-a:OLD": "dex-a:OLD"})
    setattr(hl, "coin_symbols", {"BTC": "BTC", "dex-a:OLD": "dex-a:OLD"})
    setattr(hl, "asset_sz_decimals", {0: 5, PERP_DEX_OFFSET: 3})
    setattr(hl, "spot_tokens", {})
    setattr(hl, "perp_dexs", ["", "dex-a"])

    hl.get_all_dex_name = AsyncMock(return_value=["", "dex-a", "dex-a"])
    get_perp_meta = AsyncMock()
    hl.info = SimpleNamespace(
        get_all_perp_metas=AsyncMock(
            return_value=[
                {"universe": [{"name": "BTC", "szDecimals": 5}]},
                {"universe": [{"name": "dex-a:NVDA", "szDecimals": 3}]},
            ]
        ),
        get_spot_meta=AsyncMock(return_value={"universe": [], "tokens": []}),
        get_perp_meta=get_perp_meta,
    )

    with pytest.raises(
        ValueError,
        match="perpDexs returned duplicate perp dex names; refusing metadata refresh because DEX offsets are no longer trustworthy: dex-a",
    ):
        await hl.init_metas()

    assert hl.coin_assets == {"BTC": 0, "dex-a:OLD": PERP_DEX_OFFSET}
    assert hl.asset_sz_decimals == {0: 5, PERP_DEX_OFFSET: 3}
    get_perp_meta.assert_not_awaited()


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


def test_init_spot_meta_registers_quote_token_aliases() -> None:
    hl = init_spot_meta_stub()

    meta = {
        "tokens": [
            {
                "name": "PURR",
                "index": 0,
                "isCanonical": True,
                "szDecimals": 5,
                "weiDecimals": 8,
                "tokenId": "purr",
                "evmContract": None,
                "fullName": "Purr",
            },
            {
                "name": "USDC",
                "index": 1,
                "isCanonical": True,
                "szDecimals": 6,
                "weiDecimals": 8,
                "tokenId": "usdc",
                "evmContract": None,
                "fullName": "USD Coin",
            },
        ],
        "universe": [{"name": "@1", "index": 1, "isCanonical": True, "tokens": (0, 1)}],
    }

    hl._init_spot_meta(meta)

    assert hl.coin_names["PURR/USDC"] == "@1"
    assert hl.coin_names["USDC"] == "USDC"
    assert hl.spot_tokens["USDC"]["tokenId"] == "usdc"


def test_init_spot_meta_skips_malformed_token_indexes() -> None:
    hl = init_spot_meta_stub()

    meta = {
        "tokens": [
            {
                "name": "PURR",
                "index": 0,
                "isCanonical": True,
                "szDecimals": 5,
                "weiDecimals": 8,
                "tokenId": "purr",
                "evmContract": None,
                "fullName": "Purr",
            }
        ],
        "universe": [
            {"name": "@1", "index": 1, "isCanonical": True, "tokens": (0, 99)}
        ],
    }

    hl._init_spot_meta(meta)

    assert hl.coin_assets["@1"] == SPOT_OFFSET + 1
    assert "@1" not in hl.spot_tokens
    assert len(hl.asset_sz_decimals) == 0


@pytest.mark.asyncio
async def test_get_coin_sz_decimals_uses_cached_asset_fast_path() -> None:
    hl = build_stub_hl()
    get_coin_name = AsyncMock(return_value="BTC")
    setattr(hl, "get_coin_name", get_coin_name)
    setattr(hl, "coin_names", {"BTC": "BTC"})
    setattr(hl, "coin_assets", {"BTC": 7})
    setattr(hl, "asset_sz_decimals", {7: 4})

    sz_decimals = await hl.get_coin_sz_decimals("BTC")

    assert sz_decimals == 4
    get_coin_name.assert_not_awaited()


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


@pytest.mark.asyncio
async def test_cancel_orders_uses_cached_asset_fast_path() -> None:
    hl = build_stub_hl()
    exchange = SimpleNamespace(post_action=AsyncMock(return_value={"status": "ok"}))
    get_coin_asset = AsyncMock(
        side_effect=AssertionError("cache miss path should not run")
    )
    setattr(hl, "coin_assets", {"BTC": 1, "ETH": 2, "SOL": 3})
    setattr(hl, "coin_names", {"BTC": "BTC", "ETH": "ETH", "SOL": "SOL"})
    setattr(hl, "exchange", exchange)
    setattr(hl, "get_coin_asset", get_coin_asset)
    setattr(hl, "vault", None)
    setattr(hl, "expires", None)

    resp = await hl.cancel_orders([("BTC", 1), ("ETH", 2), ("SOL", 3)])

    assert resp == {"status": "ok"}
    get_coin_asset.assert_not_called()
    exchange.post_action.assert_awaited_once_with(
        {
            "type": "cancel",
            "cancels": [{"a": 1, "o": 1}, {"a": 2, "o": 2}, {"a": 3, "o": 3}],
        },
        vault=None,
        expires=None,
    )
