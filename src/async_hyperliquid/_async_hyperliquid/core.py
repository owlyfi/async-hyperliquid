import asyncio
import warnings
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
    _meta_init_lock: asyncio.Lock
    _meta_init_task: asyncio.Task[None] | None
    _metas_initialized: bool

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
        self._meta_init_lock = asyncio.Lock()
        self._meta_init_task = None
        self._metas_initialized = False

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

    def _init_perp_meta(
        self,
        meta: PerpMeta,
        offset: int,
        *,
        coin_assets: dict[str, int] | None = None,
        coin_names: dict[str, str] | None = None,
        asset_sz_decimals: dict[int, int] | None = None,
    ) -> None:
        coin_assets = self.coin_assets if coin_assets is None else coin_assets
        coin_names = self.coin_names if coin_names is None else coin_names
        asset_sz_decimals = (
            self.asset_sz_decimals if asset_sz_decimals is None else asset_sz_decimals
        )
        for asset, info in enumerate(meta["universe"]):
            asset += offset
            asset_name = info["name"]
            coin_assets[asset_name] = asset
            coin_names[asset_name] = asset_name
            asset_sz_decimals[asset] = info["szDecimals"]

    def _init_spot_meta(
        self,
        meta: SpotMeta,
        *,
        coin_assets: dict[str, int] | None = None,
        coin_names: dict[str, str] | None = None,
        asset_sz_decimals: dict[int, int] | None = None,
        spot_tokens: dict[str, SpotTokenMeta] | None = None,
    ) -> None:
        coin_assets = self.coin_assets if coin_assets is None else coin_assets
        coin_names = self.coin_names if coin_names is None else coin_names
        asset_sz_decimals = (
            self.asset_sz_decimals if asset_sz_decimals is None else asset_sz_decimals
        )
        spot_tokens = self.spot_tokens if spot_tokens is None else spot_tokens
        tokens = meta["tokens"]
        total_tokens = len(tokens)
        for info in meta["universe"]:
            asset = info["index"] + SPOT_OFFSET
            asset_name = info["name"]

            coin_assets[asset_name] = asset
            coin_names[asset_name] = asset_name

            base, quote = info["tokens"]
            if not 0 <= base < total_tokens or not 0 <= quote < total_tokens:
                continue

            base_info = tokens[base]
            base_name = base_info["name"]
            quote_info = tokens[quote]
            quote_name = quote_info["name"]
            name = f"{base_name}/{quote_name}"
            coin_names.setdefault(name, asset_name)
            coin_names.setdefault(quote_name, quote_name)

            asset_sz_decimals[asset] = base_info["szDecimals"]
            spot_tokens[asset_name] = base_info
            spot_tokens.setdefault(quote_name, quote_info)

    def _build_coin_symbols(self, coin_names: dict[str, str]) -> dict[str, str]:
        return {v: k for k, v in coin_names.items() if not k.startswith("@")}

    def _infer_perp_meta_dex(self, meta: PerpMeta) -> str | None:
        universe = meta["universe"]
        if not universe:
            return None

        first_name = universe[0]["name"]
        if ":" not in first_name:
            return ""

        return first_name.partition(":")[0]

    def _map_all_perp_metas_by_dex(
        self, all_perp_metas: list[PerpMeta]
    ) -> dict[str, PerpMeta]:
        metas_by_dex: dict[str, PerpMeta] = {}
        for meta in all_perp_metas:
            dex = self._infer_perp_meta_dex(meta)
            if dex is None:
                continue

            if dex in metas_by_dex:
                raise ValueError(
                    f"allPerpMetas returned duplicate metadata for dex '{dex}'"
                )

            metas_by_dex[dex] = meta

        return metas_by_dex

    def _format_perp_dex_name(self, dex: str) -> str:
        return "<base>" if dex == "" else dex

    def _get_perp_meta_offsets_by_dex(self, all_dex_names: list[str]) -> dict[str, int]:
        if not all_dex_names or all_dex_names[0] != "":
            raise ValueError(
                "perpDexs must start with the base perp dex; refusing metadata refresh because DEX offsets are no longer trustworthy"
            )

        seen: set[str] = set()
        duplicates: list[str] = []
        for name in all_dex_names:
            if name in seen:
                duplicates.append(name)
            seen.add(name)

        if duplicates:
            raise ValueError(
                "perpDexs returned duplicate perp dex names; refusing metadata refresh because DEX offsets are no longer trustworthy: "
                + ", ".join(self._format_perp_dex_name(name) for name in duplicates)
            )

        return {
            name: 0 if idx == 0 else PERP_DEX_OFFSET + (idx - 1) * 10000
            for idx, name in enumerate(all_dex_names)
        }

    def _get_meta_init_lock(self) -> asyncio.Lock:
        lock = getattr(self, "_meta_init_lock", None)
        if lock is None:
            lock = asyncio.Lock()
            self._meta_init_lock = lock
        return lock

    def _lookup_cached_coin_name(self, coin: str) -> str | None:
        coin_names = getattr(self, "coin_names", {})
        if coin in coin_names:
            return coin_names[coin]

        coin_assets = getattr(self, "coin_assets", {})
        if coin in coin_assets:
            return coin

        return None

    def _lookup_cached_asset_id(self, coin: str) -> int | None:
        coin_assets = getattr(self, "coin_assets", {})
        asset = coin_assets.get(coin)
        if asset is not None:
            return asset

        coin_name = getattr(self, "coin_names", {}).get(coin)
        if coin_name is None:
            return None

        return coin_assets.get(coin_name)

    def _lookup_cached_asset(self, coin: str) -> tuple[str, int] | None:
        asset = self._lookup_cached_asset_id(coin)
        if asset is None:
            return None

        coin_name = self._lookup_cached_coin_name(coin)
        if coin_name is None:
            return None

        return coin_name, asset

    async def experimental_get_all_perp_metas_by_dex(self) -> dict[str, PerpMeta]:
        all_perp_metas = await self.info.get_all_perp_metas()
        return self._map_all_perp_metas_by_dex(all_perp_metas)

    async def experimental_get_configured_perp_metas(self) -> dict[str, PerpMeta]:
        all_perp_metas_by_dex = await self.experimental_get_all_perp_metas_by_dex()
        return {
            dex: meta
            for dex in self.perp_dexs
            if (meta := all_perp_metas_by_dex.get(dex)) is not None
        }

    async def experimental_get_all_metas(self) -> Metas:
        all_perp_metas, spot_meta = await asyncio.gather(
            self.info.get_all_perp_metas(), self.info.get_spot_meta()
        )

        all_perp_metas_by_dex = self._map_all_perp_metas_by_dex(all_perp_metas)
        perp_meta = all_perp_metas_by_dex.get("")
        if perp_meta is None:
            raise ValueError("allPerpMetas missing base perp meta")

        dex_metas = {
            dex: meta for dex, meta in all_perp_metas_by_dex.items() if dex != ""
        }
        return {"perp": perp_meta, "spot": spot_meta, "dexs": dex_metas}

    async def _refresh_metas(self) -> None:
        # TODO: Add HIP-4 outcome meta initialization from the spot info
        # `outcomeMeta` endpoint once outcomes move beyond testnet-only rollout.
        # Outcome asset IDs do not follow the current perp/spot offset scheme:
        # `encoding = 10 * outcome + side`, coin names use `#{encoding}`, token
        # names use `+{encoding}`, and `asset_id = 100_000_000 + encoding`, so
        # this path will need dedicated outcome mappings instead of reusing the
        # existing perp/spot logic.
        all_dex_names, all_perp_metas, spot_meta = await asyncio.gather(
            self.get_all_dex_name(),
            self.info.get_all_perp_metas(),
            self.info.get_spot_meta(),
        )
        all_perp_metas_by_dex = self._map_all_perp_metas_by_dex(all_perp_metas)
        dex_offsets_by_name = self._get_perp_meta_offsets_by_dex(all_dex_names)

        coin_assets: dict[str, int] = {}
        coin_names: dict[str, str] = {}
        asset_sz_decimals: dict[int, int] = {}
        spot_tokens: dict[str, SpotTokenMeta] = {}

        missing_aggregate_dexs: list[tuple[str, int]] = []
        missing_dex_list_dexs: list[str] = []
        meta = all_perp_metas_by_dex.get("")
        if meta is None:
            missing_aggregate_dexs.append(("", 0))
        else:
            self._init_perp_meta(
                meta,
                0,
                coin_assets=coin_assets,
                coin_names=coin_names,
                asset_sz_decimals=asset_sz_decimals,
            )
        self._init_spot_meta(
            spot_meta,
            coin_assets=coin_assets,
            coin_names=coin_names,
            asset_sz_decimals=asset_sz_decimals,
            spot_tokens=spot_tokens,
        )

        for dex in self.perp_dexs:
            if dex == "":
                continue

            dex_asset_offset = dex_offsets_by_name.get(dex)
            if dex_asset_offset is None:
                missing_dex_list_dexs.append(dex)
                continue

            dex_meta = all_perp_metas_by_dex.get(dex)
            if dex_meta is None:
                missing_aggregate_dexs.append((dex, dex_asset_offset))
            else:
                self._init_perp_meta(
                    dex_meta,
                    dex_asset_offset,
                    coin_assets=coin_assets,
                    coin_names=coin_names,
                    asset_sz_decimals=asset_sz_decimals,
                )

        if missing_dex_list_dexs:
            raise ValueError(
                "Configured perp dexes missing from perpDexs; refusing metadata refresh because DEX offsets are no longer trustworthy: "
                + ", ".join(missing_dex_list_dexs)
            )

        if missing_aggregate_dexs:
            warnings.warn(
                "allPerpMetas missing configured perp metadata for: "
                + ", ".join(dex for dex, _ in missing_aggregate_dexs)
                + "; refetching directly by dex",
                UserWarning,
                stacklevel=2,
            )
            fallback_metas = await asyncio.gather(
                *(self.info.get_perp_meta(dex) for dex, _ in missing_aggregate_dexs)
            )
            for (dex, dex_asset_offset), fallback_meta in zip(
                missing_aggregate_dexs, fallback_metas, strict=True
            ):
                self._init_perp_meta(
                    fallback_meta,
                    dex_asset_offset,
                    coin_assets=coin_assets,
                    coin_names=coin_names,
                    asset_sz_decimals=asset_sz_decimals,
                )

        self.coin_assets = coin_assets
        self.coin_names = coin_names
        self.asset_sz_decimals = asset_sz_decimals
        self.spot_tokens = spot_tokens
        self.coin_symbols = self._build_coin_symbols(coin_names)
        self._metas_initialized = True

    async def _run_meta_refresh(self, *, only_if_missing: bool) -> None:
        if only_if_missing and getattr(self, "_metas_initialized", False):
            return

        task = getattr(self, "_meta_init_task", None)
        if task is not None and not task.done():
            await task
            return

        async with self._get_meta_init_lock():
            task = getattr(self, "_meta_init_task", None)
            if task is None or task.done():
                if only_if_missing and getattr(self, "_metas_initialized", False):
                    return
                task = asyncio.create_task(self._refresh_metas())
                self._meta_init_task = task

        try:
            await task
        finally:
            if getattr(self, "_meta_init_task", None) is task and task.done():
                self._meta_init_task = None

    async def _ensure_metas_initialized(self) -> None:
        await self._run_meta_refresh(only_if_missing=True)

    async def init_metas(self) -> None:
        await self._run_meta_refresh(only_if_missing=False)

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
        coin_name = self._lookup_cached_coin_name(coin)
        if coin_name is not None:
            return coin_name

        if getattr(self, "_metas_initialized", False):
            await self.init_metas()
        else:
            await self._ensure_metas_initialized()
        coin_name = self._lookup_cached_coin_name(coin)
        if coin_name is None:
            raise ValueError(f"Coin {coin} not found")

        return coin_name

    async def get_coin_asset(self, coin: str) -> int:
        cached = self._lookup_cached_asset(coin)
        if cached is not None:
            return cached[1]

        coin_name = await self.get_coin_name(coin)
        asset = self.coin_assets.get(coin_name)
        if asset is None:
            raise ValueError(f"Coin {coin}({coin_name}) not found")

        return asset

    async def get_coin_symbol(self, coin: str) -> str:
        coin_name = await self.get_coin_name(coin)
        return self.coin_symbols[coin_name]

    async def get_coin_sz_decimals(self, coin: str) -> int:
        cached = self._lookup_cached_asset(coin)
        if cached is not None:
            _, asset = cached
        else:
            coin_name = await self.get_coin_name(coin)
            asset = self.coin_assets.get(coin_name)
            if asset is None:
                raise ValueError(f"Coin {coin}({coin_name}) not found")
        return self.asset_sz_decimals[asset]

    async def get_token_info(self, coin: str) -> SpotTokenMeta:
        coin_name = await self.get_coin_name(coin)
        return self.spot_tokens[coin_name]

    async def get_token_id(self, coin: str) -> str:
        token_info = await self.get_token_info(coin)
        if not token_info:
            raise ValueError(f"Token {coin} not found")

        return token_info["tokenId"]
