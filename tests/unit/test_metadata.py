import asyncio
from copy import deepcopy
from typing import cast

import pytest

from async_hyperliquid._internal.http import _HttpTransport
from async_hyperliquid._internal.metadata import (
    _MarketInfo,
    _build_metadata,
    _market_info,
)
from async_hyperliquid.errors import ProtocolError
from async_hyperliquid.info import InfoClient
from async_hyperliquid.types import JsonObject, JsonValue
from async_hyperliquid.types.info import AllPerpMetas, SpotMeta


ADDRESS = "0x1111111111111111111111111111111111111111"

BASE_CONTEXT: JsonObject = {
    "dayNtlVlm": "1",
    "funding": "0",
    "impactPxs": ["99", "101"],
    "markPx": "100",
    "midPx": "100",
    "openInterest": "1",
    "oraclePx": "100",
    "premium": "0",
    "prevDayPx": "99",
}
HIP3_CONTEXT: JsonObject = {**BASE_CONTEXT, "markPx": "200", "midPx": "201"}
SPOT_CONTEXT: JsonObject = {
    "coin": "@0",
    "dayNtlVlm": "1",
    "markPx": "2",
    "midPx": "2.1",
    "prevDayPx": "1",
}
PERP_DEXES: list[JsonValue] = [
    None,
    {
        "name": "xyz",
        "fullName": "XYZ",
        "deployer": ADDRESS,
        "oracleUpdater": None,
        "feeRecipient": None,
        "assetToStreamingOiCap": [],
        "assetToFundingMultiplier": [],
    },
]
BASE_PERP_META: JsonObject = {
    "universe": [{"name": "BTC", "szDecimals": 5, "maxLeverage": 50}],
    "marginTables": [],
}
HIP3_PERP_META: JsonObject = {
    "universe": [{"name": "xyz:NVDA", "szDecimals": 3, "maxLeverage": 10}],
    "marginTables": [],
    "collateralToken": 0,
}
ALL_PERP_METAS: list[JsonValue] = [BASE_PERP_META, HIP3_PERP_META]
SPOT_META: JsonObject = {
    "tokens": [
        {
            "name": "USDC",
            "index": 0,
            "isCanonical": True,
            "szDecimals": 6,
            "weiDecimals": 6,
            "tokenId": "0x00",
            "evmContract": None,
            "fullName": "USD Coin",
        },
        {
            "name": "PURR",
            "index": 1,
            "isCanonical": True,
            "szDecimals": 0,
            "weiDecimals": 5,
            "tokenId": "0x01",
            "evmContract": None,
            "fullName": "Purr",
        },
    ],
    "universe": [{"name": "@0", "index": 0, "isCanonical": True, "tokens": [1, 0]}],
}


class MetadataTransport:
    def __init__(self) -> None:
        self.counts: dict[str, int] = {}
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.cancelled_types: set[str] = set()
        self.block_type: str | None = None
        self.fail_type: str | None = None
        self.fail_types: set[str] = set()
        self.malformed_positions = False
        self.perp_dexes = deepcopy(PERP_DEXES)
        self.all_perp_metas = deepcopy(ALL_PERP_METAS)
        self.spot_meta = deepcopy(SPOT_META)
        self.perp_context = deepcopy(BASE_CONTEXT)
        self.spot_contexts = [deepcopy(SPOT_CONTEXT)]
        self.all_mids = {"BTC": "100", "xyz:NVDA": "201", "@0": "2.1"}
        self.all_mids_dexes: list[str] = []

    async def post_json(self, url: str, payload: JsonObject) -> JsonValue:
        request_type = cast(str, payload["type"])
        self.counts[request_type] = self.counts.get(request_type, 0) + 1
        if request_type == self.block_type:
            self.started.set()
            try:
                await self.release.wait()
            except asyncio.CancelledError:
                self.cancelled_types.add(request_type)
                raise
        if request_type == self.fail_type or request_type in self.fail_types:
            raise ProtocolError(f"{request_type} failed")
        if request_type == "perpDexs":
            return deepcopy(self.perp_dexes)
        if request_type == "allPerpMetas":
            return deepcopy(self.all_perp_metas)
        if request_type == "spotMeta":
            return deepcopy(self.spot_meta)
        if request_type == "metaAndAssetCtxs":
            dex = payload.get("dex")
            if dex == "xyz":
                return [deepcopy(HIP3_PERP_META), [deepcopy(HIP3_CONTEXT)]]
            return [deepcopy(BASE_PERP_META), [deepcopy(self.perp_context)]]
        if request_type == "spotMetaAndAssetCtxs":
            return [deepcopy(SPOT_META), deepcopy(self.spot_contexts)]
        if request_type == "allMids":
            self.all_mids_dexes.append(cast(str, payload["dex"]))
            return deepcopy(self.all_mids)
        if request_type == "clearinghouseState":
            if self.malformed_positions:
                return {"assetPositions": [{}]}
            return {
                "assetPositions": [
                    {
                        "type": "oneWay",
                        "position": {
                            "coin": "BTC",
                            "cumFunding": {
                                "allTime": "0",
                                "sinceChange": "0",
                                "sinceOpen": "0",
                            },
                            "entryPx": "100",
                            "leverage": {"type": "cross", "value": 1},
                            "liquidationPx": None,
                            "marginUsed": "1",
                            "maxLeverage": 50,
                            "positionValue": "1",
                            "returnOnEquity": "0",
                            "szi": "0.01",
                            "unrealizedPnl": "0",
                        },
                    }
                ],
                "crossMaintenanceMarginUsed": "0",
                "crossMarginSummary": {
                    "accountValue": "1",
                    "totalMarginUsed": "0",
                    "totalNtlPos": "0",
                    "totalRawUsd": "1",
                },
                "marginSummary": {
                    "accountValue": "1",
                    "totalMarginUsed": "0",
                    "totalNtlPos": "0",
                    "totalRawUsd": "1",
                },
                "time": 1,
                "withdrawable": "1",
            }
        if request_type == "spotClearinghouseState":
            return {"balances": []}
        raise AssertionError(request_type)


def build_info(transport: MetadataTransport) -> InfoClient:
    return InfoClient._from_transport(
        cast(_HttpTransport, transport), info_url="https://provider.example/info"
    )


def test_build_metadata_assembles_perp_and_spot_indexes() -> None:
    snapshot = _build_metadata(
        ("", "xyz"), cast(AllPerpMetas, ALL_PERP_METAS), cast(SpotMeta, SPOT_META)
    )

    assert snapshot.asset_by_coin["BTC"] == 0
    assert snapshot.size_decimals_by_asset[0] == 5
    assert snapshot.asset_by_coin["@0"] == 10_000
    assert snapshot.symbol_by_coin["@0"] == "PURR/USDC"
    assert snapshot.spot_market_coins == frozenset({"@0"})
    assert snapshot.perp_context_by_coin["xyz:NVDA"] == ("xyz", 0)
    assert _market_info(snapshot, "BTC") == _MarketInfo(
        coin="BTC", asset=0, size_decimals=5, is_spot=False, dex=""
    )


async def test_metadata_builds_exact_asset_and_alias_lookups() -> None:
    info = build_info(MetadataTransport())

    assert await info.perp_dex_names() == ("", "xyz")
    assert await info.coin_name("BTC") == "BTC"
    assert await info.asset_id("BTC") == 0
    assert await info.size_decimals("BTC") == 5
    assert await info.coin_name("xyz:NVDA") == "xyz:NVDA"
    assert await info.asset_id("xyz:NVDA") == 110_000
    assert await info.coin_symbol("xyz:NVDA") == "xyz:NVDA"
    assert await info.coin_name("PURR/USDC") == "@0"
    assert await info.coin_symbol("@0") == "PURR/USDC"
    assert await info.asset_id("PURR/USDC") == 10_000
    assert await info.size_decimals("@0") == 0
    assert (await info.spot_token_metadata("@0"))["name"] == "PURR"
    assert await info.token_id("PURR/USDC") == "0x01"


async def test_spot_alias_resolves_to_protocol_coin_before_mid_lookup() -> None:
    transport = MetadataTransport()
    base = cast(JsonObject, cast(list[JsonValue], transport.spot_meta["tokens"])[1])
    pair = cast(JsonObject, cast(list[JsonValue], transport.spot_meta["universe"])[0])
    base["name"] = "HYPE"
    base["szDecimals"] = 2
    pair["name"] = "@107"
    pair["index"] = 107
    transport.all_mids = {"BTC": "100", "@107": "42.5"}
    info = build_info(transport)

    assert await info._market_info("HYPE/USDC") == _MarketInfo(
        coin="@107", asset=10_107, size_decimals=2, is_spot=True, dex=""
    )
    assert await info.mid_price("HYPE/USDC") == 42.5
    assert transport.all_mids_dexes == [""]


@pytest.mark.parametrize(
    ("protocol_name", "alias"),
    (
        ("UBTC", "BTC/USDC"),
        ("UETH", "ETH/USDC"),
        ("USOL", "SOL/USDC"),
        ("USDT0", "USDT/USDC"),
    ),
)
async def test_spot_accepts_ui_alias(protocol_name: str, alias: str) -> None:
    transport = MetadataTransport()
    base = cast(JsonObject, cast(list[JsonValue], transport.spot_meta["tokens"])[1])
    base["name"] = protocol_name
    base["tokenId"] = "0x8f254b963e8468305d409b33aa137c67"
    pair = cast(JsonObject, cast(list[JsonValue], transport.spot_meta["universe"])[0])
    pair["name"] = "@11"
    info = build_info(transport)

    assert await info.token_id(alias) == base["tokenId"]
    assert (await info.spot_token_metadata(alias))["name"] == protocol_name


async def test_spot_alias_overrides_legacy_symbol() -> None:
    transport = MetadataTransport()
    tokens = cast(list[JsonValue], transport.spot_meta["tokens"])
    legacy = cast(JsonObject, tokens[1])
    legacy["name"] = "PUMP"
    legacy_pair = cast(
        JsonObject, cast(list[JsonValue], transport.spot_meta["universe"])[0]
    )
    legacy_pair.update({"name": "@20", "index": 20})
    tokens.append({**legacy, "name": "UPUMP", "index": 2, "tokenId": "0x02"})
    cast(list[JsonValue], transport.spot_meta["universe"]).append(
        {"name": "@188", "index": 188, "isCanonical": False, "tokens": [2, 0]}
    )
    info = build_info(transport)

    assert await info.coin_name("PUMP/USDC") == "@188"
    assert await info.token_id("PUMP/USDC") == "0x02"


async def test_purr_named_pair_is_its_protocol_coin() -> None:
    transport = MetadataTransport()
    pair = cast(JsonObject, cast(list[JsonValue], transport.spot_meta["universe"])[0])
    pair["name"] = "PURR/USDC"
    transport.all_mids = {"BTC": "100", "PURR/USDC": "0.123"}
    info = build_info(transport)

    assert (await info._market_info("PURR/USDC")).coin == "PURR/USDC"
    assert await info.mid_price("PURR/USDC") == 0.123


@pytest.mark.parametrize("coin", ["#10", "+10"])
async def test_outcome_market_uses_documented_encoding(coin: str) -> None:
    info = build_info(MetadataTransport())

    assert await info._market_info(coin) == _MarketInfo(
        coin="#10", asset=100_000_010, size_decimals=0, is_spot=True, dex=""
    )
    assert await info.asset_id(coin) == 100_000_010
    assert await info.size_decimals(coin) == 0


@pytest.mark.parametrize("coin", ["#", "+abc", "#12"])
async def test_outcome_market_rejects_invalid_encoding(coin: str) -> None:
    info = build_info(MetadataTransport())

    with pytest.raises(ValueError, match="outcome"):
        await info._market_info(coin)


async def test_spot_token_metadata_returns_an_isolated_snapshot() -> None:
    info = build_info(MetadataTransport())

    token = await info.spot_token_metadata("@0")
    token["name"] = "CORRUPTED"
    token["tokenId"] = "0xdead"

    fresh = await info.spot_token_metadata("@0")

    assert fresh is not token
    assert fresh["name"] == "PURR"
    assert fresh["tokenId"] == "0x01"
    assert await info.token_id("@0") == "0x01"


async def test_spot_token_accepts_the_documented_evm_contract_shape() -> None:
    transport = MetadataTransport()
    token = cast(JsonObject, cast(list[JsonValue], transport.spot_meta["tokens"])[0])
    token["evmContract"] = {"address": ADDRESS, "evm_extra_wei_decimals": -2}
    info = build_info(transport)

    await info.refresh_metadata()

    assert (await info.spot_token_metadata("USDC"))["evmContract"] == {
        "address": ADDRESS,
        "evm_extra_wei_decimals": -2,
    }


@pytest.mark.parametrize(
    "field", ["isCanonical", "weiDecimals", "evmContract", "fullName"]
)
async def test_spot_token_requires_every_published_field(field: str) -> None:
    transport = MetadataTransport()
    token = cast(JsonObject, cast(list[JsonValue], transport.spot_meta["tokens"])[0])
    del token[field]
    info = build_info(transport)

    with pytest.raises(ProtocolError, match=field):
        await info.refresh_metadata()

    assert info._metadata is None


@pytest.mark.parametrize(
    ("field", "invalid"),
    [
        ("index", -1),
        ("isCanonical", "yes"),
        ("szDecimals", -1),
        ("weiDecimals", -1),
        ("evmContract", 1),
        ("fullName", 1),
    ],
)
async def test_spot_token_rejects_invalid_published_field(
    field: str, invalid: JsonValue
) -> None:
    transport = MetadataTransport()
    token = cast(JsonObject, cast(list[JsonValue], transport.spot_meta["tokens"])[0])
    token[field] = invalid
    info = build_info(transport)

    with pytest.raises(ProtocolError, match=field):
        await info.refresh_metadata()

    assert info._metadata is None


async def test_price_and_account_helpers_use_info_only() -> None:
    transport = MetadataTransport()
    info = build_info(transport)

    assert await info.mark_price("BTC") == 100.0
    assert await info.mark_price("xyz:NVDA") == 200.0
    assert await info.mark_price("PURR/USDC") == 2.0
    assert await info.mid_price("BTC") == 100.0
    assert await info.mid_price("xyz:NVDA") == 201.0
    state = await info.account_state(ADDRESS, dexs=("", "xyz"))
    positions = await info.positions(ADDRESS, dexs=("", "xyz"))

    assert set(state["dexs"]) == {"xyz"}
    assert state["spot"] == {"balances": []}
    assert [position["coin"] for position in positions] == ["BTC", "BTC"]


async def test_spot_mark_price_matches_context_by_coin_not_list_position() -> None:
    transport = MetadataTransport()
    transport.spot_contexts.insert(0, {**SPOT_CONTEXT, "coin": "#10", "markPx": "999"})
    info = build_info(transport)

    assert await info.mark_price("PURR/USDC") == 2.0


async def test_mid_prices_fetch_once_per_distinct_dex() -> None:
    transport = MetadataTransport()
    info = build_info(transport)
    markets = await info._market_infos(("BTC", "BTC", "xyz:NVDA", "PURR/USDC"))

    prices = await info._mid_prices(markets)

    assert prices == (100.0, 100.0, 201.0, 2.1)
    assert transport.all_mids_dexes == ["", "xyz"]


async def test_mid_prices_preserve_the_underlying_request_error() -> None:
    transport = MetadataTransport()
    transport.fail_type = "allMids"
    info = build_info(transport)
    markets = await info._market_infos(("BTC", "xyz:NVDA"))

    with pytest.raises(ProtocolError, match="allMids failed"):
        await info._mid_prices(markets)


@pytest.mark.parametrize("method_name", ["account_state", "positions"])
async def test_public_fanout_preserves_the_underlying_request_error(
    method_name: str,
) -> None:
    transport = MetadataTransport()
    transport.fail_type = "clearinghouseState"
    info = build_info(transport)

    method = getattr(info, method_name)
    with pytest.raises(ProtocolError, match="clearinghouseState failed"):
        await method(ADDRESS, dexs=("", "xyz"))


async def test_metadata_fanout_preserves_a_library_error_when_multiple_calls_fail() -> (
    None
):
    transport = MetadataTransport()
    transport.fail_types = {"perpDexs", "allPerpMetas"}
    info = build_info(transport)

    with pytest.raises(ProtocolError):
        await info.refresh_metadata()


async def test_failed_metadata_fanout_cancels_blocked_sibling() -> None:
    transport = MetadataTransport()
    transport.block_type = "allPerpMetas"
    transport.fail_type = "perpDexs"
    info = build_info(transport)

    refresh = asyncio.create_task(info.refresh_metadata())
    await transport.started.wait()
    try:
        with pytest.raises(ProtocolError, match="perpDexs failed"):
            await refresh
        await asyncio.sleep(0)
        assert transport.cancelled_types == {"allPerpMetas"}
    finally:
        transport.release.set()


async def test_positions_rejects_malformed_provider_entries() -> None:
    transport = MetadataTransport()
    transport.malformed_positions = True
    info = build_info(transport)

    with pytest.raises(ProtocolError, match="assetPositions"):
        await info.positions(ADDRESS)


async def test_twenty_cold_readers_share_one_metadata_fetch_set() -> None:
    transport = MetadataTransport()
    transport.block_type = "allPerpMetas"
    info = build_info(transport)

    readers = [asyncio.create_task(info.asset_id("BTC")) for _ in range(20)]
    await transport.started.wait()
    transport.release.set()

    assert await asyncio.gather(*readers) == [0] * 20
    assert transport.counts == {"perpDexs": 1, "allPerpMetas": 1, "spotMeta": 1}


async def test_cancelling_a_waiter_does_not_cancel_the_active_loader() -> None:
    transport = MetadataTransport()
    transport.block_type = "allPerpMetas"
    info = build_info(transport)

    loader = asyncio.create_task(info.asset_id("BTC"))
    await transport.started.wait()
    waiter = asyncio.create_task(info.asset_id("BTC"))
    await asyncio.sleep(0)
    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter

    transport.release.set()
    assert await loader == 0
    assert transport.counts["allPerpMetas"] == 1


async def test_cancelling_the_active_loader_leaves_cache_retryable() -> None:
    transport = MetadataTransport()
    transport.block_type = "allPerpMetas"
    info = build_info(transport)

    loader = asyncio.create_task(info.asset_id("BTC"))
    await transport.started.wait()
    loader.cancel()
    with pytest.raises(asyncio.CancelledError):
        await loader

    transport.block_type = None
    assert await info.asset_id("BTC") == 0
    assert transport.counts["allPerpMetas"] == 2


async def test_failed_refresh_preserves_the_last_complete_snapshot() -> None:
    transport = MetadataTransport()
    info = build_info(transport)
    assert await info.asset_id("BTC") == 0
    original_snapshot = info._metadata

    transport.fail_type = "spotMeta"
    with pytest.raises(ProtocolError, match="spotMeta failed"):
        await info.refresh_metadata()

    assert info._metadata is original_snapshot
    assert await info.asset_id("BTC") == 0

    transport.fail_type = None
    await info.refresh_metadata()
    assert info._metadata is not original_snapshot


async def test_missing_perp_dex_metadata_is_rejected_without_publication() -> None:
    transport = MetadataTransport()
    transport.all_perp_metas = [deepcopy(BASE_PERP_META)]
    info = build_info(transport)

    with pytest.raises(ProtocolError, match="missing dex metadata"):
        await info.refresh_metadata()

    assert info._metadata is None


@pytest.mark.parametrize("malformed_branch", ["perp", "spot"])
async def test_malformed_metadata_is_rejected_without_partial_publication(
    malformed_branch: str,
) -> None:
    transport = MetadataTransport()
    info = build_info(transport)
    if malformed_branch == "perp":
        transport.all_perp_metas = [{"marginTables": []}]
    else:
        token = cast(
            JsonObject, cast(list[JsonValue], transport.spot_meta["tokens"])[0]
        )
        del token["tokenId"]

    with pytest.raises(ProtocolError, match="metadata"):
        await info.refresh_metadata()

    assert info._metadata is None
