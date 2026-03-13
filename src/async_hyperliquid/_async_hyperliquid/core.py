import asyncio

from aiohttp import ClientSession, ClientTimeout
from eth_account import Account
from eth_account.signers.local import LocalAccount
from hl_web3.exchange import Exchange as EVMExchange
from hl_web3.info import Info as EVMInfo
from hl_web3.utils.constants import HL_RPC_URL, HL_TESTNET_RPC_URL

from async_hyperliquid.async_api import AsyncAPI
from async_hyperliquid.exchange import ExchangeAPI
from async_hyperliquid.info import InfoAPI
from async_hyperliquid.utils.constants import (
    MAINNET_API_URL,
    PERP_DEX_OFFSET,
    SPOT_OFFSET,
    TESTNET_API_URL,
)
from async_hyperliquid.utils.types import (
    Metas,
    PerpMeta,
    SpotMeta,
    SpotTokenMeta,
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

        self.vault = vault
        self.expires: int | None = None
        self.perp_dexs = perp_dexs

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
        total_tokens = len(meta["tokens"])
        for info in meta["universe"]:
            asset = info["index"] + SPOT_OFFSET
            asset_name = info["name"]

            self.coin_assets[asset_name] = asset
            self.coin_names[asset_name] = asset_name

            base, quote = info["tokens"]
            if base >= total_tokens or quote >= total_tokens:
                print("Unreconized token index for: ", info)
                continue

            base_info = meta["tokens"][base]
            base_name = base_info["name"]
            quote_name = meta["tokens"][quote]["name"]
            name = f"{base_name}/{quote_name}"
            if name not in self.coin_names:
                self.coin_names[name] = asset_name

            self.asset_sz_decimals[asset] = base_info["szDecimals"]
            self.spot_tokens[asset_name] = meta["tokens"][base]

    def _update_coin_symbols(self) -> None:
        self.coin_symbols = {
            v: k for k, v in self.coin_names.items() if not k.startswith("@")
        }

    async def init_metas(self) -> None:
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
