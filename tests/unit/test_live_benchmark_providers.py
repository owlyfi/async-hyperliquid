from types import SimpleNamespace
from typing import Any, cast

import pytest

import benchmarks.live.providers as provider_module
from benchmarks.live.models import BenchmarkFailure, CanonicalOrder, OrderPair
from benchmarks.live.preflight import Credentials
from benchmarks.live.providers import (
    AsyncHyperliquidProvider,
    AsyncMarketSource,
    CcxtProvider,
    ProviderSet,
    SdkProvider,
    assert_wire_parity,
    validate_provider_wire_parity,
)
from benchmarks.live.workload import build_order_pair


PLACE_RESPONSE = {
    "status": "ok",
    "response": {
        "type": "order",
        "data": {"statuses": [{"resting": {"oid": 101}}, {"resting": {"oid": 202}}]},
    },
}
CANCEL_RESPONSE = {
    "status": "ok",
    "response": {"type": "cancel", "data": {"statuses": ["success", "success"]}},
}
ONE_CANCEL_RESPONSE = {
    "status": "ok",
    "response": {"type": "cancel", "data": {"statuses": ["success"]}},
}


def _pair() -> OrderPair:
    return build_order_pair(
        100_000.0, 5, target_notional=11.0, cloids=("0x" + "01" * 16, "0x" + "02" * 16)
    )


class AsyncClientStub:
    def __init__(self, resting_oids: tuple[int, ...] = (101, 202)) -> None:
        self.resting_oids = resting_oids
        self.placed: object = None
        self.cancelled_oids: object = None
        self.cancelled_cloids: object = None
        self.closed = False

    async def place_orders(self, orders: object) -> object:
        self.placed = orders
        return {
            "status": "ok",
            "response": {
                "type": "order",
                "data": {
                    "statuses": [
                        {"resting": {"oid": oid}} for oid in self.resting_oids
                    ]
                },
            },
        }

    async def cancel_orders(self, orders: object) -> object:
        self.cancelled_oids = orders
        count = len(cast(tuple[object, ...], orders))
        return CANCEL_RESPONSE if count == 2 else ONE_CANCEL_RESPONSE

    async def cancel_orders_by_cloid(self, orders: object) -> object:
        self.cancelled_cloids = orders
        count = len(cast(tuple[object, ...], orders))
        return CANCEL_RESPONSE if count == 2 else ONE_CANCEL_RESPONSE

    async def close(self) -> None:
        self.closed = True


async def test_async_provider_uses_public_batch_methods() -> None:
    client = AsyncClientStub()
    provider = AsyncHyperliquidProvider(
        cast(Any, client), coin="BTC", asset=0, size_decimals=5
    )
    pair = _pair()

    assert await provider.place(pair) == (101, 202)
    await provider.cancel_oids(pair.as_tuple(), (101, 202))
    await provider.cancel_cloids((pair.buy,))
    await provider.close()

    placed = cast(tuple[dict[str, object], ...], client.placed)
    assert [order["is_buy"] for order in placed] == [True, False]
    assert [order["order_type"] for order in placed] == [
        {"limit": {"tif": "Alo"}},
        {"limit": {"tif": "Alo"}},
    ]
    assert [str(order["cloid"]) for order in placed] == [
        pair.buy.cloid,
        pair.sell.cloid,
    ]
    assert [order.oid for order in cast(tuple[Any, ...], client.cancelled_oids)] == [
        101,
        202,
    ]
    assert [
        str(order.cloid) for order in cast(tuple[Any, ...], client.cancelled_cloids)
    ] == [pair.buy.cloid]
    assert client.closed is True


async def test_async_provider_places_arbitrary_order_batch() -> None:
    client = AsyncClientStub(resting_oids=tuple(range(100, 120)))
    provider = AsyncHyperliquidProvider(
        cast(Any, client), coin="BTC", asset=0, size_decimals=5
    )
    orders = tuple(
        CanonicalOrder(
            is_buy=index % 2 == 0,
            price=90_000.0 if index % 2 == 0 else 110_000.0,
            size=0.00013 if index % 2 == 0 else 0.0001,
            cloid=f"0x{index + 1:032x}",
        )
        for index in range(20)
    )

    assert await provider.place_many(orders) == tuple(range(100, 120))
    assert len(cast(tuple[object, ...], client.placed)) == 20


class SyncCloseStub:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class SdkClientStub:
    def __init__(self) -> None:
        self.placed: object = None
        self.cancelled_oids: object = None
        self.cancelled_cloids: object = None
        self.session = SyncCloseStub()

    def bulk_orders(self, orders: object) -> object:
        self.placed = orders
        return PLACE_RESPONSE

    def bulk_cancel(self, orders: object) -> object:
        self.cancelled_oids = orders
        count = len(cast(list[object], orders))
        return CANCEL_RESPONSE if count == 2 else ONE_CANCEL_RESPONSE

    def bulk_cancel_by_cloid(self, orders: object) -> object:
        self.cancelled_cloids = orders
        count = len(cast(list[object], orders))
        return CANCEL_RESPONSE if count == 2 else ONE_CANCEL_RESPONSE


async def test_sdk_provider_uses_public_batch_methods() -> None:
    client = SdkClientStub()
    provider = SdkProvider(cast(Any, client), coin="BTC", asset=0, size_decimals=5)
    pair = _pair()

    assert await provider.place(pair) == (101, 202)
    await provider.cancel_oids(pair.as_tuple(), (101, 202))
    await provider.cancel_cloids((pair.sell,))
    await provider.close()

    placed = cast(list[dict[str, object]], client.placed)
    assert [order["is_buy"] for order in placed] == [True, False]
    assert [order["order_type"] for order in placed] == [
        {"limit": {"tif": "Alo"}},
        {"limit": {"tif": "Alo"}},
    ]
    assert [cast(Any, order["cloid"]).to_raw() for order in placed] == [
        pair.buy.cloid,
        pair.sell.cloid,
    ]
    assert cast(list[dict[str, object]], client.cancelled_oids) == [
        {"coin": "BTC", "oid": 101},
        {"coin": "BTC", "oid": 202},
    ]
    cloid_cancel = cast(list[dict[str, object]], client.cancelled_cloids)
    assert cast(Any, cloid_cancel[0]["cloid"]).to_raw() == pair.sell.cloid
    assert client.session.closed is True


class CcxtClientStub:
    def __init__(self) -> None:
        self.created: object = None
        self.cancelled: list[tuple[list[str], str, dict[str, object]]] = []
        self.closed = False

    def create_order_request(
        self,
        symbol: str,
        order_type: str,
        side: str,
        amount: str,
        price: str,
        params: dict[str, object],
    ) -> dict[str, object]:
        return {
            "a": 0,
            "b": side == "buy",
            "p": price,
            "s": amount,
            "r": False,
            "t": {"limit": {"tif": "Alo"}},
            "c": params["clientOrderId"],
        }

    def create_orders(
        self, orders: object, params: dict[str, object]
    ) -> list[dict[str, object]]:
        self.created = (orders, params)
        return [
            {"id": "101", "status": None, "info": {"resting": {"oid": 101}}},
            {"id": "202", "status": None, "info": {"resting": {"oid": 202}}},
        ]

    def cancel_orders(
        self, ids: list[str], symbol: str, params: dict[str, object]
    ) -> list[dict[str, object]]:
        self.cancelled.append((ids, symbol, params))
        expected = len(cast(list[object], params.get("clientOrderId", ids)))
        return [{"status": "success", "info": "success"} for _ in range(expected)]

    def close(self) -> None:
        self.closed = True


async def test_ccxt_provider_uses_public_batch_methods_and_vault() -> None:
    client = CcxtClientStub()
    vault = "0x" + "33" * 20
    provider = CcxtProvider(
        cast(Any, client),
        coin="BTC",
        symbol="BTC/USDC:USDC",
        asset=0,
        size_decimals=5,
        vault_address=vault,
    )
    pair = _pair()

    assert await provider.place(pair) == (101, 202)
    await provider.cancel_oids(pair.as_tuple(), (101, 202))
    await provider.cancel_cloids((pair.buy,))
    await provider.close()

    created, global_params = cast(
        tuple[list[dict[str, object]], dict[str, object]], client.created
    )
    assert global_params == {"vaultAddress": vault}
    assert [order["params"] for order in created] == [
        {"postOnly": True, "clientOrderId": pair.buy.cloid},
        {"postOnly": True, "clientOrderId": pair.sell.cloid},
    ]
    assert client.cancelled == [
        (["101", "202"], "BTC/USDC:USDC", {"vaultAddress": vault}),
        (
            ["0"],
            "BTC/USDC:USDC",
            {"vaultAddress": vault, "clientOrderId": [pair.buy.cloid]},
        ),
    ]
    assert client.closed is True


def test_all_provider_wire_orders_must_match() -> None:
    pair = _pair()
    wire = ({"a": 0, "b": True}, {"a": 0, "b": False})

    assert_wire_parity({"async-hyperliquid": wire, "sdk": wire, "ccxt": wire})

    with pytest.raises(BenchmarkFailure, match="wire-order parity"):
        assert_wire_parity(
            {
                "async-hyperliquid": wire,
                "sdk": wire,
                "ccxt": (wire[0], {**wire[1], "b": True}),
            }
        )
    assert pair.buy.is_buy is True


def test_real_adapter_wire_builders_produce_the_same_orders() -> None:
    pair = _pair()
    async_provider = AsyncHyperliquidProvider(
        cast(Any, AsyncClientStub()), coin="BTC", asset=0, size_decimals=5
    )
    sdk_provider = SdkProvider(
        cast(Any, SdkClientStub()), coin="BTC", asset=0, size_decimals=5
    )
    ccxt_provider = CcxtProvider(
        cast(Any, CcxtClientStub()),
        coin="BTC",
        symbol="BTC/USDC:USDC",
        asset=0,
        size_decimals=5,
        vault_address="0x" + "33" * 20,
    )

    validate_provider_wire_parity((async_provider, sdk_provider, ccxt_provider), pair)


class MidInfoStub:
    async def mid_price(self, coin: str) -> float:
        assert coin == "BTC"
        return 100_000.0


async def test_market_source_returns_one_mid_and_size_precision() -> None:
    source = AsyncMarketSource(cast(Any, MidInfoStub()), coin="BTC", size_decimals=5)

    assert await source.snapshot() == (100_000.0, 5)


class CloseProviderStub:
    def __init__(self, name: str, closed: list[str]) -> None:
        self.name = name
        self.closed = closed

    async def close(self) -> None:
        self.closed.append(self.name)


async def test_provider_set_closes_owned_resources_in_reverse_order() -> None:
    closed: list[str] = []
    first = CloseProviderStub("first", closed)
    second = CloseProviderStub("second", closed)
    recovery = CloseProviderStub("recovery", closed)
    source = AsyncMarketSource(cast(Any, MidInfoStub()), coin="BTC", size_decimals=5)
    providers = ProviderSet(
        measured=cast(Any, (first, second)),
        recovery=cast(Any, recovery),
        mid_source=source,
        owned=cast(Any, (first, recovery, second)),
    )

    await providers.close()

    assert closed == ["second", "recovery", "first"]


def test_ccxt_market_resolves_perpetual_by_unified_base() -> None:
    btc_swap = {
        "symbol": "BTC/USDC:USDC",
        "id": "3",
        "base": "BTC",
        "baseId": "3",
        "swap": True,
    }
    markets = {
        "BTC/USDC": {
            "symbol": "BTC/USDC",
            "id": "@50",
            "base": "BTC",
            "baseId": "10050",
            "swap": False,
        },
        "BTC/USDC:USDC": btc_swap,
    }

    assert provider_module._ccxt_market(markets, "BTC") is btc_swap


async def test_factory_builds_recovery_first_and_closes_partial_clients(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clients: list[Any] = []

    class FakeInfo:
        def __init__(self, index: int) -> None:
            self.index = index

        async def refresh_metadata(self) -> None:
            assert clients[self.index].opened is True, "metadata read before open"
            if self.index == 1:
                raise RuntimeError("measured metadata failed")

        async def _market_info(self, coin: str) -> object:
            assert coin == "BTC"
            return SimpleNamespace(asset=0, size_decimals=5)

        async def user_role(self, address: str) -> object:
            raise AssertionError(f"recovery must not query roles: {address}")

    class FakeAsyncHyperliquid:
        def __init__(self, *args: object, **kwargs: object) -> None:
            del args, kwargs
            self.info = FakeInfo(len(clients))
            self.opened = False
            self.closed = False
            clients.append(self)

        async def open(self) -> None:
            self.opened = True

        async def close(self) -> None:
            self.closed = True

    monkeypatch.setattr(provider_module, "AsyncHyperliquid", FakeAsyncHyperliquid)
    credentials = Credentials(
        master_address="0x1111111111111111111111111111111111111111",
        api_wallet_address="0x2222222222222222222222222222222222222222",
        signing_key="0x" + "11" * 32,
        subaccount_address="0x3333333333333333333333333333333333333333",
    )

    with pytest.raises(RuntimeError, match="measured metadata failed"):
        await provider_module.build_providers(credentials)

    assert len(clients) == 2
    assert all(client.opened for client in clients)
    assert all(client.closed for client in clients)


async def test_factory_sets_finite_timeouts_and_closes_failed_ccxt_setup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import ccxt
    import hyperliquid.exchange as sdk_exchange

    master = "0x1111111111111111111111111111111111111111"
    api_wallet = "0x2222222222222222222222222222222222222222"
    subaccount = "0x3333333333333333333333333333333333333333"
    async_clients: list[Any] = []
    sdk_timeouts: list[float] = []
    sdk_sessions: list[SyncCloseStub] = []
    ccxt_configs: list[dict[str, object]] = []
    ccxt_clients: list[Any] = []

    class FakeInfo:
        async def refresh_metadata(self) -> None:
            return None

        async def _market_info(self, coin: str) -> object:
            assert coin == "BTC"
            return SimpleNamespace(asset=0, size_decimals=5)

        async def user_role(self, address: str) -> object:
            if address == api_wallet:
                return {"role": "agent", "data": {"user": master}}
            assert address == subaccount
            return {"role": "subAccount", "data": {"master": master}}

    class FakeAsyncHyperliquid:
        def __init__(self, *args: object, **kwargs: object) -> None:
            del args, kwargs
            self.info = FakeInfo()
            self.opened = False
            self.closed = False
            async_clients.append(self)

        async def open(self) -> None:
            self.opened = True

        async def close(self) -> None:
            self.closed = True

    class FakeSdkInfo:
        asset_to_sz_decimals = {0: 5}

        def name_to_asset(self, coin: str) -> int:
            assert coin == "BTC"
            return 0

    class FakeExchange:
        def __init__(self, *args: object, timeout: float, **kwargs: object) -> None:
            del args, kwargs
            sdk_timeouts.append(timeout)
            self.info = FakeSdkInfo()
            self.session = SyncCloseStub()
            sdk_sessions.append(self.session)

    class FakeCcxt:
        def __init__(self, config: dict[str, object]) -> None:
            ccxt_configs.append(config)
            ccxt_clients.append(self)
            self.closed = False

        def set_sandbox_mode(self, enabled: bool) -> None:
            assert enabled is True

        def load_markets(self) -> object:
            raise RuntimeError("ccxt metadata failed")

        def close(self) -> None:
            self.closed = True

    monkeypatch.setattr(provider_module, "AsyncHyperliquid", FakeAsyncHyperliquid)
    monkeypatch.setattr(sdk_exchange, "Exchange", FakeExchange)
    monkeypatch.setattr(ccxt, "hyperliquid", FakeCcxt)
    credentials = Credentials(
        master_address=master,
        api_wallet_address=api_wallet,
        signing_key="0x" + "11" * 32,
        subaccount_address=subaccount,
    )

    with pytest.raises(RuntimeError, match="ccxt metadata failed"):
        await provider_module.build_providers(credentials)

    assert sdk_timeouts == [15.0]
    assert ccxt_configs[0]["timeout"] == 15_000
    assert all(session.closed for session in sdk_sessions)
    assert all(client.opened for client in async_clients)
    assert all(client.closed for client in (*async_clients, *ccxt_clients))
