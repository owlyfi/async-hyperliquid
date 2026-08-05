from collections.abc import Awaitable, Callable, Sequence
from typing import cast

import pytest

from async_hyperliquid.types import Network
from async_hyperliquid.types.info import PerpMeta, SpotMeta
from tests.integration.info_client import IntegrationInfoClient
from tests.integration.test_info import Markets, markets


PERP_META = cast(
    PerpMeta,
    {
        "universe": [{"name": "BTC", "szDecimals": 5, "maxLeverage": 50}],
        "marginTables": [],
    },
)
EMPTY_PERP_META = cast(PerpMeta, {"universe": [], "marginTables": []})
SPOT_META = cast(
    SpotMeta,
    {
        "tokens": [
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
        ],
        "universe": [{"name": "@0", "index": 0, "isCanonical": True, "tokens": [1, 0]}],
    },
)


class MarketsInfoStub:
    def __init__(
        self,
        network: Network,
        *,
        refresh_results: Sequence[BaseException | None] = (),
        perp_metas: Sequence[PerpMeta] = (PERP_META,),
    ) -> None:
        self.network = network
        self._refresh_results = list(refresh_results)
        self._perp_metas = list(perp_metas)
        self.refresh_calls = 0
        self.perp_meta_calls = 0
        self.spot_meta_calls = 0
        self.perp_dex_names_calls = 0

    async def refresh_metadata(self) -> None:
        self.refresh_calls += 1
        if self._refresh_results:
            result = self._refresh_results.pop(0)
            if result is not None:
                raise result

    async def perp_meta(self) -> PerpMeta:
        self.perp_meta_calls += 1
        if len(self._perp_metas) > 1:
            return self._perp_metas.pop(0)
        return self._perp_metas[0]

    async def spot_meta(self) -> SpotMeta:
        self.spot_meta_calls += 1
        return SPOT_META

    async def perp_dex_names(self) -> tuple[str, ...]:
        self.perp_dex_names_calls += 1
        return ("",)


_MARKETS_FIXTURE = cast(
    Callable[[IntegrationInfoClient, dict[Network, Markets]], Awaitable[Markets]],
    getattr(markets, "__wrapped__"),
)


async def _markets(info: MarketsInfoStub, cache: dict[Network, Markets]) -> Markets:
    return await _MARKETS_FIXTURE(cast(IntegrationInfoClient, info), cache)


def test_markets_fixture_retries_setup_per_case_until_cached() -> None:
    marker = getattr(markets, "_fixture_function_marker")

    assert marker.scope == "function"


async def test_markets_skip_is_not_cached_and_success_is_cached() -> None:
    info = MarketsInfoStub(Network.TESTNET, perp_metas=(EMPTY_PERP_META, PERP_META))
    cache: dict[Network, Markets] = {}

    with pytest.raises(pytest.skip.Exception):
        await _markets(info, cache)
    assert cache == {}

    loaded = await _markets(info, cache)
    assert await _markets(info, cache) is loaded
    assert info.refresh_calls == 2
    assert info.perp_meta_calls == 2
    assert info.spot_meta_calls == 2
    assert info.perp_dex_names_calls == 2


async def test_markets_error_is_not_cached_and_success_is_cached() -> None:
    failure = RuntimeError("metadata unavailable")
    info = MarketsInfoStub(Network.TESTNET, refresh_results=(failure, None))
    cache: dict[Network, Markets] = {}

    with pytest.raises(RuntimeError) as raised:
        await _markets(info, cache)
    assert raised.value is failure
    assert cache == {}

    loaded = await _markets(info, cache)
    assert await _markets(info, cache) is loaded
    assert info.refresh_calls == 2
    assert info.perp_meta_calls == 1
    assert info.spot_meta_calls == 1
    assert info.perp_dex_names_calls == 1


async def test_markets_cache_is_scoped_by_network() -> None:
    mainnet = MarketsInfoStub(Network.MAINNET)
    testnet = MarketsInfoStub(Network.TESTNET)
    cache: dict[Network, Markets] = {}

    mainnet_markets = await _markets(mainnet, cache)
    testnet_markets = await _markets(testnet, cache)

    assert await _markets(mainnet, cache) is mainnet_markets
    assert await _markets(testnet, cache) is testnet_markets
    assert set(cache) == {Network.MAINNET, Network.TESTNET}
    assert mainnet.refresh_calls == 1
    assert testnet.refresh_calls == 1
