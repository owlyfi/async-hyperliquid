import os
from collections.abc import AsyncIterator
from dataclasses import dataclass
from time import time

import pytest
import pytest_asyncio

from async_hyperliquid import InfoClient
from async_hyperliquid.errors import HttpError
from async_hyperliquid.types import CandleInterval, Network
from tests.integration.live_config import validate_live_roles


pytestmark = [pytest.mark.info, pytest.mark.asyncio(loop_scope="session")]


@dataclass(frozen=True, slots=True)
class LiveMarkets:
    perp: str
    spot: str
    token_id: str
    dexs: tuple[str, ...]


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def markets(info: InfoClient) -> LiveMarkets:
    await info.refresh_metadata()
    perp_meta = await info.perp_meta()
    spot_meta = await info.spot_meta()
    dexs = await info.perp_dex_names()
    if not perp_meta["universe"] or not spot_meta["universe"]:
        raise pytest.skip.Exception("testnet has no perp and spot markets")
    spot = spot_meta["universe"][0]
    base_token = spot["tokens"][0]
    token = next(token for token in spot_meta["tokens"] if token["index"] == base_token)
    return LiveMarkets(
        perp=perp_meta["universe"][0]["name"],
        spot=spot["name"],
        token_id=token["tokenId"],
        dexs=dexs,
    )


def _start_time() -> int:
    return int(time() * 1_000) - 3_600_000


async def test_all_mids(info: InfoClient) -> None:
    assert await info.all_mids()


async def test_open_orders(info: InfoClient, master_address: str) -> None:
    assert isinstance(await info.open_orders(master_address), list)
    assert isinstance(await info.open_orders(master_address, frontend=True), list)


async def test_user_fills(info: InfoClient, master_address: str) -> None:
    assert isinstance(await info.user_fills(master_address), list)


async def test_user_rate_limit(info: InfoClient, master_address: str) -> None:
    assert isinstance(await info.user_rate_limit(master_address), dict)


async def test_order_status(info: InfoClient, master_address: str) -> None:
    result = await info.order_status(master_address, 0)
    assert result["status"] in {"order", "unknownOid"}


async def test_l2_book(info: InfoClient, markets: LiveMarkets) -> None:
    book = await info.l2_book(markets.perp)
    assert len(book["levels"]) == 2


async def test_candles(info: InfoClient, markets: LiveMarkets) -> None:
    start = _start_time()
    candles = await info.candles(
        markets.perp, CandleInterval.FIFTEEN_MINUTES, start, start + 3_600_000
    )
    assert isinstance(candles, list)


async def test_max_builder_fee(info: InfoClient, master_address: str) -> None:
    assert isinstance(await info.max_builder_fee(master_address, master_address), int)


async def test_historical_orders(info: InfoClient, master_address: str) -> None:
    assert isinstance(await info.historical_orders(master_address), list)


async def test_twap_slice_fills(info: InfoClient, master_address: str) -> None:
    assert isinstance(await info.twap_slice_fills(master_address), list)


async def test_sub_accounts(info: InfoClient, master_address: str) -> None:
    result = await info.sub_accounts(master_address)
    assert result is None or isinstance(result, list)


async def test_vault_details(info: InfoClient, subaccount_address: str) -> None:
    result = await info.vault_details(subaccount_address)
    assert result is None or isinstance(result, dict)


async def test_vault_equities(info: InfoClient, master_address: str) -> None:
    assert isinstance(await info.vault_equities(master_address), list)


async def test_user_role(
    info: InfoClient,
    master_address: str,
    api_wallet_address: str,
    subaccount_address: str,
) -> None:
    validate_live_roles(
        master_address,
        await info.user_role(api_wallet_address),
        await info.user_role(subaccount_address),
    )


async def test_portfolio(info: InfoClient, master_address: str) -> None:
    assert isinstance(await info.portfolio(master_address), list)


async def test_referral(info: InfoClient, master_address: str) -> None:
    assert isinstance(await info.referral(master_address), dict)


async def test_user_fees(info: InfoClient, master_address: str) -> None:
    assert isinstance(await info.user_fees(master_address), dict)


async def test_delegations(info: InfoClient, master_address: str) -> None:
    assert isinstance(await info.delegations(master_address), list)


async def test_staking_summary(info: InfoClient, master_address: str) -> None:
    assert isinstance(await info.staking_summary(master_address), dict)


async def test_staking_history(info: InfoClient, master_address: str) -> None:
    assert isinstance(await info.staking_history(master_address), list)


async def test_staking_rewards(info: InfoClient, master_address: str) -> None:
    assert isinstance(await info.staking_rewards(master_address), list)


async def test_user_dex_abstraction(info: InfoClient, master_address: str) -> None:
    assert isinstance(await info.user_dex_abstraction(master_address), bool)


async def test_user_abstraction(info: InfoClient, master_address: str) -> None:
    assert isinstance(await info.user_abstraction(master_address), str)


async def test_aligned_quote_token_info(info: InfoClient) -> None:
    token = next(
        (
            token
            for token in (await info.spot_meta())["tokens"]
            if token["name"] == "USDZZ"
        ),
        None,
    )
    if token is None:
        raise pytest.skip.Exception("testnet has no aligned quote token")
    try:
        result = await info.aligned_quote_token_info(token["index"])
    except HttpError as error:
        if error.status == 422:
            raise pytest.xfail.Exception(
                "testnet does not expose alignedQuoteTokenInfo"
            )
        raise
    assert isinstance(result, dict)


async def test_perp_meta(info: InfoClient) -> None:
    assert (await info.perp_meta())["universe"]


async def test_perp_meta_and_contexts(info: InfoClient) -> None:
    meta, contexts = await info.perp_meta_and_contexts()
    assert len(meta["universe"]) == len(contexts)


async def test_all_perp_metas(info: InfoClient) -> None:
    assert await info.all_perp_metas()


async def test_perp_dexes(info: InfoClient) -> None:
    assert isinstance(await info.perp_dexes(), list)


async def test_perp_account_state(info: InfoClient, master_address: str) -> None:
    assert "assetPositions" in await info.perp_account_state(master_address)


async def test_funding_updates(info: InfoClient, master_address: str) -> None:
    assert isinstance(await info.funding_updates(master_address, _start_time()), list)


async def test_non_funding_ledger_updates(
    info: InfoClient, master_address: str
) -> None:
    updates = await info.non_funding_ledger_updates(master_address, _start_time())
    assert isinstance(updates, list)


async def test_funding_history(info: InfoClient, markets: LiveMarkets) -> None:
    assert isinstance(await info.funding_history(markets.perp, _start_time()), list)


async def test_predicted_fundings(info: InfoClient) -> None:
    assert isinstance(await info.predicted_fundings(), list)


async def test_perps_at_open_interest_cap(info: InfoClient) -> None:
    assert all(
        isinstance(coin, str) for coin in await info.perps_at_open_interest_cap()
    )


async def test_perp_deploy_auction_status(info: InfoClient) -> None:
    assert isinstance(await info.perp_deploy_auction_status(), dict)


async def test_active_asset_data(
    info: InfoClient, markets: LiveMarkets, master_address: str
) -> None:
    result = await info.active_asset_data(master_address, markets.perp)
    assert isinstance(result, dict)


async def test_spot_meta(info: InfoClient) -> None:
    assert (await info.spot_meta())["tokens"]


async def test_spot_meta_and_contexts(info: InfoClient) -> None:
    meta, contexts = await info.spot_meta_and_contexts()
    assert {pair["name"] for pair in meta["universe"]} <= {
        context["coin"] for context in contexts
    }


async def test_spot_account_state(info: InfoClient, master_address: str) -> None:
    assert "balances" in await info.spot_account_state(master_address)


async def test_spot_deploy_state(info: InfoClient, master_address: str) -> None:
    assert isinstance(await info.spot_deploy_state(master_address), dict)


async def test_token_details(info: InfoClient, markets: LiveMarkets) -> None:
    result = await info.token_details(markets.token_id)
    assert result is None or isinstance(result, dict)


async def test_perp_dex_names(info: InfoClient) -> None:
    assert "" in await info.perp_dex_names()


async def test_refresh_metadata(info: InfoClient) -> None:
    assert await info.refresh_metadata() is None


async def test_coin_name(info: InfoClient, markets: LiveMarkets) -> None:
    assert await info.coin_name(markets.perp) == markets.perp


async def test_coin_symbol(info: InfoClient, markets: LiveMarkets) -> None:
    assert await info.coin_symbol(markets.perp)


async def test_asset_id(info: InfoClient, markets: LiveMarkets) -> None:
    assert await info.asset_id(markets.perp) >= 0


async def test_size_decimals(info: InfoClient, markets: LiveMarkets) -> None:
    assert await info.size_decimals(markets.perp) >= 0


async def test_spot_token_metadata(info: InfoClient, markets: LiveMarkets) -> None:
    assert (await info.spot_token_metadata(markets.spot))["tokenId"]


async def test_token_id(info: InfoClient, markets: LiveMarkets) -> None:
    assert await info.token_id(markets.spot) == markets.token_id


@pytest.mark.parametrize("market", ["perp", "spot"])
async def test_mark_price(info: InfoClient, markets: LiveMarkets, market: str) -> None:
    assert await info.mark_price(getattr(markets, market)) > 0


async def test_mid_price(info: InfoClient, markets: LiveMarkets) -> None:
    assert await info.mid_price(markets.perp) > 0


async def test_account_state(
    info: InfoClient, markets: LiveMarkets, master_address: str
) -> None:
    state = await info.account_state(master_address, dexs=markets.dexs[:2])
    assert {"perp", "spot", "dexs"} <= state.keys()


async def test_positions(info: InfoClient, subaccount_address: str) -> None:
    positions = await info.positions(subaccount_address)
    assert isinstance(positions, list)


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def mainnet_info() -> AsyncIterator[InfoClient]:
    if os.environ.get("RUN_MAINNET_INFO_TESTS") != "true":
        raise pytest.skip.Exception(
            "set RUN_MAINNET_INFO_TESTS=true to run mainnet Info cases"
        )
    async with InfoClient(network=Network.MAINNET) as client:
        await client.refresh_metadata()
        yield client


@pytest.mark.mainnet_info
@pytest.mark.parametrize(
    "coin", ["BTC", "HYPE/USDC", "@107", "xyz:NVDA", "flx:TSLA", "vntl:OPENAI"]
)
async def test_mainnet_legacy_coin_aliases(mainnet_info: InfoClient, coin: str) -> None:
    assert await mainnet_info.coin_symbol(coin)


@pytest.mark.mainnet_info
@pytest.mark.parametrize("coin", ["xyz:SLIVER", "USDT/USDC"])
async def test_mainnet_legacy_unsupported_aliases(
    mainnet_info: InfoClient, coin: str
) -> None:
    with pytest.raises(ValueError):
        await mainnet_info.mark_price(coin)


@pytest.mark.mainnet_info
async def test_mainnet_legacy_hype_alias_price_parity(mainnet_info: InfoClient) -> None:
    assert await mainnet_info.mark_price("HYPE/USDC") == pytest.approx(
        await mainnet_info.mark_price("@107"), abs=0.01
    )
