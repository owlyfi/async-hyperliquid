from dataclasses import dataclass
from time import time

import pytest
import pytest_asyncio

from async_hyperliquid.errors import HttpError
from async_hyperliquid.types import CandleInterval, Network
from tests.integration.info_client import IntegrationInfoClient


pytestmark = [pytest.mark.info, pytest.mark.asyncio(loop_scope="session")]


@dataclass(frozen=True, slots=True)
class Markets:
    perp: str
    spot: str
    token_id: str
    dexs: tuple[str, ...]


HYPE_SPOT = {Network.MAINNET: ("@107", 10_107), Network.TESTNET: ("@1035", 11_035)}


@pytest.fixture(scope="session")
def markets_cache() -> dict[Network, Markets]:
    return {}


@pytest_asyncio.fixture(scope="function", loop_scope="session")
async def markets(
    info: IntegrationInfoClient, markets_cache: dict[Network, Markets]
) -> Markets:
    cached = markets_cache.get(info.network)
    if cached is not None:
        return cached

    await info.refresh_metadata()
    perp_meta = await info.perp_meta()
    spot_meta = await info.spot_meta()
    dexs = await info.perp_dex_names()
    if not perp_meta["universe"] or not spot_meta["universe"]:
        raise pytest.skip.Exception("testnet has no perp and spot markets")
    spot = spot_meta["universe"][0]
    base_token = spot["tokens"][0]
    token = next(token for token in spot_meta["tokens"] if token["index"] == base_token)
    loaded = Markets(
        perp=perp_meta["universe"][0]["name"],
        spot=spot["name"],
        token_id=token["tokenId"],
        dexs=dexs,
    )
    markets_cache[info.network] = loaded
    return loaded


def _start_time() -> int:
    return int(time() * 1_000) - 3_600_000


async def test_all_mids(info: IntegrationInfoClient) -> None:
    assert await info.all_mids()


async def test_hype_spot_mapping(info: IntegrationInfoClient) -> None:
    coin, asset = HYPE_SPOT[info.network]
    mids = await info.all_mids()

    assert await info.coin_name("HYPE/USDC") == coin
    assert await info.asset_id("HYPE/USDC") == asset
    assert await info.coin_symbol(coin) == "HYPE/USDC"
    assert (await info.spot_token_metadata(coin))["name"] == "HYPE"
    assert await info.mid_price("HYPE/USDC") == float(mids[coin])


async def test_purr_spot_mapping(info: IntegrationInfoClient) -> None:
    mids = await info.all_mids()

    assert await info.coin_name("PURR/USDC") == "PURR/USDC"
    assert await info.coin_symbol("PURR/USDC") == "PURR/USDC"
    assert (await info.spot_token_metadata("PURR/USDC"))["name"] == "PURR"
    assert await info.mid_price("PURR/USDC") == float(mids["PURR/USDC"])
    if info.network is Network.MAINNET:
        assert await info.asset_id("PURR/USDC") == 10_000


@pytest.mark.parametrize(
    ("symbol", "coin", "asset"),
    (
        ("USDT0/USDC", "@166", 10_166),
        ("USDE/USDC", "@150", 10_150),
        ("USDH/USDC", "@230", 10_230),
    ),
)
async def test_mainnet_spot_mapping(
    info: IntegrationInfoClient, symbol: str, coin: str, asset: int
) -> None:
    if info.network is Network.TESTNET:
        raise pytest.skip.Exception("mapping is mainnet-only")
    mids = await info.all_mids()

    assert await info.coin_name(symbol) == coin
    assert await info.asset_id(symbol) == asset
    assert await info.coin_symbol(coin) == symbol
    assert (await info.spot_token_metadata(coin))["name"] == symbol.partition("/")[0]
    assert await info.mid_price(symbol) == float(mids[coin])


async def test_outcome_mapping(info: IntegrationInfoClient) -> None:
    mids = await info.all_mids()
    coin = next((name for name in mids if name.startswith("#")), None)
    if coin is None:
        raise pytest.skip.Exception("testnet allMids has no outcome market")
    encoding = int(coin[1:])

    assert encoding % 10 in (0, 1)
    assert await info.asset_id(coin) == 100_000_000 + encoding
    assert await info.asset_id(f"+{encoding}") == 100_000_000 + encoding
    assert await info.size_decimals(coin) == 0
    assert await info.mid_price(coin) == float(mids[coin])


async def test_open_orders(info: IntegrationInfoClient, master_address: str) -> None:
    assert isinstance(await info.open_orders(master_address), list)
    assert isinstance(await info.open_orders(master_address, frontend=True), list)


async def test_user_fills(info: IntegrationInfoClient, master_address: str) -> None:
    assert isinstance(await info.user_fills(master_address), list)


async def test_user_rate_limit(
    info: IntegrationInfoClient, master_address: str
) -> None:
    assert isinstance(await info.user_rate_limit(master_address), dict)


async def test_order_status(info: IntegrationInfoClient, master_address: str) -> None:
    result = await info.order_status(master_address, 0)
    assert result["status"] in {"order", "unknownOid"}


async def test_l2_book(info: IntegrationInfoClient, markets: Markets) -> None:
    book = await info.l2_book(markets.perp)
    assert len(book["levels"]) == 2


async def test_candles(info: IntegrationInfoClient, markets: Markets) -> None:
    start = _start_time()
    candles = await info.candles(
        markets.perp, CandleInterval.FIFTEEN_MINUTES, start, start + 3_600_000
    )
    assert isinstance(candles, list)


async def test_max_builder_fee(
    info: IntegrationInfoClient, master_address: str
) -> None:
    assert isinstance(await info.max_builder_fee(master_address, master_address), int)


async def test_historical_orders(
    info: IntegrationInfoClient, master_address: str
) -> None:
    assert isinstance(await info.historical_orders(master_address), list)


async def test_twap_slice_fills(
    info: IntegrationInfoClient, master_address: str
) -> None:
    assert isinstance(await info.twap_slice_fills(master_address), list)


async def test_sub_accounts(info: IntegrationInfoClient, master_address: str) -> None:
    result = await info.sub_accounts(master_address)
    assert result is None or isinstance(result, list)


async def test_vault_details(
    info: IntegrationInfoClient, subaccount_address: str
) -> None:
    result = await info.vault_details(subaccount_address)
    assert result is None or isinstance(result, dict)


async def test_vault_equities(info: IntegrationInfoClient, master_address: str) -> None:
    assert isinstance(await info.vault_equities(master_address), list)


async def test_user_role(
    info: IntegrationInfoClient,
    master_address: str,
    api_wallet_address: str,
    subaccount_address: str,
) -> None:
    for address in (master_address, api_wallet_address, subaccount_address):
        role = await info.user_role(address)
        assert role["role"] in {"missing", "user", "vault", "agent", "subAccount"}


async def test_portfolio(info: IntegrationInfoClient, master_address: str) -> None:
    assert isinstance(await info.portfolio(master_address), list)


async def test_referral(info: IntegrationInfoClient, master_address: str) -> None:
    assert isinstance(await info.referral(master_address), dict)


async def test_user_fees(info: IntegrationInfoClient, master_address: str) -> None:
    assert isinstance(await info.user_fees(master_address), dict)


async def test_delegations(info: IntegrationInfoClient, master_address: str) -> None:
    assert isinstance(await info.delegations(master_address), list)


async def test_staking_summary(
    info: IntegrationInfoClient, master_address: str
) -> None:
    assert isinstance(await info.staking_summary(master_address), dict)


async def test_staking_history(
    info: IntegrationInfoClient, master_address: str
) -> None:
    assert isinstance(await info.staking_history(master_address), list)


async def test_staking_rewards(
    info: IntegrationInfoClient, master_address: str
) -> None:
    assert isinstance(await info.staking_rewards(master_address), list)


async def test_user_dex_abstraction(
    info: IntegrationInfoClient, master_address: str
) -> None:
    assert isinstance(await info.user_dex_abstraction(master_address), bool)


async def test_user_abstraction(
    info: IntegrationInfoClient, master_address: str
) -> None:
    assert isinstance(await info.user_abstraction(master_address), str)


async def test_aligned_quote_token_info(info: IntegrationInfoClient) -> None:
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


async def test_perp_meta(info: IntegrationInfoClient) -> None:
    assert (await info.perp_meta())["universe"]


async def test_perp_meta_and_contexts(info: IntegrationInfoClient) -> None:
    meta, contexts = await info.perp_meta_and_contexts()
    assert len(meta["universe"]) == len(contexts)


async def test_all_perp_metas(info: IntegrationInfoClient) -> None:
    assert await info.all_perp_metas()


async def test_perp_dexes(info: IntegrationInfoClient) -> None:
    assert isinstance(await info.perp_dexes(), list)


async def test_perp_account_state(
    info: IntegrationInfoClient, master_address: str
) -> None:
    assert "assetPositions" in await info.perp_account_state(master_address)


async def test_funding_updates(
    info: IntegrationInfoClient, master_address: str
) -> None:
    assert isinstance(await info.funding_updates(master_address, _start_time()), list)


async def test_non_funding_ledger_updates(
    info: IntegrationInfoClient, master_address: str
) -> None:
    updates = await info.non_funding_ledger_updates(master_address, _start_time())
    assert isinstance(updates, list)


async def test_funding_history(info: IntegrationInfoClient, markets: Markets) -> None:
    assert isinstance(await info.funding_history(markets.perp, _start_time()), list)


async def test_predicted_fundings(info: IntegrationInfoClient) -> None:
    assert isinstance(await info.predicted_fundings(), list)


async def test_open_interest_cap(info: IntegrationInfoClient) -> None:
    assert all(
        isinstance(coin, str) for coin in await info.perps_at_open_interest_cap()
    )


async def test_perp_deploy_auction_status(info: IntegrationInfoClient) -> None:
    assert isinstance(await info.perp_deploy_auction_status(), dict)


async def test_active_asset_data(
    info: IntegrationInfoClient, markets: Markets, master_address: str
) -> None:
    result = await info.active_asset_data(master_address, markets.perp)
    assert isinstance(result, dict)


async def test_spot_meta(info: IntegrationInfoClient) -> None:
    assert (await info.spot_meta())["tokens"]


async def test_spot_meta_and_contexts(info: IntegrationInfoClient) -> None:
    meta, contexts = await info.spot_meta_and_contexts()
    assert {pair["name"] for pair in meta["universe"]} <= {
        context["coin"] for context in contexts
    }


async def test_spot_account_state(
    info: IntegrationInfoClient, master_address: str
) -> None:
    assert "balances" in await info.spot_account_state(master_address)


async def test_spot_deploy_state(
    info: IntegrationInfoClient, master_address: str
) -> None:
    assert isinstance(await info.spot_deploy_state(master_address), dict)


async def test_token_details(info: IntegrationInfoClient, markets: Markets) -> None:
    result = await info.token_details(markets.token_id)
    assert result is None or isinstance(result, dict)


async def test_perp_dex_names(info: IntegrationInfoClient) -> None:
    assert "" in await info.perp_dex_names()


async def test_refresh_metadata(info: IntegrationInfoClient) -> None:
    assert await info.refresh_metadata() is None


async def test_coin_name(info: IntegrationInfoClient, markets: Markets) -> None:
    assert await info.coin_name(markets.perp) == markets.perp


async def test_coin_symbol(info: IntegrationInfoClient, markets: Markets) -> None:
    assert await info.coin_symbol(markets.perp)


async def test_asset_id(info: IntegrationInfoClient, markets: Markets) -> None:
    assert await info.asset_id(markets.perp) >= 0


async def test_size_decimals(info: IntegrationInfoClient, markets: Markets) -> None:
    assert await info.size_decimals(markets.perp) >= 0


async def test_spot_token_metadata(
    info: IntegrationInfoClient, markets: Markets
) -> None:
    assert (await info.spot_token_metadata(markets.spot))["tokenId"]


async def test_token_id(info: IntegrationInfoClient, markets: Markets) -> None:
    assert await info.token_id(markets.spot) == markets.token_id


@pytest.mark.parametrize("market", ["perp", "spot"])
async def test_mark_price(
    info: IntegrationInfoClient, markets: Markets, market: str
) -> None:
    assert await info.mark_price(getattr(markets, market)) > 0


async def test_mid_price(info: IntegrationInfoClient, markets: Markets) -> None:
    assert await info.mid_price(markets.perp) > 0


async def test_account_state(
    info: IntegrationInfoClient, markets: Markets, master_address: str
) -> None:
    state = await info.account_state(master_address, dexs=markets.dexs[:2])
    assert {"perp", "spot", "dexs"} <= state.keys()


async def test_positions(info: IntegrationInfoClient, subaccount_address: str) -> None:
    positions = await info.positions(subaccount_address)
    assert isinstance(positions, list)


@pytest.mark.parametrize(
    "coin", ["BTC", "HYPE/USDC", "@107", "xyz:NVDA", "flx:TSLA", "vntl:OPENAI"]
)
async def test_mainnet_legacy_coin_aliases(
    info: IntegrationInfoClient, coin: str
) -> None:
    if info.network is Network.TESTNET:
        raise pytest.skip.Exception("aliases are mainnet-only")

    assert await info.coin_symbol(coin)


@pytest.mark.parametrize("coin", ["xyz:SLIVER", "USDT/USDC"])
async def test_mainnet_legacy_unsupported_aliases(
    info: IntegrationInfoClient, coin: str
) -> None:
    if info.network is Network.TESTNET:
        raise pytest.skip.Exception("aliases are mainnet-only")

    with pytest.raises(ValueError):
        await info.mark_price(coin)


async def test_hype_price_parity(info: IntegrationInfoClient) -> None:
    if info.network is Network.TESTNET:
        raise pytest.skip.Exception("@107 alias is mainnet-only")

    assert await info.mark_price("HYPE/USDC") == pytest.approx(
        await info.mark_price("@107"), abs=0.01
    )
