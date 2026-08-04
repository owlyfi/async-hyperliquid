from __future__ import annotations

import math
from collections.abc import Sequence
from types import TracebackType
from typing import TYPE_CHECKING, Literal, Self

from aiohttp import ClientSession, ClientTimeout

from ._encoding import _round_float, _wire_float, encode_order
from ._http import _HttpTransport
from ._metadata import _MarketInfo
from .errors import ProtocolError
from .info import InfoClient
from .types import (
    Builder,
    CancelByCloid,
    CancelOrder,
    CancelOrderResponse,
    CancelTwapResponse,
    Cloid,
    DefaultActionResponse,
    ModifyOrderRequest,
    Network,
    OrderGrouping,
    OrderType,
    PlaceOrderRequest,
    PlaceOrderResponse,
    PlaceTwapResponse,
    TimeInForce,
    limit_order_type,
)
from .types.exchange import (
    EncodedCancel,
    EncodedCancelByCloid,
    EncodedModify,
    EncodedOrder,
    EncodedTwapOrder,
)

if TYPE_CHECKING:
    from .exchange import ExchangeClient


def _coin_dex(coin: str) -> str:
    return coin.partition(":")[0] if ":" in coin else ""


class AsyncHyperliquid:
    """Resource owner plus intent-level order workflows."""

    __slots__ = ("_dexs", "_exchange", "_execution_address", "_info", "_transport")

    _transport: _HttpTransport
    _info: InfoClient
    _exchange: ExchangeClient
    _execution_address: str
    _dexs: tuple[str, ...]

    def __init__(
        self,
        account_address: str,
        signing_key: str,
        *,
        vault_address: str | None = None,
        network: Network = Network.MAINNET,
        info_url: str | None = None,
        exchange_url: str | None = None,
        session: ClientSession | None = None,
        timeout: ClientTimeout | None = None,
        dexs: tuple[str, ...] = ("",),
    ) -> None:
        from eth_account import Account

        try:
            account = Account.from_key(signing_key)
        except (TypeError, ValueError):
            raise ValueError("signing_key must be a 32-byte hex private key") from None

        from .exchange import ExchangeClient

        transport = _HttpTransport(session=session, timeout=timeout)
        self._transport = transport
        self._info = InfoClient._from_transport(
            transport, info_url=network.info_url if info_url is None else info_url
        )
        self._exchange = ExchangeClient(
            transport,
            account,
            account_address=account_address,
            vault_address=vault_address,
            network=network,
            exchange_url=exchange_url,
        )
        self._execution_address = self._exchange.execution_address
        self._dexs = tuple(dict.fromkeys(dexs))

    @property
    def info(self) -> InfoClient:
        return self._info

    @property
    def exchange(self) -> ExchangeClient:
        return self._exchange

    async def _encode_orders(
        self, orders: Sequence[PlaceOrderRequest]
    ) -> tuple[EncodedOrder, ...]:
        markets = await self._info._market_infos(
            tuple(order["coin"] for order in orders)
        )
        return tuple(
            encode_order(
                order,
                asset=market.asset,
                size_decimals=market.size_decimals,
                is_spot=market.is_spot,
            )
            for order, market in zip(orders, markets, strict=True)
        )

    async def _encode_market_orders(
        self, orders: Sequence[PlaceOrderRequest]
    ) -> tuple[EncodedOrder, ...]:
        markets = await self._info._market_infos(
            tuple(order["coin"] for order in orders)
        )
        mids = await self._info._mid_prices(markets)
        limits: list[PlaceOrderRequest] = []
        for order, mid in zip(orders, mids, strict=True):
            slippage = order.get("slippage", 0.05)
            if not math.isfinite(slippage) or not 0 <= slippage < 1:
                raise ValueError("slippage must be finite and in [0, 1)")
            limit: PlaceOrderRequest = {
                "coin": order["coin"],
                "is_buy": order["is_buy"],
                "sz": order["sz"],
                "px": mid * (1 + slippage if order["is_buy"] else 1 - slippage),
                "is_market": False,
                "ro": order.get("ro", False),
                "order_type": limit_order_type(TimeInForce.IOC),
            }
            cloid = order.get("cloid")
            if cloid is not None:
                limit["cloid"] = cloid
            limits.append(limit)
        return tuple(
            encode_order(
                order,
                asset=market.asset,
                size_decimals=market.size_decimals,
                is_spot=market.is_spot,
            )
            for order, market in zip(limits, markets, strict=True)
        )

    async def place_order(
        self,
        coin: str,
        is_buy: bool,
        sz: float,
        px: float,
        is_market: bool = True,
        *,
        ro: bool = False,
        order_type: OrderType | None = None,
        cloid: Cloid | None = None,
        slippage: float = 0.05,
        builder: Builder | None = None,
        expires_after: int | None = None,
    ) -> PlaceOrderResponse:
        order: PlaceOrderRequest = {
            "coin": coin,
            "is_buy": is_buy,
            "sz": sz,
            "px": px,
            "is_market": is_market,
            "ro": ro,
            "order_type": order_type,
            "cloid": cloid,
            "slippage": slippage,
        }
        if is_market:
            return await self.place_market_orders(
                (order,), builder=builder, expires_after=expires_after
            )
        return await self.place_orders(
            (order,), builder=builder, expires_after=expires_after
        )

    async def place_limit_order(
        self,
        order: PlaceOrderRequest,
        *,
        builder: Builder | None = None,
        expires_after: int | None = None,
    ) -> PlaceOrderResponse:
        if order["is_market"]:
            raise ValueError("place_limit_order requires is_market=False")
        order_type = order.get("order_type")
        if order_type is not None and "limit" not in order_type:
            raise ValueError("place_limit_order requires a limit order_type")
        return await self.place_orders(
            (order,), builder=builder, expires_after=expires_after
        )

    async def place_trigger_order(
        self,
        order: PlaceOrderRequest,
        *,
        builder: Builder | None = None,
        expires_after: int | None = None,
    ) -> PlaceOrderResponse:
        if order["is_market"]:
            raise ValueError("place_trigger_order requires is_market=False")
        order_type = order.get("order_type")
        if order_type is None or "trigger" not in order_type:
            raise ValueError("place_trigger_order requires a trigger order_type")
        return await self.place_orders(
            (order,), builder=builder, expires_after=expires_after
        )

    async def place_orders(
        self,
        orders: Sequence[PlaceOrderRequest],
        *,
        grouping: OrderGrouping = OrderGrouping.NA,
        builder: Builder | None = None,
        expires_after: int | None = None,
    ) -> PlaceOrderResponse:
        commands = tuple(orders)
        if not commands:
            raise ValueError("orders must not be empty")
        market_flags = {order["is_market"] for order in commands}
        if len(market_flags) != 1:
            raise ValueError("orders must use the same is_market value")
        if market_flags == {True}:
            return await self.place_market_orders(
                commands,
                grouping=grouping,
                builder=builder,
                expires_after=expires_after,
            )
        encoded = await self._encode_orders(commands)
        return await self._exchange._submit_orders(
            encoded, grouping=grouping, builder=builder, expires_after=expires_after
        )

    batch_place_orders = place_orders

    async def place_market_order(
        self,
        order: PlaceOrderRequest,
        *,
        builder: Builder | None = None,
        expires_after: int | None = None,
    ) -> PlaceOrderResponse:
        if not order["is_market"]:
            raise ValueError("place_market_order requires is_market=True")
        return await self.place_market_orders(
            (order,), builder=builder, expires_after=expires_after
        )

    async def place_market_orders(
        self,
        orders: Sequence[PlaceOrderRequest],
        *,
        grouping: OrderGrouping = OrderGrouping.NA,
        builder: Builder | None = None,
        expires_after: int | None = None,
    ) -> PlaceOrderResponse:
        commands = tuple(orders)
        if not commands:
            raise ValueError("orders must not be empty")
        if any(not order["is_market"] for order in commands):
            raise ValueError("place_market_orders requires is_market=True")
        encoded = await self._encode_market_orders(commands)
        return await self._exchange._submit_orders(
            encoded, grouping=grouping, builder=builder, expires_after=expires_after
        )

    async def cancel_order(
        self, order: CancelOrder, *, expires_after: int | None = None
    ) -> CancelOrderResponse:
        return await self.cancel_orders((order,), expires_after=expires_after)

    async def cancel_orders(
        self, orders: Sequence[CancelOrder], *, expires_after: int | None = None
    ) -> CancelOrderResponse:
        commands = tuple(orders)
        if not commands:
            raise ValueError("orders must not be empty")
        markets = await self._info._market_infos(
            tuple(order.coin for order in commands)
        )
        cancels = tuple(
            EncodedCancel(a=market.asset, o=order.oid)
            for order, market in zip(commands, markets, strict=True)
        )
        return await self._exchange._submit_cancels(
            cancels, expires_after=expires_after
        )

    async def cancel_by_cloid(
        self, order: CancelByCloid, *, expires_after: int | None = None
    ) -> CancelOrderResponse:
        return await self.cancel_orders_by_cloid((order,), expires_after=expires_after)

    async def cancel_orders_by_cloid(
        self, orders: Sequence[CancelByCloid], *, expires_after: int | None = None
    ) -> CancelOrderResponse:
        commands = tuple(orders)
        if not commands:
            raise ValueError("orders must not be empty")
        markets = await self._info._market_infos(
            tuple(order.coin for order in commands)
        )
        cancels = tuple(
            EncodedCancelByCloid(asset=market.asset, cloid=str(order.cloid))
            for order, market in zip(commands, markets, strict=True)
        )
        return await self._exchange._submit_cloid_cancels(
            cancels, expires_after=expires_after
        )

    @staticmethod
    def _encode_modify(order: ModifyOrderRequest, market: _MarketInfo) -> EncodedModify:
        oid = order["oid"]
        return EncodedModify(
            oid=oid if isinstance(oid, int) else str(oid),
            order=encode_order(
                order,
                asset=market.asset,
                size_decimals=market.size_decimals,
                is_spot=market.is_spot,
            ),
        )

    async def modify_order(
        self, order: ModifyOrderRequest, *, expires_after: int | None = None
    ) -> PlaceOrderResponse:
        oid = order["oid"]
        if isinstance(oid, int) and oid < 0:
            raise ValueError("oid must not be negative")
        market = await self._info._market_info(order["coin"])
        return await self._exchange._submit_modify(
            self._encode_modify(order, market), expires_after=expires_after
        )

    async def modify_orders(
        self, orders: Sequence[ModifyOrderRequest], *, expires_after: int | None = None
    ) -> PlaceOrderResponse:
        commands = tuple(orders)
        if not commands:
            raise ValueError("orders must not be empty")
        if any(
            isinstance(command["oid"], int) and command["oid"] < 0
            for command in commands
        ):
            raise ValueError("oid must not be negative")
        markets = await self._info._market_infos(
            tuple(command["coin"] for command in commands)
        )
        modifies = tuple(
            self._encode_modify(command, market)
            for command, market in zip(commands, markets, strict=True)
        )
        return await self._exchange._submit_modifies(
            modifies, expires_after=expires_after
        )

    async def update_leverage(
        self,
        coin: str,
        leverage: int,
        *,
        is_cross: bool = True,
        expires_after: int | None = None,
    ) -> DefaultActionResponse:
        if leverage <= 0:
            raise ValueError("leverage must be greater than zero")
        asset = await self._info.asset_id(coin)
        return await self._exchange._update_leverage(
            asset, leverage, is_cross=is_cross, expires_after=expires_after
        )

    async def update_isolated_margin(
        self, coin: str, amount: float, *, expires_after: int | None = None
    ) -> DefaultActionResponse:
        asset = await self._info.asset_id(coin)
        return await self._exchange._update_isolated_margin(
            asset, amount, expires_after=expires_after
        )

    async def place_twap(
        self,
        coin: str,
        is_buy: bool,
        size: float,
        minutes: int,
        *,
        reduce_only: bool = False,
        randomize: bool = False,
        expires_after: int | None = None,
    ) -> PlaceTwapResponse:
        if minutes <= 0:
            raise ValueError("minutes must be greater than zero")
        if not math.isfinite(size) or size <= 0:
            raise ValueError("size must be finite and greater than zero")
        market = await self._info._market_info(coin)
        rounded_size = _round_float(size, market.size_decimals)
        if rounded_size == 0:
            raise ValueError("size is below market precision")
        twap = EncodedTwapOrder(
            a=market.asset,
            b=is_buy,
            s=_wire_float(rounded_size),
            r=reduce_only,
            m=minutes,
            t=randomize,
        )
        return await self._exchange._submit_twap(twap, expires_after=expires_after)

    async def cancel_twap(
        self, coin: str, twap_id: int, *, expires_after: int | None = None
    ) -> CancelTwapResponse:
        if twap_id < 0:
            raise ValueError("twap_id must not be negative")
        asset = await self._info.asset_id(coin)
        return await self._exchange._submit_twap_cancel(
            asset, twap_id, expires_after=expires_after
        )

    async def spot_transfer(
        self, coin: str, amount: float, destination: str
    ) -> DefaultActionResponse:
        token = await self._info.spot_token_metadata(coin)
        return await self._exchange._spot_transfer(
            f"{token['name']}:{token['tokenId']}",
            token["weiDecimals"],
            amount,
            destination,
        )

    async def send_asset(
        self,
        coin: str,
        amount: float,
        destination: str,
        *,
        source_dex: str,
        destination_dex: str,
    ) -> DefaultActionResponse:
        token = await self._info.spot_token_metadata(coin)
        return await self._exchange._send_asset(
            f"{token['name']}:{token['tokenId']}",
            token["weiDecimals"],
            amount,
            destination,
            source_dex=source_dex,
            destination_dex=destination_dex,
        )

    async def agent_send_asset(
        self,
        coin: str,
        amount: float,
        destination: str,
        *,
        source_dex: str,
        destination_dex: str,
        expires_after: int | None = None,
    ) -> DefaultActionResponse:
        token = await self._info.spot_token_metadata(coin)
        return await self._exchange._agent_send_asset(
            f"{token['name']}:{token['tokenId']}",
            token["weiDecimals"],
            amount,
            destination,
            source_dex=source_dex,
            destination_dex=destination_dex,
            expires_after=expires_after,
        )

    async def send_to_evm_with_data(
        self,
        coin: str,
        amount: float,
        destination_recipient: str,
        *,
        source_dex: str,
        address_encoding: Literal["hex", "base58"],
        destination_chain_id: int,
        gas_limit: int,
        data: str,
    ) -> DefaultActionResponse:
        if destination_chain_id < 0:
            raise ValueError("destination_chain_id must not be negative")
        if gas_limit < 0:
            raise ValueError("gas_limit must not be negative")
        if not data.startswith(("0x", "0X")):
            raise ValueError("data must be a hex string")
        try:
            bytes.fromhex(data[2:])
        except ValueError:
            raise ValueError("data must be a hex string") from None

        token = await self._info.spot_token_metadata(coin)
        return await self._exchange._send_to_evm_with_data(
            f"{token['name']}:{token['tokenId']}",
            token["weiDecimals"],
            amount,
            destination_recipient,
            source_dex=source_dex,
            address_encoding=address_encoding,
            destination_chain_id=destination_chain_id,
            gas_limit=gas_limit,
            data=data,
        )

    async def close_position(
        self,
        coin: str,
        *,
        builder: Builder | None = None,
        expires_after: int | None = None,
    ) -> PlaceOrderResponse | None:
        return await self.close_positions(
            (coin,), builder=builder, expires_after=expires_after
        )

    async def close_positions(
        self,
        coins: Sequence[str] | None = None,
        *,
        dexs: tuple[str, ...] | None = None,
        builder: Builder | None = None,
        expires_after: int | None = None,
    ) -> PlaceOrderResponse | None:
        requested = None if coins is None else tuple(dict.fromkeys(coins))
        if requested == ():
            return None
        query_dexs = (
            tuple(dict.fromkeys(_coin_dex(coin) for coin in requested))
            if dexs is None and requested is not None
            else self._dexs
            if dexs is None
            else tuple(dict.fromkeys(dexs))
        )
        positions = await self._info.positions(self._execution_address, dexs=query_dexs)

        position_sizes: dict[str, float] = {}
        position_order: list[str] = []
        for position in positions:
            coin = position.get("coin")
            raw_size = position.get("szi")
            if not isinstance(coin, str) or not isinstance(raw_size, str):
                raise ProtocolError("position contains malformed coin or size")
            try:
                size = float(raw_size)
            except ValueError:
                raise ProtocolError("position contains an invalid size") from None
            if not math.isfinite(size):
                raise ProtocolError("position contains an invalid size")
            if coin not in position_sizes:
                position_order.append(coin)
            position_sizes[coin] = size

        selected_coins = position_order if requested is None else requested
        orders: list[PlaceOrderRequest] = []
        for coin in selected_coins:
            size = position_sizes.get(coin, 0.0)
            if not size:
                continue
            orders.append(
                {
                    "coin": coin,
                    "is_buy": size < 0,
                    "sz": abs(size),
                    "px": 0.0,
                    "is_market": True,
                    "ro": True,
                }
            )
        if not orders:
            return None
        return await self.place_market_orders(
            tuple(orders), builder=builder, expires_after=expires_after
        )

    async def close_all_positions(
        self,
        *,
        dexs: tuple[str, ...] | None = None,
        builder: Builder | None = None,
        expires_after: int | None = None,
    ) -> PlaceOrderResponse | None:
        return await self.close_positions(
            None, dexs=dexs, builder=builder, expires_after=expires_after
        )

    async def open(self) -> None:
        await self._transport.open()

    async def close(self) -> None:
        await self._transport.close()

    async def __aenter__(self) -> Self:
        await self.open()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.close()
