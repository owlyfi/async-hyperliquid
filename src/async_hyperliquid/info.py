from typing import Any

from aiohttp import ClientSession

from async_hyperliquid.async_api import AsyncAPI
from async_hyperliquid.utils.types import (
    Depth,
    Candles,
    Endpoint,
    PerpDexs,
    PerpMeta,
    Referral,
    SpotMeta,
    UserFees,
    UserRole,
    Portfolio,
    RateLimit,
    UserFills,
    VaultInfo,
    Delegations,
    PerpMetaCtx,
    SpotMetaCtx,
    SubAccounts,
    FundingRates,
    TokenDetails,
    UserFundings,
    VaultDeposits,
    CandleInterval,
    StakingHistory,
    StakingRewards,
    StakingSummary,
    TwapSliceFills,
    UserOpenOrders,
    ActiveAssetData,
    OrderWithStatus,
    SpotDeployState,
    AssetFundingInfo,
    HistoricalOrders,
    PerpDeployStatus,
    ClearinghouseState,
    SpotClearinghouseState,
)


class InfoAPI(AsyncAPI):
    def __init__(self, base_url: str, session: ClientSession):
        super().__init__(Endpoint.INFO, base_url, session)

    async def get_all_mids(self, dex: str = "") -> dict[str, int]:
        payload = {"type": "allMids", "dex": dex}
        return await self.post(payload)

    async def get_user_open_orders(
        self, address: str, is_frontend: bool = False, dex: str = ""
    ) -> UserOpenOrders:
        payload = {
            "type": "frontendOpenOrders" if is_frontend else "openOrders",
            "user": address,
            "dex": dex,
        }
        return await self.post(payload)

    async def get_user_fills(
        self,
        address: str,
        aggregated: bool = False,
        *,
        start_time: int | None = None,
        end_time: int | None = None,
    ) -> UserFills:
        payload = {
            "type": "userFillsByTime" if start_time else "userFills",
            "user": address,
            "aggregateByTime": aggregated,
        }
        if start_time:
            payload["startTime"] = start_time
            payload["endTime"] = end_time
        return await self.post(payload)

    async def get_user_rate_limit(self, address: str) -> RateLimit:
        payload = {"type": "userRateLimit", "user": address}
        return await self.post(payload)

    async def get_order_status(
        self, order_id: str | int, address: str, dex: str = ""
    ) -> OrderWithStatus:
        payload = {
            "type": "orderStatus",
            "user": address,
            "oid": order_id,
            "dex": dex,
        }
        return await self.post(payload)

    async def get_depth(
        self, coin: str, level: int | None = None, mantissa: int | None = None
    ) -> list[Depth]:
        payload: dict[str, Any] = {"type": "l2Book", "coin": coin}
        if level:
            payload["nSigFigs"] = level
        if level and level == 5 and mantissa:
            payload["mantissa"] = mantissa
        return await self.post(payload)

    async def get_candles(
        self, coin: str, interval: CandleInterval, start: int, end: int
    ) -> Candles:
        req = {
            "coin": coin,
            "interval": interval.value,
            "startTime": start,
            "endTime": end,
        }
        payload = {"type": "candleSnapshot", "req": req}
        return await self.post(payload)

    async def check_user_builder_fee(self, user: str, builder: str) -> int:
        payload = {"type": "maxBuilderFee", "user": user, "builder": builder}
        return await self.post(payload)

    async def get_user_order_history(self, address: str) -> HistoricalOrders:
        payload = {"type": "historicalOrders", "user": address}
        return await self.post(payload)

    async def get_user_twap_fills(self, address: str) -> TwapSliceFills:
        payload = {"type": "userTwapSliceFills", "user": address}
        return await self.post(payload)

    async def get_user_subaccounts(self, address: str) -> SubAccounts:
        payload = {"type": "subAccounts", "user": address}
        return await self.post(payload)

    async def get_vault_info(
        self, address: str, user: str | None = None
    ) -> VaultInfo:
        payload = {"type": "vaultDetails", "vaultAddress": address}
        if user:
            payload["user"] = user
        return await self.post(payload)

    async def get_user_vault_deposits(self, address: str) -> VaultDeposits:
        payload = {"type": "userVaultEquities", "user": address}
        return await self.post(payload)

    async def get_user_role(self, address: str) -> UserRole:
        payload = {"type": "userRole", "user": address}
        return await self.post(payload)

    async def get_user_portfolio(self, address: str) -> Portfolio:
        payload = {"type": "portfolio", "user": address}
        return await self.post(payload)

    async def get_user_referral(self, address: str) -> Referral:
        payload = {"type": "referral", "user": address}
        return await self.post(payload)

    async def get_user_fees(self, address: str) -> UserFees:
        payload = {"type": "userFees", "user": address}
        return await self.post(payload)

    async def get_user_delegations(self, address: str) -> Delegations:
        payload = {"type": "delegations", "user": address}
        return await self.post(payload)

    async def get_user_staking(self, address: str) -> Delegations:
        payload = {"type": "delegations", "user": address}
        return await self.post(payload)

    async def get_user_staking_summary(self, address: str) -> StakingSummary:
        payload = {"type": "delegatorSummary", "user": address}
        return await self.post(payload)

    async def get_user_staking_history(self, address: str) -> StakingHistory:
        payload = {"type": "delegatorHistory", "user": address}
        return await self.post(payload)

    async def get_user_staking_rewards(self, address: str) -> StakingRewards:
        payload = {"type": "delegatorRewards", "user": address}
        return await self.post(payload)

    async def get_user_dex_abstraction(self, address: str) -> bool:
        payload = {"type": "userDexAbstraction", "user": address}
        return await self.post(payload)

    async def get_user_abstraction_state(self, address: str) -> str:
        payload = {"type": "userAbstraction", "user": address}
        return await self.post(payload)

    async def get_aligned_quote_token_status(self, token: int):
        payload = {"type": "alignedQuoteTokenInfo", "token": token}
        return await self.post(payload)

    # Perpetuals
    async def get_perp_meta(self, dex: str = "") -> PerpMeta:
        payload = {"type": "meta", "dex": dex}
        return await self.post(payload)

    async def get_perp_meta_ctx(self) -> PerpMetaCtx:
        payload = {"type": "metaAndAssetCtxs"}
        return await self.post(payload)

    async def get_perp_dexs(self) -> PerpDexs:
        payload = {"type": "perpDexs"}
        return await self.post(payload)

    async def get_perp_clearinghouse_state(
        self, address: str, dex: str = ""
    ) -> ClearinghouseState:
        payload = {"type": "clearinghouseState", "user": address, "dex": dex}
        return await self.post(payload)

    async def get_user_funding(
        self,
        address: str,
        start_time: int,
        end_time: int | None = None,
        is_funding: bool = True,
    ) -> UserFundings:
        payload = {
            "type": "userFunding"
            if is_funding
            else "userNonFundingLedgerUpdates",
            "user": address,
            "startTime": start_time,
            "endTime": end_time,
        }
        return await self.post(payload)

    async def get_funding_rates(
        self, coin: str, start_time: int, end_time: int | None = None
    ) -> FundingRates:
        payload = {
            "type": "fundingHistory",
            "coin": coin,
            "startTime": start_time,
            "endTime": end_time,
        }
        return await self.post(payload)

    async def get_predicted_funding(self) -> AssetFundingInfo:
        payload = {"type": "predictedFundings"}
        return await self.post(payload)

    async def get_perps_at_open_interest_cap(self) -> list[str]:
        payload = {"type": "perpsAtOpenInterestCap"}
        return await self.post(payload)

    async def get_perp_deploy_status(self) -> PerpDeployStatus:
        payload = {"type": "perpDeployAuctionStatus"}
        return await self.post(payload)

    async def get_user_active_asset_data(
        self, address: str, coin: str
    ) -> ActiveAssetData:
        payload = {"type": "activeAssetData", "user": address, "coin": coin}
        return await self.post(payload)

    # Spot
    async def get_spot_meta(self) -> SpotMeta:
        payload = {"type": "spotMeta"}
        return await self.post(payload)

    async def get_spot_meta_ctx(self) -> SpotMetaCtx:
        payload = {"type": "spotMetaAndAssetCtxs"}
        return await self.post(payload)

    async def get_user_token_balances(
        self, address: str
    ) -> SpotClearinghouseState:
        return await self.get_spot_clearinghouse_state(address)

    async def get_spot_clearinghouse_state(
        self, address: str
    ) -> SpotClearinghouseState:
        payload = {"type": "spotClearinghouseState", "user": address}
        return await self.post(payload)

    async def get_spot_deploy_state(self, address: str) -> SpotDeployState:
        payload = {"type": "spotDeployState", "user": address}
        return await self.post(payload)

    async def get_token_info(self, token_id: str) -> TokenDetails:
        payload = {"type": "tokenDetails", "tokenId": token_id}
        return await self.post(payload)
