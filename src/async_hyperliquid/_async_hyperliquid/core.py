import asyncio
from threading import Lock

from aiohttp import TCPConnector, BaseConnector, ClientSession, ClientTimeout
from eth_account import Account
from hl_web3.info import Info as EVMInfo
from hl_web3.exchange import Exchange as EVMExchange
from hl_web3.utils.constants import HL_RPC_URL, HL_TESTNET_RPC_URL
from eth_account.signers.local import LocalAccount

from async_hyperliquid.info import InfoAPI
from async_hyperliquid.exchange import ExchangeAPI
from async_hyperliquid.async_api import AsyncAPI
from async_hyperliquid.utils.miscs import get_timestamp_ms
from async_hyperliquid.utils.types import Metas, PerpMeta, SpotMeta, SpotTokenMeta
from async_hyperliquid.utils.constants import (
    SPOT_OFFSET,
    MAINNET_API_URL,
    PERP_DEX_OFFSET,
    TESTNET_API_URL,
)


class AsyncHyperliquidCore(AsyncAPI):
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
        session: ClientSession | None = None,
        timeout: ClientTimeout | None = None,
        connector: BaseConnector | None = None,
    ):
        self.address = address
        self.is_mainnet = is_mainnet
        self.account = Account.from_key(api_key)
        self._nonce_lock = Lock()
        self._last_nonce = 0
        self._owns_session = session is None
        self.session = session or self._build_session(
            timeout=timeout, connector=connector
        )
        self.base_url = MAINNET_API_URL if is_mainnet else TESTNET_API_URL
        self.info = InfoAPI(self.base_url, self.session)
        self.exchange = ExchangeAPI(
            self.account,
            self.session,
            self.base_url,
            address=self.address,
            nonce_factory=self.next_nonce,
        )

        self.coin_assets = {}
        self.coin_names = {}
        self.coin_symbols = {}
        self.asset_sz_decimals = {}
        self.spot_tokens = {}

        self.vault = vault
        self.expires: int | None = None
        self.perp_dexs = perp_dexs

        if enable_evm:
            self._init_evm_client(private_key, evm_rpc_url)

    def set_expires(self, expires: int | None) -> None:
        self.expires = expires

    def _build_session(
        self, *, timeout: ClientTimeout | None, connector: BaseConnector | None
    ) -> ClientSession:
        resolved_timeout = timeout or ClientTimeout(
            connect=3, sock_connect=3, sock_read=10
        )
        resolved_connector = connector or TCPConnector(
            ttl_dns_cache=300, enable_cleanup_closed=True
        )
        return ClientSession(timeout=resolved_timeout, connector=resolved_connector)

    def next_nonce(self) -> int:
        with self._nonce_lock:
            nonce = get_timestamp_ms()
            if nonce <= self._last_nonce:
                nonce = self._last_nonce + 1
            self._last_nonce = nonce
            return nonce

    def _init_evm_client(
        self, private_key: str | None, rpc_url: str | None = None
    ) -> None:
        if rpc_url is None:
            rpc_url = HL_RPC_URL if self.is_mainnet else HL_TESTNET_RPC_URL

        self.evm_info = EVMInfo(rpc_url)

        if private_key is None:
            if self.account.address != self.address:
                raise ValueError("EVM Exchange client can not init without private key")
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
        tokens = meta["tokens"]
        total_tokens = len(tokens)
        for info in meta["universe"]:
            asset = info["index"] + SPOT_OFFSET
            asset_name = info["name"]

            self.coin_assets[asset_name] = asset
            self.coin_names[asset_name] = asset_name

            base, quote = info["tokens"]
            if not 0 <= base < total_tokens or not 0 <= quote < total_tokens:
                continue

            base_info = tokens[base]
            base_name = base_info["name"]
            quote_info = tokens[quote]
            quote_name = quote_info["name"]
            name = f"{base_name}/{quote_name}"
            self.coin_names.setdefault(name, asset_name)
            self.coin_names.setdefault(quote_name, quote_name)

            self.asset_sz_decimals[asset] = base_info["szDecimals"]
            self.spot_tokens[asset_name] = base_info
            self.spot_tokens.setdefault(quote_name, quote_info)

    def _update_coin_symbols(self) -> None:
        self.coin_symbols = {
            v: k for k, v in self.coin_names.items() if not k.startswith("@")
        }

    async def init_metas(self) -> None:
        # TODO: Add HIP-4 outcome meta initialization from the spot info
        # `outcomeMeta` endpoint once outcomes move beyond testnet-only rollout.
        # Outcome asset IDs do not follow the current perp/spot offset scheme:
        # `encoding = 10 * outcome + side`, coin names use `#{encoding}`, token
        # names use `+{encoding}`, and `asset_id = 100_000_000 + encoding`, so
        # this path will need dedicated outcome mappings instead of reusing the
        # existing perp/spot logic.
        meta_task = self.info.get_perp_meta()
        spot_meta_task = self.info.get_spot_meta()
        all_dex_names_task = self.get_all_dex_name()

        meta, spot_meta, all_dex_names = await asyncio.gather(
            meta_task, spot_meta_task, all_dex_names_task
        )

        self._init_perp_meta(meta, 0)
        self._init_spot_meta(spot_meta)

        dex_meta_tasks = []
        dex_indices = []
        for dex in self.perp_dexs:
            if dex == "":
                continue
            try:
                idx = all_dex_names.index(dex)
            except ValueError:
                continue

            if idx > 0:
                dex_meta_tasks.append(self.info.get_perp_meta(dex))
                dex_indices.append(idx)

        if dex_meta_tasks:
            dex_metas = await asyncio.gather(*dex_meta_tasks)
            for idx, dex_meta in zip(dex_indices, dex_metas):
                dex_asset_offset = PERP_DEX_OFFSET + (idx - 1) * 10000
                self._init_perp_meta(dex_meta, dex_asset_offset)

        self._update_coin_symbols()

    async def get_metas(self, perp_only: bool = False) -> Metas:
        metas: Metas = {"perp": {}, "spot": [], "dexs": {}}  # type: ignore
        if perp_only:
            metas["perp"] = await self.info.get_perp_meta()
            return metas

        perp_meta, spot_meta = await asyncio.gather(
            self.info.get_perp_meta(), self.info.get_spot_meta()
        )
        metas["perp"] = perp_meta
        metas["spot"] = spot_meta
        return metas

    async def get_all_metas(self) -> Metas:
        dexs, perp_meta, spot_meta = await asyncio.gather(
            self.get_all_dex_name(),
            self.info.get_perp_meta(),
            self.info.get_spot_meta(),
        )
        dex_metas: dict[str, PerpMeta] = {}
        if len(dexs) > 1:
            dex_meta_results = await asyncio.gather(
                *(self.info.get_perp_meta(dex) for dex in dexs[1:])
            )
            dex_metas = {
                dex: meta for dex, meta in zip(dexs[1:], dex_meta_results, strict=True)
            }
        return {"perp": perp_meta, "spot": spot_meta, "dexs": dex_metas}

    async def get_all_dex_name(self) -> list[str]:
        names = []
        dexs = await self.info.get_perp_dexs()
        for dex in dexs:
            if dex is None:
                names.append("")
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
        if coin_name not in self.coin_assets:
            raise ValueError(f"Coin {coin}({coin_name}) not found")

        asset = self.coin_assets[coin_name]
        return self.asset_sz_decimals[asset]

    async def get_token_info(self, coin: str) -> SpotTokenMeta:
        coin_name = await self.get_coin_name(coin)
        return self.spot_tokens[coin_name]

    async def get_token_id(self, coin: str) -> str:
        token_info = await self.get_token_info(coin)
        if not token_info:
            raise ValueError(f"Token {coin} not found")

        return token_info["tokenId"]
