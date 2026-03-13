import math

from async_hyperliquid.utils.constants import (
    PERP_DEX_OFFSET,
    SPOT_OFFSET,
    USD_FACTOR,
)
from async_hyperliquid.utils.miscs import get_coin_dex, round_float, round_px
from async_hyperliquid.utils.signing import encode_order, orders_to_action
from async_hyperliquid.utils.types import (
    BatchCancelRequest,
    BatchPlaceOrderRequest,
    Cloid,
    GroupOptions,
    LimitTif,
    OrderBuilder,
    OrderType,
    PlaceOrderRequest,
    limit_order_type,
)

from .info import AsyncHyperliquidInfoClient


class AsyncHyperliquidOrdersClient(AsyncHyperliquidInfoClient):
    async def _round_sz_px(self, coin: str, sz: float, px: float):
        asset = await self.get_coin_asset(coin)
        is_spot = asset >= SPOT_OFFSET and asset < PERP_DEX_OFFSET
        sz_decimals = await self.get_coin_sz_decimals(coin)
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
        reqs = []
        if is_market:
            reqs = await self._get_batch_market_orders(orders, slippage)
        else:
            for o in orders:
                asset, sz, px = await self._round_sz_px(
                    o["coin"], o["sz"], o["px"]
                )
                req = {**o, "asset": asset, "sz": sz, "px": px}
                reqs.append(req)

        return await self.place_orders(reqs, grouping=grouping, builder=builder)

    async def _get_batch_market_orders(
        self, orders: BatchPlaceOrderRequest, slippage: float = 0.05
    ):
        reqs = []
        dexs = list(set(get_coin_dex(o["coin"]) for o in orders))
        all_mids = await self.get_dexs_mids(dexs)
        order_type = limit_order_type(LimitTif.IOC)
        for o in orders:
            coin = o["coin"]
            market_price = all_mids[coin]
            slippage_factor = (1 + slippage) if o["is_buy"] else (1 - slippage)
            px = market_price * slippage_factor
            asset, sz, px = await self._round_sz_px(coin, o["sz"], px)
            req = {
                **o,
                "asset": asset,
                "sz": sz,
                "px": px,
                "order_type": order_type,
            }
            reqs.append(req)
        return reqs

    async def cancel_order(self, coin: str, oid: int):
        return await self.cancel_orders([(coin, int(oid))])

    async def batch_cancel_orders(self, cancels: BatchCancelRequest):
        return await self.cancel_orders(cancels)

    async def cancel_orders(self, cancels: BatchCancelRequest):
        action = {
            "type": "cancel",
            "cancels": [
                {"a": await self.get_coin_asset(coin), "o": oid}
                for coin, oid in cancels
            ],
        }

        return await self.exchange.post_action(
            action, vault=self.vault, expires=self.expires
        )

    async def cancel_by_cloid(self, coin: str, cloid: Cloid):
        return await self.batch_cancel_by_cloid([(coin, cloid)])

    async def batch_cancel_by_cloid(self, cancels: list[tuple[str, Cloid]]):
        action = {
            "type": "cancelByCloid",
            "cancels": [
                {
                    "asset": await self.get_coin_asset(coin),
                    "cloid": cloid.to_raw(),
                }
                for coin, cloid in cancels
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
                "oid": m["oid"].to_raw()
                if isinstance(m["oid"], Cloid)
                else m["oid"],
                "order": encode_order(m["order"]),
            }
            for m in modify_req
        ]
        action = {"type": "batchModify", "modifies": modifies}
        return await self.exchange.post_action(
            action, vault=self.vault, expires=self.expires
        )

    async def update_leverage(
        self, leverage: int, coin: str, is_cross: bool = True
    ):
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

    async def close_all_positions(self, dexs: list[str] | None = None):
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

        return await self.batch_place_orders(orders, is_market=True)

    async def close_dex_positions(self, dex: str):
        return await self.close_all_positions(dexs=[dex])

    async def close_position(self, coin: str):
        dex = get_coin_dex(coin)
        positions = await self.get_dex_positions(dex=dex)
        target = {}
        for position in positions:
            if coin == position["coin"]:
                target = position

        if not target:
            return None

        size = float(target["szi"])
        price = await self.get_mid_price(coin)
        if not price:
            raise ValueError(f"Failed to retrieve market price for {coin}")

        close_order = {
            "coin": coin,
            "is_buy": size < 0,
            "sz": abs(size),
            "px": price,
            "is_market": True,
            "ro": True,
        }

        return await self.place_order(**close_order)  # type: ignore
