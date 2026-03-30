import math
import asyncio

from async_hyperliquid.utils.miscs import round_px, round_float, get_coin_dex
from async_hyperliquid.utils.types import (
    Cloid,
    LimitTif,
    OrderType,
    GroupOptions,
    OrderBuilder,
    PlaceOrderRequest,
    BatchCancelRequest,
    BatchPlaceOrderRequest,
    limit_order_type,
)
from async_hyperliquid.utils.signing import encode_order, orders_to_action
from async_hyperliquid.utils.constants import USD_FACTOR, SPOT_OFFSET, PERP_DEX_OFFSET

from .info import AsyncHyperliquidInfoClient


class AsyncHyperliquidOrdersClient(AsyncHyperliquidInfoClient):
    def _round_sz_px_cached(
        self, coin: str, sz: float, px: float
    ) -> tuple[int, float, float | int] | None:
        asset = self._lookup_cached_asset_id(coin)
        if asset is None:
            return None

        sz_decimals = self.asset_sz_decimals.get(asset)
        if sz_decimals is None:
            return None

        is_spot = SPOT_OFFSET <= asset < PERP_DEX_OFFSET
        px_decimals = (6 if not is_spot else 8) - sz_decimals
        return asset, round_float(sz, sz_decimals), round_px(px, px_decimals)

    async def _round_sz_px(self, coin: str, sz: float, px: float):
        cached = self._round_sz_px_cached(coin, sz, px)
        if cached is not None:
            return cached

        coin_name = await self.get_coin_name(coin)
        asset = self.coin_assets.get(coin_name)
        if asset is None:
            raise ValueError(f"Coin {coin}({coin_name}) not found")

        sz_decimals = self.asset_sz_decimals[asset]
        is_spot = SPOT_OFFSET <= asset < PERP_DEX_OFFSET
        px_decimals = (6 if not is_spot else 8) - sz_decimals
        return asset, round_float(sz, sz_decimals), round_px(px, px_decimals)

    async def place_market_order(
        self,
        coin: str,
        is_buy: bool,
        sz: float,
        *,
        ro: bool = False,
        cloid: Cloid | None = None,
        slippage: float = 0.05,
        builder: OrderBuilder | None = None,
    ):
        mid_px = await self.get_mid_price(coin)
        slippage_factor = (1 + slippage) if is_buy else (1 - slippage)
        px = mid_px * slippage_factor
        return await self.place_typed_order(
            coin=coin,
            is_buy=is_buy,
            sz=sz,
            px=px,
            ro=ro,
            order_type=limit_order_type(LimitTif.IOC),
            cloid=cloid,
            builder=builder,
        )

    async def place_typed_order(
        self,
        coin: str,
        is_buy: bool,
        sz: float,
        px: float,
        *,
        ro: bool = False,
        order_type: OrderType | None = None,
        cloid: Cloid | None = None,
        builder: OrderBuilder | None = None,
    ):
        if order_type is None:
            order_type = limit_order_type(LimitTif.IOC)

        asset, sz, px = await self._round_sz_px(coin, sz, px)

        order_req: PlaceOrderRequest = {
            "asset": asset,
            "is_buy": is_buy,
            "sz": sz,
            "px": px,
            "ro": ro,
            "order_type": order_type,
            "cloid": cloid,
        }

        return await self.place_orders([order_req], builder=builder)

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
        builder: OrderBuilder | None = None,
    ):
        if is_market:
            return await self.place_market_order(
                coin=coin,
                is_buy=is_buy,
                sz=sz,
                ro=ro,
                cloid=cloid,
                slippage=slippage,
                builder=builder,
            )

        return await self.place_typed_order(
            coin=coin,
            is_buy=is_buy,
            sz=sz,
            px=px,
            ro=ro,
            order_type=order_type,
            cloid=cloid,
            builder=builder,
        )

    async def place_orders(
        self,
        orders: list[PlaceOrderRequest],
        grouping: GroupOptions = "na",
        builder: OrderBuilder | None = None,
    ):
        encoded_orders = [encode_order(o) for o in orders]

        if builder:
            builder["b"] = builder["b"].lower()

        action = orders_to_action(encoded_orders, grouping, builder)

        return await self.exchange.post_action(
            action, vault=self.vault, expires=self.expires
        )

    async def batch_place_orders(
        self,
        orders: BatchPlaceOrderRequest,
        *,
        grouping: GroupOptions = "na",
        is_market: bool = False,
        slippage: float = 0.05,
        builder: OrderBuilder | None = None,
    ):
        if is_market:
            reqs = await self._get_batch_market_orders(orders, slippage)
        else:
            reqs = await self._get_batch_limit_orders(orders)

        return await self.place_orders(reqs, grouping=grouping, builder=builder)

    async def _get_batch_limit_orders(self, orders: BatchPlaceOrderRequest):
        rounded_orders = [
            self._round_sz_px_cached(o["coin"], o["sz"], o["px"]) for o in orders
        ]
        if all(rounded_order is not None for rounded_order in rounded_orders):
            return [
                {**order, "asset": asset, "sz": sz, "px": px}
                for order, (asset, sz, px) in zip(orders, rounded_orders, strict=True)
            ]

        rounded_orders = await asyncio.gather(
            *(self._round_sz_px(o["coin"], o["sz"], o["px"]) for o in orders)
        )
        return [
            {**order, "asset": asset, "sz": sz, "px": px}
            for order, (asset, sz, px) in zip(orders, rounded_orders, strict=True)
        ]

    async def _get_batch_market_orders(
        self, orders: BatchPlaceOrderRequest, slippage: float = 0.05
    ):
        dexs = list(set(get_coin_dex(o["coin"]) for o in orders))
        all_mids = await self.get_dexs_mids(dexs)
        order_type = limit_order_type(LimitTif.IOC)
        quoted_prices = []
        for order in orders:
            market_price = all_mids[order["coin"]]
            slippage_factor = (1 + slippage) if order["is_buy"] else (1 - slippage)
            quoted_prices.append(market_price * slippage_factor)

        rounded_orders = [
            self._round_sz_px_cached(order["coin"], order["sz"], quoted_price)
            for order, quoted_price in zip(orders, quoted_prices, strict=True)
        ]
        if all(rounded_order is not None for rounded_order in rounded_orders):
            return [
                {**order, "asset": asset, "sz": sz, "px": px, "order_type": order_type}
                for order, (asset, sz, px) in zip(orders, rounded_orders, strict=True)
            ]

        rounded_orders = await asyncio.gather(
            *(
                self._round_sz_px(order["coin"], order["sz"], quoted_price)
                for order, quoted_price in zip(orders, quoted_prices, strict=True)
            )
        )
        return [
            {**order, "asset": asset, "sz": sz, "px": px, "order_type": order_type}
            for order, (asset, sz, px) in zip(orders, rounded_orders, strict=True)
        ]

    async def cancel_order(self, coin: str, oid: int):
        return await self.cancel_orders([(coin, int(oid))])

    async def batch_cancel_orders(self, cancels: BatchCancelRequest):
        return await self.cancel_orders(cancels)

    async def cancel_orders(self, cancels: BatchCancelRequest):
        assets = [
            asset
            for coin, _ in cancels
            if (asset := self._lookup_cached_asset_id(coin)) is not None
        ]
        if len(assets) != len(cancels):
            assets = await asyncio.gather(
                *(self.get_coin_asset(coin) for coin, _ in cancels)
            )
        action = {
            "type": "cancel",
            "cancels": [
                {"a": asset, "o": oid}
                for asset, (_, oid) in zip(assets, cancels, strict=True)
            ],
        }

        return await self.exchange.post_action(
            action, vault=self.vault, expires=self.expires
        )

    async def cancel_by_cloid(self, coin: str, cloid: Cloid):
        return await self.batch_cancel_by_cloid([(coin, cloid)])

    async def batch_cancel_by_cloid(self, cancels: list[tuple[str, Cloid]]):
        assets = [
            asset
            for coin, _ in cancels
            if (asset := self._lookup_cached_asset_id(coin)) is not None
        ]
        if len(assets) != len(cancels):
            assets = await asyncio.gather(
                *(self.get_coin_asset(coin) for coin, _ in cancels)
            )
        action = {
            "type": "cancelByCloid",
            "cancels": [
                {"asset": asset, "cloid": cloid.to_raw()}
                for asset, (_, cloid) in zip(assets, cancels, strict=True)
            ],
        }

        return await self.exchange.post_action(
            action, vault=self.vault, expires=self.expires
        )

    async def schedule_cancel(self, time: int | None = None):
        action = {"type": "scheduleCancel", "time": time}
        return await self.exchange.post_action(
            action, vault=self.vault, expires=self.expires
        )

    async def modify_order(
        self,
        oid: int | Cloid,
        coin: str,
        is_buy: bool,
        sz: float,
        px: float,
        ro: bool,
        order_type: OrderType,
        cloid: Cloid | None = None,
    ):
        asset, sz, px = await self._round_sz_px(coin, sz, px)
        modify = {
            "oid": oid,
            "order": {
                "asset": asset,
                "is_buy": is_buy,
                "sz": sz,
                "px": px,
                "ro": ro,
                "order_type": order_type,
                "cloid": cloid,
            },
        }
        return await self.batch_modify_orders([modify])

    async def batch_modify_orders(self, modify_req: list[dict]):
        modifies = [
            {
                "oid": m["oid"].to_raw() if isinstance(m["oid"], Cloid) else m["oid"],
                "order": encode_order(m["order"]),
            }
            for m in modify_req
        ]
        action = {"type": "batchModify", "modifies": modifies}
        return await self.exchange.post_action(
            action, vault=self.vault, expires=self.expires
        )

    async def update_leverage(self, leverage: int, coin: str, is_cross: bool = True):
        action = {
            "type": "updateLeverage",
            "asset": await self.get_coin_asset(coin),
            "isCross": is_cross,
            "leverage": leverage,
        }

        return await self.exchange.post_action(
            action, vault=self.vault, expires=self.expires
        )

    async def update_isolated_margin(self, usd: float, coin: str):
        usd_in_units = usd * USD_FACTOR
        if abs(round(usd_in_units) - usd_in_units) >= 1e-3:
            raise ValueError(
                f"USD amount precision error: Value {usd} cannot be accurately"
            )
        amount = math.floor(usd_in_units)
        action = {
            "type": "updateIsolatedMargin",
            "asset": await self.get_coin_asset(coin),
            "isBuy": True,
            "ntli": amount,
        }

        return await self.exchange.post_action(
            action, vault=self.vault, expires=self.expires
        )

    async def place_twap(
        self,
        coin: str,
        is_buy: bool,
        sz: float,
        minutes: int,
        ro: bool = False,
        randomize: bool = False,
    ):
        asset, sz, _ = await self._round_sz_px(coin, sz, 0)
        sz_str = str(sz).rstrip("0").rstrip(".")
        action = {
            "type": "twapOrder",
            "twap": {
                "a": asset,
                "b": is_buy,
                "s": sz_str,
                "r": ro,
                "m": minutes,
                "t": randomize,
            },
        }
        return await self.exchange.post_action(
            action, vault=self.vault, expires=self.expires
        )

    async def cancel_twap(self, coin: str, twap_id: int):
        action = {
            "type": "twapCancel",
            "a": await self.get_coin_asset(coin),
            "t": twap_id,
        }
        return await self.exchange.post_action(action)

    async def close_all_positions(
        self, dexs: list[str] | None = None, *, builder: OrderBuilder | None = None
    ):
        positions = await self.get_all_positions(dexs=dexs)
        if not positions:
            return None
        orders = []
        for p in positions:
            coin = p["coin"]
            szi = float(p["szi"])
            order = {
                "coin": coin,
                "is_buy": szi < 0,
                "sz": abs(szi),
                "px": 0,
                "ro": True,
            }
            orders.append(order)

        return await self.batch_place_orders(orders, is_market=True, builder=builder)

    async def close_dex_positions(
        self, dex: str, *, builder: OrderBuilder | None = None
    ):
        return await self.close_all_positions(dexs=[dex], builder=builder)

    async def close_positions(
        self, coins: list[str], *, builder: OrderBuilder | None = None
    ):
        if not coins:
            return None

        positions = await self.get_all_positions(
            dexs=sorted({get_coin_dex(coin) for coin in coins})
        )
        targets = {coin: None for coin in coins}
        for position in positions:
            coin = position["coin"]
            if coin in targets:
                targets[coin] = position

        orders = []
        for coin in coins:
            target = targets[coin]
            if target is None:
                continue
            size = float(target["szi"])
            orders.append(
                {"coin": coin, "is_buy": size < 0, "sz": abs(size), "px": 0, "ro": True}
            )

        if not orders:
            return None

        return await self.batch_place_orders(orders, is_market=True, builder=builder)

    async def close_position(self, coin: str, *, builder: OrderBuilder | None = None):
        return await self.close_positions([coin], builder=builder)
