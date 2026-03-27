import asyncio
import warnings
from typing import Literal, cast

from async_hyperliquid.utils.constants import ONE_HOUR_MS, PERP_DEX_OFFSET, SPOT_OFFSET
from async_hyperliquid.utils.miscs import get_coin_dex, get_timestamp_ms
from async_hyperliquid.utils.types import (
    Abstraction,
    AccountState,
    ClearinghouseState,
    OrderWithStatus,
    PerpMeta,
    PerpMetaCtxItem,
    Portfolio,
    Position,
    SpotMeta,
    SpotClearinghouseState,
    SpotMetaCtxItem,
    UserDeposit,
    UserNonFundingDelta,
    UserOpenOrders,
    UserTransfer,
    UserWithdraw,
)

from .core import AsyncHyperliquidCore


class AsyncHyperliquidInfoClient(AsyncHyperliquidCore):
    async def _get_perp_mark_price(self, coin_name: str, dex: str = "") -> float:
        meta_ctx = await self.info.get_perp_meta_ctx(dex)
        meta = cast(PerpMeta, meta_ctx[0])
        asset_ctxs = cast(list[PerpMetaCtxItem], meta_ctx[1])

        for idx, info in enumerate(meta["universe"]):
            if info["name"] == coin_name:
                return float(asset_ctxs[idx]["markPx"])

        raise ValueError(f"Coin {coin_name} not found in perp dex '{dex}'")

    async def _get_spot_mark_price(self, coin_name: str) -> float:
        meta_ctx = await self.info.get_spot_meta_ctx()
        meta = cast(SpotMeta, meta_ctx[0])
        asset_ctxs = cast(list[SpotMetaCtxItem], meta_ctx[1])

        for info in meta["universe"]:
            if info["name"] == coin_name:
                asset_index = info["index"]
                return float(asset_ctxs[asset_index]["markPx"])

        raise ValueError(f"Coin {coin_name} not found in spot metadata")

    async def get_mark_price(self, coin: str) -> float:
        if ":" in coin:
            return await self._get_perp_mark_price(coin, get_coin_dex(coin))

        coin_name = await self.get_coin_name(coin)
        if coin_name not in self.coin_assets:
            raise ValueError(f"Coin {coin}({coin_name}) not found")

        asset = self.coin_assets[coin_name]
        is_spot_asset = SPOT_OFFSET <= asset < PERP_DEX_OFFSET
        if is_spot_asset:
            return await self._get_spot_mark_price(coin_name)

        return await self._get_perp_mark_price(coin_name, get_coin_dex(coin_name))

    async def get_market_price(self, coin: str) -> float:
        warnings.warn(
            "get_market_price is deprecated and will remove in the future, use get_mid_price instead"
        )
        return await self.get_mark_price(coin)

    async def get_all_market_prices(
        self, market: Literal["spot", "perp", "all"] = "all"
    ) -> dict[str, float]:
        warnings.warn(
            "get_all_market_prices is deprecated and will remove in the future, use get_all_mids instead"
        )
        is_spot = market == "spot"
        is_perp = market == "perp"
        is_all = market == "all"

        prices: dict[str, float] = {}

        await self.init_metas()
        spot_data = None
        perp_data = None
        if is_all:
            spot_data, perp_data = await asyncio.gather(
                self.info.get_spot_meta_ctx(), self.info.get_perp_meta_ctx()
            )
        else:
            if is_spot:
                spot_data = await self.info.get_spot_meta_ctx()
            if is_perp:
                perp_data = await self.info.get_perp_meta_ctx()

        is_perp = is_perp or is_all
        is_spot = is_spot or is_all

        for coin, asset in self.coin_assets.items():
            is_perp_asset = asset < SPOT_OFFSET
            is_spot_asset = asset >= SPOT_OFFSET and asset < PERP_DEX_OFFSET
            if is_perp_asset and is_perp:
                prices[coin] = float(perp_data[1][asset]["markPx"])  # type: ignore
            if is_spot_asset and is_spot:
                asset -= SPOT_OFFSET
                prices[coin] = float(spot_data[1][asset]["markPx"])  # type: ignore
        return prices

    async def get_mid_price(self, coin: str) -> float:
        dex = get_coin_dex(coin)
        coin_name = await self.get_coin_name(coin)
        dex_mids = await self.info.get_all_mids(dex)
        return float(dex_mids[coin_name])

    async def get_dexs_mids(self, dexs: list[str]) -> dict[str, float]:
        tasks = [self.info.get_all_mids(dex) for dex in dexs]
        results = await asyncio.gather(*tasks)

        all_mids = {}
        for mids in results:
            all_mids.update(mids)

        return {k: float(v) for k, v in all_mids.items()}

    async def get_all_mids(self) -> dict[str, float]:
        return await self.get_dexs_mids(self.perp_dexs)

    async def get_perp_account_state(
        self, address: str | None = None, dex: str = ""
    ) -> ClearinghouseState:
        if not address:
            address = self.address

        return await self.info.get_perp_clearinghouse_state(address, dex)

    async def get_spot_account_state(
        self, address: str | None = None
    ) -> SpotClearinghouseState:
        if not address:
            address = self.address
        return await self.info.get_spot_clearinghouse_state(address)

    async def get_account_state(self, address: str | None = None) -> AccountState:
        if not address:
            address = self.address

        tasks = [
            self.get_perp_account_state(address),
            self.get_spot_account_state(address),
        ]

        dexs = self.perp_dexs[1:]
        for dex in dexs:
            tasks.append(self.get_perp_account_state(address, dex))

        results = await asyncio.gather(*tasks)

        account_state: AccountState = {
            "perp": results[0],
            "spot": results[1],
            "dexs": {dex: results[i + 2] for i, dex in enumerate(dexs)},
        }

        return account_state

    async def get_account_portfolio(self, address: str | None = None) -> Portfolio:
        if not address:
            address = self.address

        return await self.info.get_user_portfolio(address)

    async def get_latest_ledgers(
        self,
        ledger_type: str = "deposit",
        address: str | None = None,
        start_time: int | None = None,
        end_time: int | None = None,
    ) -> list[UserNonFundingDelta]:
        if not start_time:
            now = get_timestamp_ms()
            start_time = now - ONE_HOUR_MS
        if not address:
            address = self.address
        data = await self.info.get_user_funding(
            address, start_time, end_time=end_time, is_funding=False
        )
        return [d for d in data if d["delta"]["type"] == ledger_type]  # type: ignore

    async def get_latest_deposits(
        self,
        address: str | None = None,
        start_time: int | None = None,
        end_time: int | None = None,
    ) -> list[UserDeposit]:
        return await self.get_latest_ledgers("deposit", address, start_time, end_time)  # type: ignore

    async def get_latest_withdraws(
        self,
        address: str | None = None,
        start_time: int | None = None,
        end_time: int | None = None,
    ) -> list[UserWithdraw]:
        return await self.get_latest_ledgers("withdraw", address, start_time, end_time)  # type: ignore

    async def get_latest_transfers(
        self,
        address: str | None = None,
        start_time: int | None = None,
        end_time: int | None = None,
    ) -> list[UserTransfer]:
        return await self.get_latest_ledgers(
            "accountClassTransfer", address, start_time, end_time
        )  # type: ignore

    async def get_user_open_orders(
        self, address: str | None = None, is_frontend: bool = False, dex: str = ""
    ) -> UserOpenOrders:
        if not address:
            address = self.address
        return await self.info.get_user_open_orders(address, is_frontend, dex)

    async def get_order_status(
        self, order_id: int, address: str | None = None, dex: str = ""
    ) -> OrderWithStatus:
        if not address:
            address = self.address
        return await self.info.get_order_status(order_id, address, dex)

    async def get_dex_positions(
        self, address: str | None = None, dex: str = ""
    ) -> list[Position]:
        if not address:
            address = self.address

        resp = await self.info.get_perp_clearinghouse_state(address, dex)
        positions = [p["position"] for p in resp["assetPositions"]]
        return positions

    async def get_all_positions(
        self, address: str | None = None, dexs: list[str] | None = None
    ) -> list[Position]:
        if not address:
            address = self.address

        positions = []
        if dexs is None:
            dexs = self.perp_dexs

        tasks = [self.get_dex_positions(address, dex) for dex in dexs]

        results = await asyncio.gather(*tasks)
        for result in results:
            positions.extend(result)
        return positions

    async def get_user_abstraction(self, address: str | None = None) -> Abstraction:
        if not address:
            address = self.address
        return await self.info.get_user_abstraction(address)
