import os
from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
import pytest_asyncio

from async_hyperliquid import AsyncHyperliquid
from async_hyperliquid.types import (
    Cloid,
    Network,
    PlaceOrderRequest,
    TimeInForce,
    limit_order_type,
)
from tests.integration.config import require_env
from tests.integration.conftest import _prepare_exchange, _validate_exchange_roles

from .order_checks import (
    _resting_oid,
    assert_order_owner,
    cleanup_shared_cloid_orders,
    place_and_assert_order_owner,
    requires_order_cleanup,
)


pytestmark = [pytest.mark.exchange, pytest.mark.asyncio(loop_scope="session")]


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def sub_account_hl() -> AsyncIterator[AsyncHyperliquid]:
    _prepare_exchange()
    subaccount = require_env("HL_SUB", os.environ)
    async with AsyncHyperliquid(
        subaccount,
        require_env("HL_SK", os.environ),
        vault_address=subaccount,
        network=Network.TESTNET,
        dexs=("",),
    ) as client:
        await client.info.refresh_metadata()
        await _validate_exchange_roles(client.info)
        yield client


async def _limit_request(client: AsyncHyperliquid) -> PlaceOrderRequest:
    spot = await client.info.spot_meta()
    coin = spot["universe"][0]["name"]
    mid = await client.info.mid_price(coin)
    size_decimals = await client.info.size_decimals(coin)
    return {
        "coin": coin,
        "is_buy": True,
        "sz": round(20 / (mid * 0.5), size_decimals),
        "px": mid * 0.5,
        "is_market": False,
        "order_type": limit_order_type(TimeInForce.ALO),
    }


async def test_routes_orders_to_expected_owner(
    master_hl: AsyncHyperliquid, master_address: str, subaccount_address: str
) -> None:
    await place_and_assert_order_owner(
        master_hl, master_address, subaccount_address, await _limit_request(master_hl)
    )


async def test_routes_orders_to_canonical_subaccount(
    sub_hl: AsyncHyperliquid, master_address: str, subaccount_address: str
) -> None:
    await place_and_assert_order_owner(
        sub_hl, subaccount_address, master_address, await _limit_request(sub_hl)
    )


async def test_routes_orders_from_subaccount_address(
    sub_account_hl: AsyncHyperliquid, master_address: str, subaccount_address: str
) -> None:
    await place_and_assert_order_owner(
        sub_account_hl,
        subaccount_address,
        master_address,
        await _limit_request(sub_account_hl),
    )


async def test_shared_cloid_stays_isolated_between_master_and_subaccount(
    master_hl: AsyncHyperliquid,
    sub_hl: AsyncHyperliquid,
    master_address: str,
    subaccount_address: str,
) -> None:
    cloid = Cloid.from_int(uuid4().int)
    master_order = await _limit_request(master_hl)
    master_order["cloid"] = cloid
    subaccount_order = await _limit_request(sub_hl)
    subaccount_order["cloid"] = cloid
    failure: BaseException | None = None
    master_cleanup_required = False
    subaccount_cleanup_required = False
    try:
        master_cleanup_required = True
        master_response = await master_hl.place_limit_order(master_order)
        master_cleanup_required = requires_order_cleanup(master_response)
        _resting_oid(master_response)
        subaccount_cleanup_required = True
        subaccount_response = await sub_hl.place_limit_order(subaccount_order)
        subaccount_cleanup_required = requires_order_cleanup(subaccount_response)
        _resting_oid(subaccount_response)
        await assert_order_owner(master_hl, master_address, cloid)
        await assert_order_owner(sub_hl, subaccount_address, cloid)
    except BaseException as error:
        failure = error
    finally:
        await cleanup_shared_cloid_orders(
            master_hl,
            master_address,
            master_order["coin"],
            sub_hl,
            subaccount_address,
            subaccount_order["coin"],
            cloid,
            failure=failure,
            master_cleanup_required=master_cleanup_required,
            subaccount_cleanup_required=subaccount_cleanup_required,
        )
