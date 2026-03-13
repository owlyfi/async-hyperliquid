import math
import re
import warnings

from async_hyperliquid.utils.constants import (
    HYPE_FACTOR,
    MAINNET_API_URL,
    USD_FACTOR,
)
from async_hyperliquid.utils.decorators import private_key_required
from async_hyperliquid.utils.miscs import get_timestamp_ms, round_token_amount
from async_hyperliquid.utils.signing import (
    sign_approve_agent_action,
    sign_approve_builder_fee_action,
    sign_convert_to_multi_sig_user_action,
    sign_send_asset_action,
    sign_spot_transfer_action,
    sign_staking_deposit_action,
    sign_staking_withdraw_action,
    sign_token_delegate_action,
    sign_usd_class_transfer_action,
    sign_usd_transfer_action,
    sign_user_dex_abstraction_action,
    sign_user_set_abstraction_action,
    sign_withdraw_action,
)
from async_hyperliquid.utils.types import AgentAbstraction, UserSetAbstraction

from .orders import AsyncHyperliquidOrdersClient


class AsyncHyperliquidActionsClient(AsyncHyperliquidOrdersClient):
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

    async def user_dex_abstraction(
        self, user: str | None = None, enabled: bool = True
    ):
        warnings.warn(
            "user_dex_abstraction is deprecated and may be removed in a "
            "future release.",
            DeprecationWarning,
            stacklevel=2,
        )
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

    async def user_set_abstraction(
        self, abstraction: UserSetAbstraction, user: str | None = None
    ):
        nonce = get_timestamp_ms()
        if user is None:
            user = self.address
        if re.fullmatch(r"0x[a-fA-F0-9]{40}", user) is None:
            raise ValueError(
                f"user must be a 42-char hex address, got: {user!r}"
            )
        action = {
            "type": "userSetAbstraction",
            "user": user.lower(),
            "abstraction": abstraction,
            "nonce": nonce,
        }
        sig = sign_user_set_abstraction_action(
            self.account, action, self.is_mainnet
        )
        return await self.exchange.post_action_with_sig(action, sig, nonce)

    async def agent_enable_dex_abstraction(self):
        warnings.warn(
            "agent_enable_dex_abstraction is deprecated and may be removed "
            "in a future release.",
            DeprecationWarning,
            stacklevel=2,
        )
        action = {"type": "agentEnableDexAbstraction"}
        return await self.exchange.post_action(
            action, vault=self.vault, expires=self.expires
        )

    async def agent_set_abstraction(self, abstraction: AgentAbstraction):
        action = {"type": "agentSetAbstraction", "abstraction": abstraction}
        return await self.exchange.post_action(
            action, vault=self.vault, expires=self.expires
        )
