import asyncio
from copy import deepcopy
from typing import cast

import pytest

from async_hyperliquid._http import _HttpTransport
from async_hyperliquid.errors import ProtocolError
from async_hyperliquid.info import InfoClient
from async_hyperliquid.types import JsonObject, JsonValue


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
        self.block_type: str | None = None
        self.fail_type: str | None = None
        self.perp_dexes = deepcopy(PERP_DEXES)
        self.all_perp_metas = deepcopy(ALL_PERP_METAS)
        self.spot_meta = deepcopy(SPOT_META)
        self.perp_context = deepcopy(BASE_CONTEXT)
        self.spot_context = deepcopy(SPOT_CONTEXT)

    async def post_json(self, url: str, payload: JsonObject) -> JsonValue:
        request_type = cast(str, payload["type"])
        self.counts[request_type] = self.counts.get(request_type, 0) + 1
        if request_type == self.block_type:
            self.started.set()
            await self.release.wait()
        if request_type == self.fail_type:
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
            return [deepcopy(SPOT_META), [deepcopy(self.spot_context)]]
        if request_type == "allMids":
            return {"BTC": "100", "xyz:NVDA": "201", "@0": "2.1"}
        if request_type == "clearinghouseState":
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


async def test_price_and_account_helpers_use_info_only() -> None:
    transport = MetadataTransport()
    info = build_info(transport)

    assert await info.mark_price("BTC") == 100.0
    assert await info.mark_price("xyz:NVDA") == 200.0
    assert await info.mark_price("PURR/USDC") == 2.0
    assert await info.mid_price("BTC") == 100.0
    assert await info.mid_price("xyz:NVDA") == 201.0
    state = await info.account_state(ADDRESS, perp_dexes=("", "xyz"))
    positions = await info.positions(ADDRESS, perp_dexes=("", "xyz"))

    assert set(state["dexs"]) == {"xyz"}
    assert state["spot"] == {"balances": []}
    assert [position["coin"] for position in positions] == ["BTC", "BTC"]


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
