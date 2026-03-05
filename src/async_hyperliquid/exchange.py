import logging
from typing import Any

from aiohttp import ClientSession
from eth_account.signers.local import LocalAccount

from async_hyperliquid.async_api import AsyncAPI
from async_hyperliquid.utils.miscs import get_timestamp_ms
from async_hyperliquid.utils.types import Endpoint, SignType
from async_hyperliquid.utils.signing import sign_action, sign_multi_sig_action
from async_hyperliquid.utils.constants import (
    MAINNET_API_URL,
    SIGNATURE_CHAIN_ID,
)

logger = logging.getLogger(__name__)


class ExchangeAPI(AsyncAPI):
    def __init__(
        self,
        account: LocalAccount,
        session: ClientSession,
        base_url: str | None = None,
        address: str | None = None,
    ):
        self.account = account
        self.address = address or account.address
        self.is_mainnet = base_url == MAINNET_API_URL
        super().__init__(Endpoint.EXCHANGE, base_url, session)

    async def multi_sig(
        self,
        multi_sig_user: str,
        inner_action: dict,
        sigs: list[str],
        nonce: int,
        *,
        vault: str | None = None,
        expires: int | None = None,
    ):
        action = {
            "type": "multiSig",
            "signatureChainId": SIGNATURE_CHAIN_ID,
            "signatures": sigs,
            "payload": {
                "multiSigUser": multi_sig_user.lower(),
                "outerSigner": self.address.lower(),
                "action": inner_action,
            },
        }
        sig = sign_multi_sig_action(
            self.account, action, self.is_mainnet, vault, nonce, expires
        )
        return await self.post_action_with_sig(action, sig, nonce)

    async def post_action(
        self,
        action: Any,
        *,
        vault: str | None = None,
        expires: int | None = None,
        sign_type: SignType = SignType.SINGLE_SIG,
    ) -> Any:
        assert self.endpoint == Endpoint.EXCHANGE, (
            "only exchange endpoint supports action"
        )
        nonce = get_timestamp_ms()
        # TODO: support multi sig
        signature = sign_action(
            self.account, action, vault, nonce, self.is_mainnet, expires
        )
        return await self.post_action_with_sig(
            action, signature, nonce, vault=vault, expires=expires
        )

    async def post_action_with_sig(
        self,
        action: Any,
        sig: Any,
        nonce: int,
        *,
        vault: str | None = None,
        expires: int | None = None,
    ) -> Any:
        payload = {"action": action, "nonce": nonce, "signature": sig}
        if vault and action["type"] not in ["usdClassTransfer", "sendAsset"]:
            payload["vaultAddress"] = vault
        if expires:
            payload["expiresAfter"] = expires
        logger.debug(f"Post action payload: {payload}")
        return await self.post(payload)
