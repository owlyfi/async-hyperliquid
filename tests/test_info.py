import pytest

from tests.conftest import get_is_mainnet
from async_hyperliquid import AsyncHyperliquid

is_mainnet = get_is_mainnet()
is_testnet = not is_mainnet


@pytest.mark.asyncio(loop_scope="session")
async def test_get_metas(hl: AsyncHyperliquid) -> None:
    metas = await hl.get_metas()
    assert "perp" in metas

    perp_metas = metas["perp"]
    assert "universe" in perp_metas

    assert "spot" in metas
    spot_metas = metas["spot"]
    assert "tokens" in spot_metas
    assert "universe" in spot_metas


@pytest.mark.asyncio(loop_scope="session")
async def test_get_all_metas(hl: AsyncHyperliquid) -> None:
    metas = await hl.get_all_metas()
    assert "perp" in metas
    assert "universe" in metas["perp"]

    assert "spots" in metas
    spot_metas = metas["spots"]  # type: ignore
    assert "tokens" in spot_metas
    assert "universe" in spot_metas

    assert "dexs" in metas
    assert isinstance(metas["dexs"], dict)


@pytest.mark.asyncio(loop_scope="session")
async def test_get_all_dex_name(hl: AsyncHyperliquid) -> None:
    dexs = await hl.get_all_dex_name()
    assert len(dexs) > 0
    assert "" in dexs
    assert "xyz" in dexs
    assert "flx" in dexs
    assert "vntl" in dexs


@pytest.mark.asyncio(loop_scope="session")
@pytest.mark.skipif(is_testnet, reason="Only test on mainnet")
@pytest.mark.parametrize(
    "coin, name",
    [
        ("HYPE/USDC", "@107"),
        ("PURR/USDC", "PURR/USDC"),
        ("@142", "@142"),
        ("UBTC/USDC", "@142"),
        ("xyz:XYZ100", "xyz:XYZ100"),
        ("xyz:NVDA", "xyz:NVDA"),
        ("flx:CRCL", "flx:CRCL"),
        ("flx:TSLA", "flx:TSLA"),
        ("vntl:OPENAI", "vntl:OPENAI"),
        ("vntl:SPACEX", "vntl:SPACEX"),
        pytest.param(
            "ETH/USDC",
            None,
            marks=pytest.mark.xfail(
                raises=ValueError, reason="ETH/USDC is not supported"
            ),
        ),
    ],
)
async def test_get_coin_name(
    hl: AsyncHyperliquid, coin: str, name: str
) -> None:
    coin_name = await hl.get_coin_name(coin)
    assert coin_name == name


@pytest.mark.asyncio(loop_scope="session")
@pytest.mark.skipif(is_testnet, reason="Only test on mainnet")
@pytest.mark.parametrize(
    "coin, asset",
    [
        ("BTC", 0),  # perp
        ("UBTC/USDC", 10142),  # spot
        ("xyz:NVDA", 110002),  # xyz perp
        ("flx:TSLA", 120000),  # flx perp
        ("vntl:OPENAI", 130001),  # vntl perp
    ],
)
async def test_get_coin_asset(
    hl: AsyncHyperliquid, coin: str, asset: int
) -> None:
    coin_asset = await hl.get_coin_asset(coin)
    assert coin_asset == asset


@pytest.mark.asyncio(loop_scope="session")
@pytest.mark.skipif(is_testnet, reason="Only test on mainnet")
@pytest.mark.parametrize(
    "coin, symbol",
    [
        ("BTC", "BTC"),  # perp
        ("UBTC/USDC", "UBTC/USDC"),  # spot
        ("@142", "UBTC/USDC"),  # spot
        ("@107", "HYPE/USDC"),  # spot
        ("PURR/USDC", "PURR/USDC"),  # spot
        ("xyz:XYZ100", "xyz:XYZ100"),  # xyz perp
        ("xyz:NVDA", "xyz:NVDA"),  # xyz perp
        ("flx:CRCL", "flx:CRCL"),  # flx perp
        ("flx:TSLA", "flx:TSLA"),  # flx perp
        ("vntl:OPENAI", "vntl:OPENAI"),  # vntl perp
        ("vntl:SPACEX", "vntl:SPACEX"),  # vntl perp
        pytest.param(
            "ETH/USDC",
            None,
            marks=pytest.mark.xfail(
                raises=ValueError, reason="ETH/USDC is not supported"
            ),
        ),
    ],
)
async def test_get_coin_symbol(
    hl: AsyncHyperliquid, coin: str, symbol: str
) -> None:
    coin_symbol = await hl.get_coin_symbol(coin)
    assert coin_symbol == symbol


@pytest.mark.asyncio(loop_scope="session")
@pytest.mark.skipif(is_testnet, reason="Only test on mainnet")
@pytest.mark.parametrize(
    "coin, sz_decimals",
    [
        ("BTC", 5),  # perp
        ("UBTC/USDC", 5),  # spot
        ("xyz:NVDA", 3),  # xyz perp
        ("flx:TSLA", 2),  # flx perp
        ("vntl:OPENAI", 3),  # vntl perp
    ],
)
async def test_get_coin_sz_decimals(
    hl: AsyncHyperliquid, coin: str, sz_decimals: int
):
    coin_sz_decimals = await hl.get_coin_sz_decimals(coin)
    assert coin_sz_decimals == sz_decimals


@pytest.mark.asyncio(loop_scope="session")
@pytest.mark.skipif(is_testnet, reason="Only test on mainnet")
async def test_get_token_info(hl: AsyncHyperliquid):
    token_info = await hl.get_token_info("UBTC/USDC")
    assert token_info == {
        "name": "UBTC",
        "szDecimals": 5,
        "weiDecimals": 10,
        "index": 197,
        "tokenId": "0x8f254b963e8468305d409b33aa137c67",
        "isCanonical": False,
        "evmContract": {
            "address": "0x9fdbda0a5e284c32744d2f17ee5c74b284993463",
            "evm_extra_wei_decimals": -2,
        },
        "fullName": "Unit Bitcoin",
        "deployerTradingFeeShare": "1.0",
    }


@pytest.mark.asyncio(loop_scope="session")
@pytest.mark.skipif(is_testnet, reason="Only test on mainnet")
async def test_get_token_id(hl: AsyncHyperliquid):
    token_id = await hl.get_token_id("UBTC/USDC")
    assert token_id == "0x8f254b963e8468305d409b33aa137c67"


@pytest.mark.asyncio(loop_scope="session")
@pytest.mark.parametrize(
    "coin, price",
    [
        ("BTC", 10_000),  # perp
        ("UBTC/USDC", 10_000),  # spot
    ],
)
async def test_get_market_price(hl: AsyncHyperliquid, coin: str, price: float):
    coin_px = await hl.get_market_price(coin)
    print(coin_px)
    # assert price
    assert coin_px > price


@pytest.mark.asyncio(loop_scope="session")
async def test_get_all_market_prices(hl: AsyncHyperliquid):
    # No need to test this, it's already tested in test_get_market_price
    pass


@pytest.mark.asyncio(loop_scope="session")
@pytest.mark.parametrize(
    "coin, price",
    [
        ("BTC", 10_000),  # perp
        ("UBTC/USDC", 10_000),  # spot
        ("xyz:NVDA", 100),  # xyz perp
        ("flx:TSLA", 100),  # flx perp
        ("vntl:OPENAI", 100),  # nvtl perp
    ],
)
async def test_get_mid_price(hl: AsyncHyperliquid, coin: str, price: float):
    mid_px = await hl.get_mid_price(coin)
    assert mid_px > price


@pytest.mark.asyncio(loop_scope="session")
async def test_get_all_mids(hl: AsyncHyperliquid):
    pass


@pytest.mark.asyncio(loop_scope="session")
async def test_get_perp_account_state(hl: AsyncHyperliquid):
    state = await hl.get_perp_account_state()
    assert "marginSummary" in state
    assert "crossMarginSummary" in state
    assert "crossMaintenanceMarginUsed" in state
    assert "withdrawable" in state
    assert "assetPositions" in state
    assert isinstance(state["assetPositions"], list)
    assert "time" in state


@pytest.mark.asyncio(loop_scope="session")
async def test_get_spot_account_state(hl: AsyncHyperliquid):
    state = await hl.get_spot_account_state()
    assert "balances" in state
    assert isinstance(state["balances"], list)


@pytest.mark.asyncio(loop_scope="session")
async def test_get_account_state(hl: AsyncHyperliquid):
    state = await hl.get_account_state()
    assert "perp" in state
    assert "spot" in state
    assert "dexs" in state

    assert isinstance(state["dexs"], dict)

    assert "xyz" in state["dexs"]
    assert "flx" in state["dexs"]
    assert "vntl" in state["dexs"]


@pytest.mark.asyncio(loop_scope="session")
async def test_get_account_portfolio(hl: AsyncHyperliquid):
    pf = await hl.get_account_portfolio()

    assert isinstance(pf, list)
    assert len(pf) == 8


@pytest.mark.asyncio(loop_scope="session")
async def test_get_latest_ledgers(hl: AsyncHyperliquid):
    updates = await hl.get_latest_ledgers()

    assert isinstance(updates, list)


@pytest.mark.asyncio(loop_scope="session")
async def test_get_latest_deposits(hl: AsyncHyperliquid):
    updates = await hl.get_latest_deposits()

    assert isinstance(updates, list)


@pytest.mark.asyncio(loop_scope="session")
async def test_get_latest_withdraws(hl: AsyncHyperliquid):
    updates = await hl.get_latest_withdraws()

    assert isinstance(updates, list)


@pytest.mark.asyncio(loop_scope="session")
async def test_get_latest_transfers(hl: AsyncHyperliquid):
    updates = await hl.get_latest_transfers()

    assert isinstance(updates, list)


@pytest.mark.asyncio(loop_scope="session")
async def test_get_user_open_orders(hl: AsyncHyperliquid):
    orders = await hl.get_user_open_orders()

    assert isinstance(orders, list)


@pytest.mark.asyncio(loop_scope="session")
@pytest.mark.skipif(is_testnet, reason="Only test on mainnet")
async def test_get_order_status(hl: AsyncHyperliquid):
    address = "0xf97ad6704baec104d00b88e0c157e2b7b3a1ddd1"
    orders = await hl.get_user_open_orders(address=address)
    if not orders:
        return

    order = orders[0]
    order_id = order["oid"]

    order_status = await hl.get_order_status(order_id, address=address)
    assert order_status["status"] == "order"
    assert order_status["order"] is not None

    inner_order = order_status["order"]["order"]
    assert inner_order["oid"] == order_id
    assert inner_order["coin"] == order["coin"]
    assert inner_order["side"] == order["side"]
    assert inner_order["sz"] == order["sz"]
    assert inner_order["limitPx"] == order["limitPx"]


@pytest.mark.asyncio(loop_scope="session")
async def test_get_dex_positions(hl: AsyncHyperliquid):
    address = "0xf97ad6704baec104d00b88e0c157e2b7b3a1ddd1"
    positions = await hl.get_dex_positions(address, "xyz")

    assert isinstance(positions, list)


@pytest.mark.asyncio(loop_scope="session")
async def test_get_all_positions(hl: AsyncHyperliquid):
    address = "0xf97ad6704baec104d00b88e0c157e2b7b3a1ddd1"
    positions = await hl.get_all_positions(address)

    assert isinstance(positions, list)


@pytest.mark.asyncio(loop_scope="session")
async def test_get_user_dex_abstraction(hl: AsyncHyperliquid):
    address = "0xf97ad6704baec104d00b88e0c157e2b7b3a1ddd1"
    resp = await hl.get_user_dex_abstraction(address)
    assert isinstance(resp, bool)
    assert resp is True


@pytest.mark.asyncio(loop_scope="session")
async def test_get_user_abstraction_state(hl: AsyncHyperliquid):
    address = "0xf97ad6704baec104d00b88e0c157e2b7b3a1ddd1"
    abstraction_state = await hl.get_user_abstraction_state(address)
    assert abstraction_state == "dexAbstraction"
