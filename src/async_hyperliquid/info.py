import asyncio
from collections.abc import Sequence
from types import TracebackType
from typing import Literal, Self, cast, overload

from aiohttp import ClientSession, ClientTimeout

from ._internal.http import _HttpTransport, _validate_endpoint_url
from ._internal.info import (
    context_price as _context_price,
    context_price_by_coin as _context_price_by_coin,
    expect_bool as _expect_bool,
    expect_int as _expect_int,
    expect_list as _expect_list,
    expect_object as _expect_object,
    expect_optional_list as _expect_optional_list,
    expect_optional_object as _expect_optional_object,
    expect_pair as _expect_pair,
    expect_string as _expect_string,
    wait_for_tasks as _wait_for_tasks,
)
from ._internal.metadata import (
    _MarketInfo,
    _MetadataSnapshot,
    _build_metadata,
    _market_info,
)
from .errors import ProtocolError
from .types import CandleInterval, JsonObject, JsonValue, Network
from .types.info import (
    AccountState,
    ActiveAssetData,
    AlignedQuoteTokenInfo,
    AllMids,
    AllPerpMetas,
    Candles,
    ClearinghouseState,
    Delegations,
    FrontendOpenOrders,
    FundingRates,
    HistoricalOrders,
    L2Book,
    LedgerUpdates,
    OpenOrders,
    OrderStatus,
    PerpDeployAuctionStatus,
    PerpDexes,
    PerpMeta,
    PerpMetaAndContexts,
    Portfolio,
    Position,
    PredictedFundings,
    Referral,
    SpotClearinghouseState,
    SpotDeployState,
    SpotMeta,
    SpotMetaAndContexts,
    SpotToken,
    StakingHistory,
    StakingRewards,
    StakingSummary,
    SubAccounts,
    TokenDetails,
    TwapSliceFills,
    UserAbstractionState,
    UserFees,
    UserFills,
    UserRateLimit,
    UserRole,
    VaultDetails,
    VaultEquities,
)


class InfoClient:
    """Asynchronous, credential-free client for Hyperliquid Info endpoints."""

    __slots__ = (
        "_info_url",
        "_metadata",
        "_metadata_lock",
        "_owns_transport",
        "_transport",
    )

    _transport: _HttpTransport
    _info_url: str
    _owns_transport: bool
    _metadata: _MetadataSnapshot | None
    _metadata_lock: asyncio.Lock | None

    def __init__(
        self,
        *,
        network: Network = Network.MAINNET,
        info_url: str | None = None,
        session: ClientSession | None = None,
        timeout: ClientTimeout | None = None,
    ) -> None:
        self._configure(
            transport=_HttpTransport(session=session, timeout=timeout),
            info_url=network.info_url if info_url is None else info_url,
            owns_transport=True,
        )

    @classmethod
    def _from_transport(cls, transport: _HttpTransport, *, info_url: str) -> Self:
        client = cls.__new__(cls)
        client._configure(transport=transport, info_url=info_url, owns_transport=False)
        return client

    def _configure(
        self, *, transport: _HttpTransport, info_url: str, owns_transport: bool
    ) -> None:
        self._transport = transport
        self._info_url = _validate_endpoint_url(info_url)
        self._owns_transport = owns_transport
        self._metadata = None
        self._metadata_lock = None

    @property
    def info_url(self) -> str:
        return self._info_url

    async def open(self) -> None:
        if self._owns_transport:
            await self._transport.open()

    async def close(self) -> None:
        if self._owns_transport:
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

    async def _post(self, payload: JsonObject) -> JsonValue:
        return await self._transport.post_json(self._info_url, payload)

    async def all_mids(self, dex: str = "") -> AllMids:
        value = await self._post({"type": "allMids", "dex": dex})
        return cast(AllMids, _expect_object(value, "allMids"))

    @overload
    async def open_orders(
        self, account_address: str, *, frontend: Literal[False] = False, dex: str = ""
    ) -> OpenOrders: ...

    @overload
    async def open_orders(
        self, account_address: str, *, frontend: Literal[True], dex: str = ""
    ) -> FrontendOpenOrders: ...

    async def open_orders(
        self, account_address: str, *, frontend: bool = False, dex: str = ""
    ) -> OpenOrders | FrontendOpenOrders:
        request_type = "frontendOpenOrders" if frontend else "openOrders"
        value = await self._post(
            {"type": request_type, "user": account_address, "dex": dex}
        )
        orders = _expect_list(value, request_type)
        if frontend:
            return cast(FrontendOpenOrders, orders)
        return cast(OpenOrders, orders)

    async def user_fills(
        self,
        account_address: str,
        *,
        aggregate_by_time: bool = False,
        start_time: int | None = None,
        end_time: int | None = None,
    ) -> UserFills:
        payload: JsonObject
        if start_time is None:
            if end_time is not None:
                raise ValueError("end_time requires start_time")
            payload = {
                "type": "userFills",
                "user": account_address,
                "aggregateByTime": aggregate_by_time,
            }
            request_type = "userFills"
        else:
            request_type = "userFillsByTime"
            payload = {
                "type": request_type,
                "user": account_address,
                "aggregateByTime": aggregate_by_time,
                "startTime": start_time,
            }
            if end_time is not None:
                payload["endTime"] = end_time
        value = await self._post(payload)
        return cast(UserFills, _expect_list(value, request_type))

    async def user_rate_limit(self, account_address: str) -> UserRateLimit:
        value = await self._post({"type": "userRateLimit", "user": account_address})
        return cast(UserRateLimit, _expect_object(value, "userRateLimit"))

    async def order_status(
        self, account_address: str, order_id: int | str, *, dex: str = ""
    ) -> OrderStatus:
        value = await self._post(
            {
                "type": "orderStatus",
                "user": account_address,
                "oid": order_id,
                "dex": dex,
            }
        )
        return cast(OrderStatus, _expect_object(value, "orderStatus"))

    async def l2_book(
        self, coin: str, *, n_sig_figs: int | None = None, mantissa: int | None = None
    ) -> L2Book:
        payload: JsonObject = {"type": "l2Book", "coin": coin}
        if n_sig_figs is not None:
            payload["nSigFigs"] = n_sig_figs
        if mantissa is not None:
            payload["mantissa"] = mantissa
        value = await self._post(payload)
        return cast(L2Book, _expect_object(value, "l2Book"))

    async def candles(
        self, coin: str, interval: CandleInterval, start_time: int, end_time: int
    ) -> Candles:
        value = await self._post(
            {
                "type": "candleSnapshot",
                "req": {
                    "coin": coin,
                    "interval": interval.value,
                    "startTime": start_time,
                    "endTime": end_time,
                },
            }
        )
        return cast(Candles, _expect_list(value, "candleSnapshot"))

    async def max_builder_fee(self, user: str, builder: str) -> int:
        value = await self._post(
            {"type": "maxBuilderFee", "user": user, "builder": builder}
        )
        return _expect_int(value, "maxBuilderFee")

    async def historical_orders(self, account_address: str) -> HistoricalOrders:
        value = await self._post({"type": "historicalOrders", "user": account_address})
        return cast(HistoricalOrders, _expect_list(value, "historicalOrders"))

    async def twap_slice_fills(self, account_address: str) -> TwapSliceFills:
        value = await self._post(
            {"type": "userTwapSliceFills", "user": account_address}
        )
        return cast(TwapSliceFills, _expect_list(value, "userTwapSliceFills"))

    async def sub_accounts(self, account_address: str) -> SubAccounts | None:
        value = await self._post({"type": "subAccounts", "user": account_address})
        return cast(SubAccounts | None, _expect_optional_list(value, "subAccounts"))

    async def vault_details(
        self, vault_address: str, *, user: str | None = None
    ) -> VaultDetails | None:
        payload: JsonObject = {"type": "vaultDetails", "vaultAddress": vault_address}
        if user is not None:
            payload["user"] = user
        value = await self._post(payload)
        return cast(VaultDetails | None, _expect_optional_object(value, "vaultDetails"))

    async def vault_equities(self, account_address: str) -> VaultEquities:
        value = await self._post({"type": "userVaultEquities", "user": account_address})
        return cast(VaultEquities, _expect_list(value, "userVaultEquities"))

    async def user_role(self, account_address: str) -> UserRole:
        value = await self._post({"type": "userRole", "user": account_address})
        return cast(UserRole, _expect_object(value, "userRole"))

    async def portfolio(self, account_address: str) -> Portfolio:
        value = await self._post({"type": "portfolio", "user": account_address})
        return cast(Portfolio, _expect_list(value, "portfolio"))

    async def referral(self, account_address: str) -> Referral:
        value = await self._post({"type": "referral", "user": account_address})
        return cast(Referral, _expect_object(value, "referral"))

    async def user_fees(self, account_address: str) -> UserFees:
        value = await self._post({"type": "userFees", "user": account_address})
        return cast(UserFees, _expect_object(value, "userFees"))

    async def delegations(self, account_address: str) -> Delegations:
        value = await self._post({"type": "delegations", "user": account_address})
        return cast(Delegations, _expect_list(value, "delegations"))

    async def staking_summary(self, account_address: str) -> StakingSummary:
        value = await self._post({"type": "delegatorSummary", "user": account_address})
        return cast(StakingSummary, _expect_object(value, "delegatorSummary"))

    async def staking_history(self, account_address: str) -> StakingHistory:
        value = await self._post({"type": "delegatorHistory", "user": account_address})
        return cast(StakingHistory, _expect_list(value, "delegatorHistory"))

    async def staking_rewards(self, account_address: str) -> StakingRewards:
        value = await self._post({"type": "delegatorRewards", "user": account_address})
        return cast(StakingRewards, _expect_list(value, "delegatorRewards"))

    async def user_dex_abstraction(self, account_address: str) -> bool:
        value = await self._post(
            {"type": "userDexAbstraction", "user": account_address}
        )
        return _expect_bool(value, "userDexAbstraction")

    async def user_abstraction(self, account_address: str) -> UserAbstractionState:
        value = await self._post({"type": "userAbstraction", "user": account_address})
        return cast(UserAbstractionState, _expect_string(value, "userAbstraction"))

    async def aligned_quote_token_info(self, token_index: int) -> AlignedQuoteTokenInfo:
        value = await self._post(
            {"type": "alignedQuoteTokenInfo", "token": token_index}
        )
        return cast(
            AlignedQuoteTokenInfo, _expect_object(value, "alignedQuoteTokenInfo")
        )

    async def perp_meta(self, dex: str = "") -> PerpMeta:
        value = await self._post({"type": "meta", "dex": dex})
        return cast(PerpMeta, _expect_object(value, "meta"))

    async def perp_meta_and_contexts(self, dex: str = "") -> PerpMetaAndContexts:
        value = await self._post({"type": "metaAndAssetCtxs", "dex": dex})
        return cast(PerpMetaAndContexts, _expect_pair(value, "metaAndAssetCtxs"))

    async def all_perp_metas(self) -> AllPerpMetas:
        value = await self._post({"type": "allPerpMetas"})
        metas = _expect_list(value, "allPerpMetas")
        return cast(
            AllPerpMetas, [_expect_object(meta, "allPerpMetas") for meta in metas]
        )

    async def perp_dexes(self) -> PerpDexes:
        value = await self._post({"type": "perpDexs"})
        return cast(PerpDexes, _expect_list(value, "perpDexs"))

    async def perp_account_state(
        self, account_address: str, dex: str = ""
    ) -> ClearinghouseState:
        value = await self._post(
            {"type": "clearinghouseState", "user": account_address, "dex": dex}
        )
        return cast(ClearinghouseState, _expect_object(value, "clearinghouseState"))

    async def funding_updates(
        self, account_address: str, start_time: int, *, end_time: int | None = None
    ) -> LedgerUpdates:
        return await self._ledger_updates(
            "userFunding", account_address, start_time, end_time
        )

    async def non_funding_ledger_updates(
        self, account_address: str, start_time: int, *, end_time: int | None = None
    ) -> LedgerUpdates:
        return await self._ledger_updates(
            "userNonFundingLedgerUpdates", account_address, start_time, end_time
        )

    async def _ledger_updates(
        self,
        request_type: str,
        account_address: str,
        start_time: int,
        end_time: int | None,
    ) -> LedgerUpdates:
        payload: JsonObject = {
            "type": request_type,
            "user": account_address,
            "startTime": start_time,
        }
        if end_time is not None:
            payload["endTime"] = end_time
        value = await self._post(payload)
        return cast(LedgerUpdates, _expect_list(value, request_type))

    async def funding_history(
        self, coin: str, start_time: int, *, end_time: int | None = None
    ) -> FundingRates:
        payload: JsonObject = {
            "type": "fundingHistory",
            "coin": coin,
            "startTime": start_time,
        }
        if end_time is not None:
            payload["endTime"] = end_time
        value = await self._post(payload)
        return cast(FundingRates, _expect_list(value, "fundingHistory"))

    async def predicted_fundings(self) -> PredictedFundings:
        value = await self._post({"type": "predictedFundings"})
        return cast(PredictedFundings, _expect_list(value, "predictedFundings"))

    async def perps_at_open_interest_cap(self) -> list[str]:
        value = await self._post({"type": "perpsAtOpenInterestCap"})
        entries = _expect_list(value, "perpsAtOpenInterestCap")
        if not all(isinstance(entry, str) for entry in entries):
            raise ProtocolError("perpsAtOpenInterestCap response must contain strings")
        return cast(list[str], entries)

    async def perp_deploy_auction_status(self) -> PerpDeployAuctionStatus:
        value = await self._post({"type": "perpDeployAuctionStatus"})
        return cast(
            PerpDeployAuctionStatus, _expect_object(value, "perpDeployAuctionStatus")
        )

    async def active_asset_data(
        self, account_address: str, coin: str
    ) -> ActiveAssetData:
        value = await self._post(
            {"type": "activeAssetData", "user": account_address, "coin": coin}
        )
        return cast(ActiveAssetData, _expect_object(value, "activeAssetData"))

    async def spot_meta(self) -> SpotMeta:
        value = await self._post({"type": "spotMeta"})
        return cast(SpotMeta, _expect_object(value, "spotMeta"))

    async def spot_meta_and_contexts(self) -> SpotMetaAndContexts:
        value = await self._post({"type": "spotMetaAndAssetCtxs"})
        return cast(SpotMetaAndContexts, _expect_pair(value, "spotMetaAndAssetCtxs"))

    async def spot_account_state(self, account_address: str) -> SpotClearinghouseState:
        value = await self._post(
            {"type": "spotClearinghouseState", "user": account_address}
        )
        return cast(
            SpotClearinghouseState, _expect_object(value, "spotClearinghouseState")
        )

    async def spot_deploy_state(self, account_address: str) -> SpotDeployState:
        value = await self._post({"type": "spotDeployState", "user": account_address})
        return cast(SpotDeployState, _expect_object(value, "spotDeployState"))

    async def token_details(self, token_id: str) -> TokenDetails | None:
        value = await self._post({"type": "tokenDetails", "tokenId": token_id})
        return cast(TokenDetails | None, _expect_optional_object(value, "tokenDetails"))

    async def perp_dex_names(self) -> tuple[str, ...]:
        dexs = await self.perp_dexes()
        names: list[str] = []
        for dex in dexs:
            if dex is None:
                names.append("")
                continue
            if not isinstance(dex, dict):
                raise ProtocolError("perpDexs contains malformed metadata")
            name = dex.get("name")
            if not isinstance(name, str):
                raise ProtocolError("perpDexs contains a malformed name")
            names.append(name)
        return tuple(names)

    def _get_metadata_lock(self) -> asyncio.Lock:
        lock = self._metadata_lock
        if lock is None:
            lock = asyncio.Lock()
            self._metadata_lock = lock
        return lock

    async def _load_metadata(self) -> _MetadataSnapshot:
        dex_task = asyncio.create_task(self.perp_dex_names())
        perp_task = asyncio.create_task(self.all_perp_metas())
        spot_task = asyncio.create_task(self.spot_meta())
        await _wait_for_tasks((dex_task, perp_task, spot_task))
        return _build_metadata(
            dex_task.result(), perp_task.result(), spot_task.result()
        )

    async def _ensure_metadata(self) -> _MetadataSnapshot:
        snapshot = self._metadata
        if snapshot is not None:
            return snapshot
        async with self._get_metadata_lock():
            snapshot = self._metadata
            if snapshot is None:
                snapshot = await self._load_metadata()
                self._metadata = snapshot
            return snapshot

    async def refresh_metadata(self) -> None:
        async with self._get_metadata_lock():
            snapshot = await self._load_metadata()
            self._metadata = snapshot

    async def coin_name(self, coin: str) -> str:
        snapshot = await self._ensure_metadata()
        name = snapshot.coin_by_alias.get(coin)
        if name is None:
            raise ValueError(f"unknown coin: {coin}")
        return name

    async def coin_symbol(self, coin: str) -> str:
        snapshot = await self._ensure_metadata()
        name = snapshot.coin_by_alias.get(coin)
        if name is None:
            raise ValueError(f"unknown coin: {coin}")
        symbol = snapshot.symbol_by_coin.get(name)
        if symbol is None:
            raise ValueError(f"coin has no market symbol: {coin}")
        return symbol

    async def asset_id(self, coin: str) -> int:
        return (await self._market_info(coin)).asset

    async def size_decimals(self, coin: str) -> int:
        return (await self._market_info(coin)).size_decimals

    async def _market_info(self, coin: str) -> _MarketInfo:
        return _market_info(await self._ensure_metadata(), coin)

    async def _market_infos(self, coins: Sequence[str]) -> tuple[_MarketInfo, ...]:
        snapshot = await self._ensure_metadata()
        return tuple(_market_info(snapshot, coin) for coin in coins)

    async def spot_token_metadata(self, coin: str) -> SpotToken:
        snapshot = await self._ensure_metadata()
        name = snapshot.coin_by_alias.get(coin)
        token = None if name is None else snapshot.spot_token_by_coin.get(name)
        if token is None:
            raise ValueError(f"unknown spot token: {coin}")
        return token.copy()

    async def token_id(self, coin: str) -> str:
        return (await self.spot_token_metadata(coin))["tokenId"]

    async def mark_price(self, coin: str) -> float:
        snapshot = await self._ensure_metadata()
        name = snapshot.coin_by_alias.get(coin)
        if name is None:
            raise ValueError(f"unknown coin: {coin}")

        if name in snapshot.spot_market_coins:
            _, contexts = await self.spot_meta_and_contexts()
            return _context_price_by_coin(
                cast(list[JsonValue], contexts), name, "markPx", "spotMetaAndAssetCtxs"
            )

        perp_context = snapshot.perp_context_by_coin.get(name)
        if perp_context is None:
            raise ValueError(f"coin has no market context: {coin}")
        dex, context_index = perp_context
        _, contexts = await self.perp_meta_and_contexts(dex)
        return _context_price(
            cast(list[JsonValue], contexts), context_index, "markPx", "metaAndAssetCtxs"
        )

    async def _mid_prices(self, markets: Sequence[_MarketInfo]) -> tuple[float, ...]:
        commands = tuple(markets)
        if not commands:
            return ()
        dexs = tuple(dict.fromkeys(market.dex for market in commands))
        tasks = {dex: asyncio.create_task(self.all_mids(dex)) for dex in dexs}
        await _wait_for_tasks(tuple(tasks.values()))
        mids_by_dex = {dex: task.result() for dex, task in tasks.items()}

        prices: list[float] = []
        for market in commands:
            price = mids_by_dex[market.dex].get(market.coin)
            if not isinstance(price, str):
                raise ProtocolError("allMids is missing a string price")
            try:
                prices.append(float(price))
            except ValueError:
                raise ProtocolError("allMids contains an invalid price") from None
        return tuple(prices)

    async def mid_price(self, coin: str) -> float:
        market = await self._market_info(coin)
        return (await self._mid_prices((market,)))[0]

    async def account_state(
        self, account_address: str, *, dexs: tuple[str, ...] = ("",)
    ) -> AccountState:
        additional_dexes = tuple(dict.fromkeys(dex for dex in dexs if dex))
        perp_task = asyncio.create_task(self.perp_account_state(account_address))
        spot_task = asyncio.create_task(self.spot_account_state(account_address))
        dex_tasks = {
            dex: asyncio.create_task(self.perp_account_state(account_address, dex))
            for dex in additional_dexes
        }
        await _wait_for_tasks((perp_task, spot_task, *dex_tasks.values()))
        return {
            "perp": perp_task.result(),
            "spot": spot_task.result(),
            "dexs": {dex: task.result() for dex, task in dex_tasks.items()},
        }

    async def positions(
        self, account_address: str, *, dexs: tuple[str, ...] = ("",)
    ) -> list[Position]:
        dexs = tuple(dict.fromkeys(dexs))
        tasks = tuple(
            asyncio.create_task(self.perp_account_state(account_address, dex))
            for dex in dexs
        )
        await _wait_for_tasks(tasks)
        positions: list[Position] = []
        for task in tasks:
            state = task.result()
            entries = _expect_list(state.get("assetPositions"), "assetPositions")
            for value in entries:
                entry = _expect_object(value, "assetPositions")
                position = _expect_object(
                    entry.get("position"), "assetPositions position"
                )
                positions.append(cast(Position, position))
        return positions


__all__ = ["InfoClient"]
