import math
import asyncio
from typing import Literal

from aiohttp import ClientSession, ClientTimeout
from eth_account import Account
from hl_web3.info import Info as EVMInfo
from hl_web3.exchange import Exchange as EVMExchange
from hl_web3.utils.constants import HL_RPC_URL, HL_TESTNET_RPC_URL
from eth_account.signers.local import LocalAccount

from async_hyperliquid.info import InfoAPI
from async_hyperliquid.exchange import ExchangeAPI
from async_hyperliquid.async_api import AsyncAPI
from async_hyperliquid.utils.miscs import (
    round_px,
    round_float,
    get_coin_dex,
    get_timestamp_ms,
    round_token_amount,
)
from async_hyperliquid.utils.types import (
    Cloid,
    Metas,
    PerpMeta,
    Position,
    SpotMeta,
    OrderType,
    Portfolio,
    LimitOrder,
    Abstraction,
    UserDeposit,
    AccountState,
    GroupOptions,
    OrderBuilder,
    UserTransfer,
    UserWithdraw,
    SpotTokenMeta,
    UserOpenOrders,
    OrderWithStatus,
    PlaceOrderRequest,
    BatchCancelRequest,
    ClearinghouseState,
    UserNonFundingDelta,
    BatchPlaceOrderRequest,
    SpotClearinghouseState,
)
from async_hyperliquid.utils.signing import (
    encode_order,
    orders_to_action,
    sign_withdraw_action,
    sign_send_asset_action,
    sign_usd_transfer_action,
    sign_approve_agent_action,
    sign_spot_transfer_action,
    sign_token_delegate_action,
    sign_staking_deposit_action,
    sign_staking_withdraw_action,
    sign_usd_class_transfer_action,
    sign_approve_builder_fee_action,
    sign_user_dex_abstraction_action,
    sign_user_set_abstraction_action,
    sign_convert_to_multi_sig_user_action,
)
from async_hyperliquid.utils.constants import (
    USD_FACTOR,
    HYPE_FACTOR,
    ONE_HOUR_MS,
    SPOT_OFFSET,
    MAINNET_API_URL,
    PERP_DEX_OFFSET,
    TESTNET_API_URL,
)
from async_hyperliquid.utils.decorators import private_key_required


class AsyncHyperliquid(AsyncAPI):
    address: str
    is_mainnet: bool
    account: LocalAccount
    session: ClientSession
    base_url: str
    vault: str | None

    coin_assets: dict[str, int]
    coin_names: dict[str, str]
    coin_symbols: dict[str, str]
    asset_sz_decimals: dict[int, int]
    spot_tokens: dict[str, SpotTokenMeta]

    # HIP 3
    perp_dexs: list[str]

    enable_evm: bool
    evm_info: EVMInfo
    evm_exchange: EVMExchange

    def __init__(
        self,
        address: str,
        api_key: str,
        is_mainnet: bool = True,
        enable_evm: bool = False,
        evm_rpc_url: str | None = None,
        private_key: str | None = None,
        vault: str | None = None,
        perp_dexs: list[str] = [""],
    ):
        self.address = address
        self.is_mainnet = is_mainnet
        self.account = Account.from_key(api_key)
        self.session = ClientSession(timeout=ClientTimeout(connect=3))
        self.base_url = MAINNET_API_URL if is_mainnet else TESTNET_API_URL
        self.info = InfoAPI(self.base_url, self.session)
        self.exchange = ExchangeAPI(
            self.account, self.session, self.base_url, address=self.address
        )

        self.coin_assets = {}
        self.coin_names = {}
        self.coin_symbols = {}
        self.asset_sz_decimals = {}

        self.spot_tokens = {}

        # sub-account or vault address
        self.vault = vault
        # expires will cause actions to be rejected after that timestamp in milliseconds
        self.expires: int | None = None

        self.perp_dexs: list[str] = perp_dexs

        if enable_evm:
            self._init_evm_client(private_key, evm_rpc_url)

    def set_expires(self, expires: int | None) -> None:
        self.expires = expires

    def _init_evm_client(
        self, private_key: str | None, rpc_url: str | None = None
    ) -> None:
        if rpc_url is None:
            rpc_url = HL_RPC_URL if self.is_mainnet else HL_TESTNET_RPC_URL

        self.evm_info = EVMInfo(rpc_url)

        if private_key is None:
            if self.account.address != self.address:
                raise ValueError(
                    "EVM Exchange client can not init without private key"
                )
            else:
                private_key = self.account.key.hex()

        self.evm_exchange = EVMExchange(rpc_url, private_key)

    def _init_perp_meta(self, meta: PerpMeta, offset: int) -> None:
        for asset, info in enumerate(meta["universe"]):
            asset += offset
            asset_name = info["name"]
            self.coin_assets[asset_name] = asset
            self.coin_names[asset_name] = asset_name
            self.asset_sz_decimals[asset] = info["szDecimals"]

    def _init_spot_meta(self, meta: SpotMeta) -> None:
        for info in meta["universe"]:
            asset = info["index"] + SPOT_OFFSET
            asset_name = info["name"]

            self.coin_assets[asset_name] = asset

            self.coin_names[asset_name] = asset_name
            # For token pairs
            base, quote = info["tokens"]
            base_info = meta["tokens"][base]
            base_name = base_info["name"]
            quote_name = meta["tokens"][quote]["name"]
            name = f"{base_name}/{quote_name}"
            if name not in self.coin_names:
                self.coin_names[name] = asset_name

            self.asset_sz_decimals[asset] = base_info["szDecimals"]

            # For token info
            self.spot_tokens[asset_name] = meta["tokens"][base]

    def _update_coin_symbols(self) -> None:
        self.coin_symbols = {
            v: k for k, v in self.coin_names.items() if not k.startswith("@")
        }

    async def init_metas(self) -> None:
        # First wave: get core perp meta, spot meta, and all dex names
        meta_task = self.info.get_perp_meta()
        spot_meta_task = self.info.get_spot_meta()
        all_dex_names_task = self.get_all_dex_name()

        meta, spot_meta, all_dex_names = await asyncio.gather(
            meta_task, spot_meta_task, all_dex_names_task
        )

        self._init_perp_meta(meta, 0)
        self._init_spot_meta(spot_meta)

        # Second wave: get each perp dex meta
        # Only fetch for specified DEXs and avoid overwriting self.perp_dexs
        dex_meta_tasks = []
        dex_indices = []
        for dex in self.perp_dexs:
            if dex == "":
                continue
            try:
                idx = all_dex_names.index(dex)
                if idx > 0:
                    dex_meta_tasks.append(self.info.get_perp_meta(dex))
                    dex_indices.append(idx)
            except ValueError:
                continue

        if dex_meta_tasks:
            dex_metas = await asyncio.gather(*dex_meta_tasks)
            for idx, dex_meta in zip(dex_indices, dex_metas):
                dex_asset_offset = PERP_DEX_OFFSET + (idx - 1) * 10000
                self._init_perp_meta(dex_meta, dex_asset_offset)

        self._update_coin_symbols()

    async def get_metas(self, perp_only: bool = False) -> Metas:
        metas: Metas = {"perp": {}, "spot": [], "dexs": {}}  # type: ignore
        perp_meta = await self.info.get_perp_meta()
        if perp_only:
            metas["perp"] = perp_meta
            return metas

        metas["spot"] = await self.info.get_spot_meta()
        return metas

    async def get_all_metas(self) -> Metas:
        dexs = await self.get_all_dex_name()
        dex_metas = {}

        for dex in dexs[1:]:
            meta = await self.info.get_perp_meta(dex)
            dex_metas[dex] = meta

        spot_meta = await self.info.get_spot_meta()
        perp_meta = await self.info.get_perp_meta()
        return {"perp": perp_meta, "spot": spot_meta, "dexs": dex_metas}

    async def get_all_dex_name(self) -> list[str]:
        names = []
        dexs = await self.info.get_perp_dexs()
        for dex in dexs:
            if dex is None:
                names.append("")  # default for hyperliquid
            else:
                names.append(dex["name"])
        return names

    async def get_coin_name(self, coin: str) -> str:
        if not hasattr(self, "coin_names") or coin not in self.coin_names:
            await self.init_metas()

        if coin not in self.coin_names:
            raise ValueError(f"Coin {coin} not found")

        return self.coin_names[coin]

    async def get_coin_asset(self, coin: str) -> int:
        coin_name = await self.get_coin_name(coin)

        if coin_name not in self.coin_assets:
            raise ValueError(f"Coin {coin}({coin_name}) not found")

        return self.coin_assets[coin_name]

    async def get_coin_symbol(self, coin: str) -> str:
        coin_name = await self.get_coin_name(coin)
        return self.coin_symbols[coin_name]

    async def get_coin_sz_decimals(self, coin: str) -> int:
        coin_name = await self.get_coin_name(coin)
        asset = await self.get_coin_asset(coin_name)
        return self.asset_sz_decimals[asset]

    async def get_token_info(self, coin: str) -> SpotTokenMeta:
        coin_name = await self.get_coin_name(coin)
        return self.spot_tokens[coin_name]

    async def get_token_id(self, coin: str) -> str:
        token_info = await self.get_token_info(coin)
        if not token_info:
            raise ValueError(f"Token {coin} not found")

        return token_info["tokenId"]

    async def get_market_price(self, coin: str) -> float:
        import warnings

        warnings.warn(
            "get_market_price is deprecated and will remove in the future, use get_mid_price instead"
        )
        # Only works for hyperliquid core perp and spot market
        coin_name = await self.get_coin_name(coin)
        market_prices = await self.get_all_market_prices()
        return market_prices[coin_name]

    async def get_all_market_prices(
        self, market: Literal["spot", "perp", "all"] = "all"
    ) -> dict[str, float]:
        import warnings

        warnings.warn(
            "get_all_market_prices is deprecated and will remove in the future, use get_all_mids instead"
        )
        # Only works for hyperliquid core perp and spot market
        is_spot = market == "spot"
        is_perp = market == "perp"
        is_all = market == "all"

        prices: dict[str, float] = {}

        await self.init_metas()
        spot_data = None
        perp_data = None
        if is_spot or is_all:
            spot_data = await self.info.get_spot_meta_ctx()
        if is_perp or is_all:
            perp_data = await self.info.get_perp_meta_ctx()

        is_perp = is_perp or is_all  # perp or all
        is_spot = is_spot or is_all  # spot or all

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

    async def get_account_state(
        self, address: str | None = None
    ) -> AccountState:
        if not address:
            address = self.address

        # Parallelize requests for perp, spot, and each dex
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

    async def get_account_portfolio(
        self, address: str | None = None
    ) -> Portfolio:
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
            one_hour = ONE_HOUR_MS
            start_time = now - one_hour
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
        return await self.get_latest_ledgers(
            "deposit", address, start_time, end_time
        )  # type: ignore

    async def get_latest_withdraws(
        self,
        address: str | None = None,
        start_time: int | None = None,
        end_time: int | None = None,
    ) -> list[UserWithdraw]:
        return await self.get_latest_ledgers(
            "withdraw", address, start_time, end_time
        )  # type: ignore

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
        self,
        address: str | None = None,
        is_frontend: bool = False,
        dex: str = "",
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

    async def get_user_dex_abstraction(self, address: str | None) -> bool:
        if not address:
            address = self.address
        return await self.info.get_user_dex_abstraction(address)

    async def get_user_abstraction_state(
        self, address: str | None = None
    ) -> str:
        if not address:
            address = self.address
        return await self.info.get_user_abstraction_state(address)

    # Exchange API
    async def _round_sz_px(self, coin: str, sz: float, px: float):
        asset = await self.get_coin_asset(coin)
        is_spot = asset >= SPOT_OFFSET and asset < PERP_DEX_OFFSET
        sz_decimals = await self.get_coin_sz_decimals(coin)
        px_decimals = (6 if not is_spot else 8) - sz_decimals
        return asset, round_float(sz, sz_decimals), round_px(px, px_decimals)

    async def place_order(
        self,
        coin: str,
        is_buy: bool,
        sz: float,
        px: float,
        is_market: bool = True,
        *,
        ro: bool = False,
        order_type: OrderType = LimitOrder.IOC.value,  # type: ignore
        cloid: Cloid | None = None,
        slippage: float = 0.05,  # Default slippage is 5%
        builder: OrderBuilder | None = None,
    ):
        if is_market:
            mid_px = await self.get_mid_price(coin)
            slippage_factor = (1 + slippage) if is_buy else (1 - slippage)
            px = mid_px * slippage_factor
            # Market order is an aggressive Limit Order IoC
            order_type = LimitOrder.IOC.value  # type: ignore

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
        slippage: float = 0.05,  # Default slippage is 5%
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
        self,
        orders: BatchPlaceOrderRequest,
        slippage: float = 0.05,  # Default slippage is 5%
    ):
        reqs = []
        dexs = list(set(get_coin_dex(o["coin"]) for o in orders))
        all_mids = await self.get_dexs_mids(dexs)
        order_type = LimitOrder.IOC.value
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

    async def set_referrer_code(self, code: str):
        action = {"type": "setReferrer", "code": code}
        return await self.exchange.post_action(action)

    @private_key_required
    async def create_sub_account(self, name: str):
        action = {"type": "createSubAccount", "name": name}
        return await self.exchange.post_action(action)

    @private_key_required
    async def usd_transfer(self, amount: float, dest: str):
        nonce = get_timestamp_ms()
        action = {
            "type": "usdSend",
            "amount": round_token_amount(amount, 2),
            "destination": dest,
            "time": nonce,
        }
        is_mainnet = self.base_url == MAINNET_API_URL
        sig = sign_usd_transfer_action(self.account, action, is_mainnet)
        return await self.exchange.post_action_with_sig(action, sig, nonce)

    @private_key_required
    async def spot_transfer(self, coin: str, amount: float, dest: str):
        token_info = await self.get_token_info(coin)
        token_name = token_info["name"]
        token_id = token_info["tokenId"]
        wei_decimals = token_info["weiDecimals"]
        token = f"{token_name}:{token_id}"
        nonce = get_timestamp_ms()
        action = {
            "type": "spotSend",
            "destination": dest,
            "token": token,
            "amount": round_token_amount(amount, wei_decimals),
            "time": nonce,
        }
        sig = sign_spot_transfer_action(self.account, action, self.is_mainnet)
        return await self.exchange.post_action_with_sig(action, sig, nonce)

    @private_key_required
    async def initiate_withdrawal(self, amount: float):
        nonce = get_timestamp_ms()
        action = {
            "type": "withdraw3",
            "amount": round_token_amount(amount, 2),
            "time": nonce,
            "destination": self.address,
        }
        sig = sign_withdraw_action(self.account, action, self.is_mainnet)
        return await self.exchange.post_action_with_sig(action, sig, nonce)

    @private_key_required
    async def usd_class_transfer(self, amount: float, to_perp: bool = False):
        nonce = get_timestamp_ms()
        action = {
            "type": "usdClassTransfer",
            "amount": round_token_amount(amount, 2),
            "toPerp": to_perp,
            "nonce": nonce,
        }
        sig = sign_usd_class_transfer_action(
            self.account, action, self.base_url == MAINNET_API_URL
        )
        return await self.exchange.post_action_with_sig(action, sig, nonce)

    @private_key_required
    async def send_asset(
        self,
        coin: str,
        amount: float,
        dest: str,
        source_dex: str,
        dest_dex: str,
        sub_account: str = "",
    ):
        token_info = await self.get_token_info(coin)
        token_name = token_info["name"]
        token_id = token_info["tokenId"]
        wei_decimals = token_info["weiDecimals"]
        token = f"{token_name}:{token_id}"
        nonce = get_timestamp_ms()
        action = {
            "type": "sendAsset",
            "token": token,
            "amount": round_token_amount(amount, wei_decimals),
            "destination": dest,
            "sourceDex": source_dex,
            "destinationDex": dest_dex,
            "fromSubAccount": sub_account,
            "nonce": nonce,
        }
        sig = sign_send_asset_action(self.account, action, self.is_mainnet)
        return await self.exchange.post_action_with_sig(action, sig, nonce)

    @private_key_required
    async def staking_deposit(self, amount: float):
        amount_in_wei = int(math.floor(amount * HYPE_FACTOR))
        nonce = get_timestamp_ms()
        action = {"type": "cDeposit", "wei": amount_in_wei, "nonce": nonce}
        sig = sign_staking_deposit_action(self.account, action, self.is_mainnet)
        return await self.exchange.post_action_with_sig(action, sig, nonce)

    @private_key_required
    async def staking_withdraw(self, amount: float):
        amount_in_wei = int(math.floor(amount * HYPE_FACTOR))
        nonce = get_timestamp_ms()
        action = {"type": "cWithdraw", "wei": amount_in_wei, "nonce": nonce}
        sig = sign_staking_withdraw_action(
            self.account, action, self.is_mainnet
        )
        return await self.exchange.post_action_with_sig(action, sig, nonce)

    @private_key_required
    async def token_delegate(
        self, validator: str, amount: float, is_undelegate: bool = False
    ):
        # HYPE decimals is 8
        amount_in_wei = int(math.floor(amount * HYPE_FACTOR))
        nonce = get_timestamp_ms()
        action = {
            "type": "tokenDelegate",
            "validator": validator,
            "wei": amount_in_wei,
            "isUndelegate": is_undelegate,
            "nonce": nonce,
        }
        sig = sign_token_delegate_action(self.account, action, self.is_mainnet)
        return await self.exchange.post_action_with_sig(action, sig, nonce)

    @private_key_required
    async def vault_transfer(
        self, vault: str, amount: float, is_deposit: bool = True
    ):
        usd_amount = int(math.floor(amount * USD_FACTOR))
        action = {
            "type": "vaultTransfer",
            "vaultAddress": vault,
            "isDeposit": is_deposit,
            "usd": usd_amount,
        }
        return await self.exchange.post_action(action)

    async def approve_agent(self, agent: str, name: str | None = None):
        nonce = get_timestamp_ms()
        action = {
            "type": "approveAgent",
            "agentAddress": agent,
            "agentName": name or "",
            "nonce": nonce,
        }
        sig = sign_approve_agent_action(self.account, action, self.is_mainnet)
        if name is None:
            del action["agentName"]

        return await self.exchange.post_action_with_sig(action, sig, nonce)

    async def approve_builder_fee(self, max_fee_rate: float, builder: str):
        nonce = get_timestamp_ms()
        action = {
            "type": "approveBuilderFee",
            "maxFeeRate": f"{max_fee_rate:.3%}",
            "builder": builder,
            "nonce": nonce,
        }
        sig = sign_approve_builder_fee_action(
            self.account, action, self.is_mainnet
        )
        return await self.exchange.post_action_with_sig(action, sig, nonce)

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

    async def convert_to_multi_sig_user(self, users: list[str], threshold: int):
        nonce = get_timestamp_ms()
        signers = {"authorizedUsers": sorted(users), "threshold": threshold}
        action = {
            "type": "convertToMultiSigUser",
            "signers": signers,
            "nonce": nonce,
        }
        sig = sign_convert_to_multi_sig_user_action(
            self.account, action, self.is_mainnet
        )
        return await self.exchange.post_action_with_sig(action, sig, nonce)

    async def reserve_request_weight(self, weight: int):
        action = {"type": "reserveRequestWeight", "weight": weight}
        return await self.exchange.post_action(action, expires=self.expires)

    async def use_big_block(self, enable: bool):
        action = {"type": "evmUserModify", "usingBigBlocks": enable}
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

    async def user_dex_abstraction(
        self, user: str | None = None, enabled: bool = True
    ):
        nonce = get_timestamp_ms()
        if user is None:
            user = self.address
        action = {
            "type": "userDexAbstraction",
            "user": user.lower(),
            "enabled": enabled,
            "nonce": nonce,
        }
        sig = sign_user_dex_abstraction_action(
            self.account, action, self.is_mainnet
        )
        return await self.exchange.post_action_with_sig(action, sig, nonce)

    async def agent_enable_dex_abstraction(self):
        action = {"type": "agentEnableDexAbstraction"}
        return await self.exchange.post_action(
            action, vault=self.vault, expires=self.expires
        )

    async def user_set_abstraction(
        self, abstraction: Abstraction, address: str | None = None
    ):
        if address is None:
            address = self.address

        nonce = get_timestamp_ms()
        action = {
            "type": "userSetAbstraction",
            "user": address.lower(),
            "abstraction": abstraction,
            "nonce": nonce,
        }
        sig = sign_user_set_abstraction_action(
            self.account, action, self.is_mainnet
        )

        return await self.exchange.post_action_with_sig(action, sig, nonce)


AsyncHyper = AsyncHyperliquid
