from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol, cast

from async_hyperliquid import AsyncHyperliquid
from async_hyperliquid._internal.encoding import _wire_float, encode_order
from async_hyperliquid.types import (
    CancelByCloid,
    CancelOrder,
    Cloid,
    Network,
    PlaceOrderRequest,
    TimeInForce,
    limit_order_type,
)

from .models import BenchmarkFailure, CanonicalOrder, OrderPair
from .preflight import Credentials, validate_roles
from .results import (
    parse_cancel_success,
    parse_ccxt_cancel_success,
    parse_ccxt_resting_oids,
    parse_resting_oids,
)


WireOrder = dict[str, object]


class LiveProvider(Protocol):
    name: str

    def wire_orders(self, pair: OrderPair) -> tuple[WireOrder, WireOrder]: ...

    async def place(self, pair: OrderPair) -> tuple[int, int]: ...

    async def cancel_oids(
        self, orders: Sequence[CanonicalOrder], oids: Sequence[int]
    ) -> None: ...

    async def cancel_cloids(self, orders: Sequence[CanonicalOrder]) -> None: ...

    async def close(self) -> None: ...


class MarketSource(Protocol):
    async def snapshot(self) -> tuple[float, int]: ...


class _AsyncInfo(Protocol):
    async def mid_price(self, coin: str) -> float: ...


class _AsyncClient(Protocol):
    async def place_orders(self, orders: object) -> object: ...

    async def cancel_orders(self, orders: object) -> object: ...

    async def cancel_orders_by_cloid(self, orders: object) -> object: ...

    async def close(self) -> None: ...


class _SdkClient(Protocol):
    def bulk_orders(self, orders: object) -> object: ...

    def bulk_cancel(self, orders: object) -> object: ...

    def bulk_cancel_by_cloid(self, orders: object) -> object: ...


class _CcxtClient(Protocol):
    def create_order_request(
        self,
        symbol: str,
        order_type: str,
        side: str,
        amount: str,
        price: str,
        params: dict[str, object],
    ) -> Mapping[str, object]: ...

    def create_orders(self, orders: object, params: dict[str, object]) -> object: ...

    def cancel_orders(
        self, ids: list[str], symbol: str, params: dict[str, object]
    ) -> object: ...

    def close(self) -> None: ...


class AsyncMarketSource:
    __slots__ = ("_coin", "_info", "_size_decimals")

    def __init__(self, info: _AsyncInfo, *, coin: str, size_decimals: int) -> None:
        self._info = info
        self._coin = coin
        self._size_decimals = size_decimals

    async def snapshot(self) -> tuple[float, int]:
        return (await self._info.mid_price(self._coin), self._size_decimals)


def _async_request(order: CanonicalOrder, coin: str) -> PlaceOrderRequest:
    return {
        "coin": coin,
        "is_buy": order.is_buy,
        "sz": order.size,
        "px": order.price,
        "is_market": False,
        "ro": order.reduce_only,
        "order_type": limit_order_type(TimeInForce.ALO),
        "cloid": Cloid(order.cloid),
    }


class AsyncHyperliquidProvider:
    name = "async-hyperliquid"

    __slots__ = ("_asset", "_client", "_coin", "_size_decimals")

    def __init__(
        self, client: _AsyncClient, *, coin: str, asset: int, size_decimals: int
    ) -> None:
        self._client = client
        self._coin = coin
        self._asset = asset
        self._size_decimals = size_decimals

    def _requests(self, pair: OrderPair) -> tuple[PlaceOrderRequest, PlaceOrderRequest]:
        return tuple(_async_request(order, self._coin) for order in pair.as_tuple())  # type: ignore[return-value]

    def wire_orders(self, pair: OrderPair) -> tuple[WireOrder, WireOrder]:
        encoded = tuple(
            cast(
                WireOrder,
                encode_order(
                    request,
                    asset=self._asset,
                    size_decimals=self._size_decimals,
                    is_spot=False,
                    is_outcome=False,
                ),
            )
            for request in self._requests(pair)
        )
        return cast(tuple[WireOrder, WireOrder], encoded)

    async def place(self, pair: OrderPair) -> tuple[int, int]:
        response = await self._client.place_orders(self._requests(pair))
        return parse_resting_oids(response, provider=self.name)

    async def cancel_oids(
        self, orders: Sequence[CanonicalOrder], oids: Sequence[int]
    ) -> None:
        if len(orders) != len(oids) or not orders:
            raise ValueError("orders and oids must have the same positive length")
        response = await self._client.cancel_orders(
            tuple(CancelOrder(self._coin, oid) for oid in oids)
        )
        parse_cancel_success(response, expected=len(oids), provider=self.name)

    async def cancel_cloids(self, orders: Sequence[CanonicalOrder]) -> None:
        if not orders:
            raise ValueError("orders must not be empty")
        response = await self._client.cancel_orders_by_cloid(
            tuple(CancelByCloid(self._coin, Cloid(order.cloid)) for order in orders)
        )
        parse_cancel_success(response, expected=len(orders), provider=self.name)

    async def close(self) -> None:
        await self._client.close()


def _sdk_requests(pair: OrderPair, coin: str) -> list[dict[str, object]]:
    from hyperliquid.utils.types import Cloid as SdkCloid

    return [
        {
            "coin": coin,
            "is_buy": order.is_buy,
            "sz": order.size,
            "limit_px": order.price,
            "order_type": {"limit": {"tif": "Alo"}},
            "reduce_only": order.reduce_only,
            "cloid": SdkCloid.from_str(order.cloid),
        }
        for order in pair.as_tuple()
    ]


class SdkProvider:
    name = "sdk"

    __slots__ = ("_asset", "_client", "_coin", "_size_decimals")

    def __init__(
        self, client: _SdkClient, *, coin: str, asset: int, size_decimals: int
    ) -> None:
        self._client = client
        self._coin = coin
        self._asset = asset
        self._size_decimals = size_decimals

    def wire_orders(self, pair: OrderPair) -> tuple[WireOrder, WireOrder]:
        from hyperliquid.utils.signing import order_request_to_order_wire

        encoded = tuple(
            cast(
                WireOrder, order_request_to_order_wire(cast(Any, request), self._asset)
            )
            for request in _sdk_requests(pair, self._coin)
        )
        return cast(tuple[WireOrder, WireOrder], encoded)

    async def place(self, pair: OrderPair) -> tuple[int, int]:
        response = self._client.bulk_orders(_sdk_requests(pair, self._coin))
        return parse_resting_oids(response, provider=self.name)

    async def cancel_oids(
        self, orders: Sequence[CanonicalOrder], oids: Sequence[int]
    ) -> None:
        if len(orders) != len(oids) or not orders:
            raise ValueError("orders and oids must have the same positive length")
        response = self._client.bulk_cancel(
            [{"coin": self._coin, "oid": oid} for oid in oids]
        )
        parse_cancel_success(response, expected=len(oids), provider=self.name)

    async def cancel_cloids(self, orders: Sequence[CanonicalOrder]) -> None:
        from hyperliquid.utils.types import Cloid as SdkCloid

        if not orders:
            raise ValueError("orders must not be empty")
        response = self._client.bulk_cancel_by_cloid(
            [
                {"coin": self._coin, "cloid": SdkCloid.from_str(order.cloid)}
                for order in orders
            ]
        )
        parse_cancel_success(response, expected=len(orders), provider=self.name)

    async def close(self) -> None:
        return None


def _ccxt_order(order: CanonicalOrder, *, symbol: str) -> dict[str, object]:
    return {
        "symbol": symbol,
        "type": "limit",
        "side": "buy" if order.is_buy else "sell",
        "amount": order.size,
        "price": order.price,
        "params": {"postOnly": True, "clientOrderId": order.cloid},
    }


class CcxtProvider:
    name = "ccxt"

    __slots__ = (
        "_asset",
        "_client",
        "_coin",
        "_size_decimals",
        "_symbol",
        "_vault_address",
    )

    def __init__(
        self,
        client: _CcxtClient,
        *,
        coin: str,
        symbol: str,
        asset: int,
        size_decimals: int,
        vault_address: str,
    ) -> None:
        self._client = client
        self._coin = coin
        self._symbol = symbol
        self._asset = asset
        self._size_decimals = size_decimals
        self._vault_address = vault_address

    def wire_orders(self, pair: OrderPair) -> tuple[WireOrder, WireOrder]:
        encoded = tuple(
            dict(
                self._client.create_order_request(
                    self._symbol,
                    "limit",
                    "buy" if order.is_buy else "sell",
                    _wire_float(order.size),
                    _wire_float(order.price),
                    {"postOnly": True, "clientOrderId": order.cloid},
                )
            )
            for order in pair.as_tuple()
        )
        return cast(tuple[WireOrder, WireOrder], encoded)

    async def place(self, pair: OrderPair) -> tuple[int, int]:
        response = self._client.create_orders(
            [_ccxt_order(order, symbol=self._symbol) for order in pair.as_tuple()],
            {"vaultAddress": self._vault_address},
        )
        return parse_ccxt_resting_oids(response)

    async def cancel_oids(
        self, orders: Sequence[CanonicalOrder], oids: Sequence[int]
    ) -> None:
        if len(orders) != len(oids) or not orders:
            raise ValueError("orders and oids must have the same positive length")
        response = self._client.cancel_orders(
            [str(oid) for oid in oids],
            self._symbol,
            {"vaultAddress": self._vault_address},
        )
        parse_ccxt_cancel_success(response, expected=len(oids))

    async def cancel_cloids(self, orders: Sequence[CanonicalOrder]) -> None:
        if not orders:
            raise ValueError("orders must not be empty")
        response = self._client.cancel_orders(
            ["0"] * len(orders),
            self._symbol,
            {
                "vaultAddress": self._vault_address,
                "clientOrderId": [order.cloid for order in orders],
            },
        )
        parse_ccxt_cancel_success(response, expected=len(orders))

    async def close(self) -> None:
        self._client.close()


def assert_wire_parity(
    provider_orders: Mapping[str, Sequence[Mapping[str, object]]],
) -> None:
    if not provider_orders:
        raise ValueError("provider_orders must not be empty")
    values = list(provider_orders.values())
    expected = tuple(dict(order) for order in values[0])
    if any(tuple(dict(order) for order in orders) != expected for orders in values[1:]):
        raise BenchmarkFailure("provider wire-order parity failed")


def validate_provider_wire_parity(
    providers: Sequence[LiveProvider], pair: OrderPair
) -> None:
    if not providers:
        raise ValueError("providers must not be empty")
    provider_orders = {
        provider.name: provider.wire_orders(pair) for provider in providers
    }
    if len(provider_orders) != len(providers):
        raise ValueError("provider names must be unique")
    assert_wire_parity(provider_orders)


@dataclass(slots=True)
class ProviderSet:
    measured: tuple[LiveProvider, ...]
    recovery: LiveProvider
    mid_source: MarketSource
    owned: tuple[LiveProvider, ...]

    async def close(self) -> None:
        failures: list[Exception] = []
        for provider in reversed(self.owned):
            try:
                await provider.close()
            except Exception as error:
                failures.append(error)
        if failures:
            raise ExceptionGroup("benchmark provider cleanup failed", failures)


def _ccxt_market(markets: Mapping[str, object], coin: str) -> Mapping[str, object]:
    candidates: list[Mapping[str, object]] = []
    for value in markets.values():
        if not isinstance(value, Mapping):
            continue
        market = cast(Mapping[str, object], value)
        if market.get("id") == coin and market.get("swap") is True:
            candidates.append(market)
    if len(candidates) != 1:
        raise BenchmarkFailure("ccxt did not resolve exactly one BTC perpetual market")
    return candidates[0]


async def build_providers(credentials: Credentials) -> ProviderSet:
    from eth_account import Account
    from hyperliquid.exchange import Exchange
    from hyperliquid.utils.constants import TESTNET_API_URL
    import ccxt

    owned: list[LiveProvider] = []
    try:
        async_client = AsyncHyperliquid(
            credentials.master_address,
            credentials.signing_key,
            vault_address=credentials.subaccount_address,
            network=Network.TESTNET,
        )
        await async_client.info.refresh_metadata()
        market = await async_client.info._market_info("BTC")
        api_role = await async_client.info.user_role(credentials.api_wallet_address)
        sub_role = await async_client.info.user_role(credentials.subaccount_address)
        validate_roles(credentials.master_address, api_role, sub_role)
        async_provider = AsyncHyperliquidProvider(
            cast(_AsyncClient, async_client),
            coin="BTC",
            asset=market.asset,
            size_decimals=market.size_decimals,
        )
        owned.append(async_provider)

        recovery_client = AsyncHyperliquid(
            credentials.master_address,
            credentials.signing_key,
            vault_address=credentials.subaccount_address,
            network=Network.TESTNET,
        )
        await recovery_client.info.refresh_metadata()
        recovery_provider = AsyncHyperliquidProvider(
            cast(_AsyncClient, recovery_client),
            coin="BTC",
            asset=market.asset,
            size_decimals=market.size_decimals,
        )
        owned.append(recovery_provider)

        sdk_client = Exchange(
            Account.from_key(credentials.signing_key),
            TESTNET_API_URL,
            vault_address=credentials.subaccount_address,
            account_address=credentials.master_address,
        )
        sdk_asset = sdk_client.info.name_to_asset("BTC")
        sdk_size_decimals = sdk_client.info.asset_to_sz_decimals[sdk_asset]
        if (sdk_asset, sdk_size_decimals) != (market.asset, market.size_decimals):
            raise BenchmarkFailure("sdk BTC market metadata does not match")
        sdk_provider = SdkProvider(
            cast(_SdkClient, sdk_client),
            coin="BTC",
            asset=sdk_asset,
            size_decimals=sdk_size_decimals,
        )
        owned.append(sdk_provider)

        ccxt_client = ccxt.hyperliquid(
            {
                "walletAddress": credentials.api_wallet_address,
                "privateKey": credentials.signing_key,
                "enableRateLimit": False,
            }
        )
        ccxt_client.set_sandbox_mode(True)
        markets = cast(Mapping[str, object], ccxt_client.load_markets())
        ccxt_market = _ccxt_market(markets, "BTC")
        symbol = ccxt_market.get("symbol")
        base_id = ccxt_market.get("baseId")
        if not isinstance(symbol, str) or not isinstance(base_id, str | int):
            raise BenchmarkFailure("ccxt BTC market metadata is incomplete")
        if int(base_id) != market.asset:
            raise BenchmarkFailure("ccxt BTC market metadata does not match")

        ccxt_runtime = cast(Any, ccxt_client)
        ccxt_options = cast(dict[str, object], ccxt_runtime.options)
        ccxt_options["approvedBuilderFee"] = False
        ccxt_options["builderFee"] = False
        ccxt_options["refSet"] = True
        ccxt_options["enableUnifiedMargin"] = False
        setattr(ccxt_runtime, "initialize_client", lambda: True)
        ccxt_provider = CcxtProvider(
            cast(_CcxtClient, ccxt_runtime),
            coin="BTC",
            symbol=symbol,
            asset=market.asset,
            size_decimals=market.size_decimals,
            vault_address=credentials.subaccount_address,
        )
        owned.append(ccxt_provider)

        return ProviderSet(
            measured=(ccxt_provider, sdk_provider, async_provider),
            recovery=recovery_provider,
            mid_source=AsyncMarketSource(
                cast(_AsyncInfo, async_client.info),
                coin="BTC",
                size_decimals=market.size_decimals,
            ),
            owned=tuple(owned),
        )
    except BaseException:
        for provider in reversed(owned):
            try:
                await provider.close()
            except Exception:
                pass
        raise
