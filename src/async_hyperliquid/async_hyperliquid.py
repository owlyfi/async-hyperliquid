import asyncio
import math
import re
import warnings
from typing import Literal

from aiohttp import ClientSession, ClientTimeout
from eth_account import Account
from eth_account.signers.local import LocalAccount
from hl_web3.exchange import Exchange as EVMExchange
from hl_web3.info import Info as EVMInfo
from hl_web3.utils.constants import HL_RPC_URL, HL_TESTNET_RPC_URL

from async_hyperliquid._async_hyperliquid import AsyncHyperliquidActionsClient
from async_hyperliquid._async_hyperliquid import actions as _actions_module
from async_hyperliquid._async_hyperliquid import info as _info_module
from async_hyperliquid._async_hyperliquid import orders as _orders_module
from async_hyperliquid.async_api import AsyncAPI
from async_hyperliquid.exchange import ExchangeAPI
from async_hyperliquid.info import InfoAPI
from async_hyperliquid.utils.constants import (
    HYPE_FACTOR,
    MAINNET_API_URL,
    ONE_HOUR_MS,
    PERP_DEX_OFFSET,
    SPOT_OFFSET,
    TESTNET_API_URL,
    USD_FACTOR,
)
from async_hyperliquid.utils.decorators import private_key_required
from async_hyperliquid.utils.miscs import (
    get_coin_dex,
    get_timestamp_ms,
    round_float,
    round_px,
    round_token_amount,
)
from async_hyperliquid.utils.signing import (
    encode_order,
    orders_to_action,
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
from async_hyperliquid.utils.types import (
    Abstraction,
    AccountState,
    AgentAbstraction,
    BatchCancelRequest,
    BatchPlaceOrderRequest,
    ClearinghouseState,
    Cloid,
    GroupOptions,
    LimitTif,
    Metas,
    OrderBuilder,
    OrderType,
    OrderWithStatus,
    PerpMeta,
    PlaceOrderRequest,
    Portfolio,
    Position,
    SpotClearinghouseState,
    SpotMeta,
    SpotTokenMeta,
    UserDeposit,
    UserNonFundingDelta,
    UserOpenOrders,
    UserSetAbstraction,
    UserTransfer,
    UserWithdraw,
    limit_order_type,
)


def _bind_compat_function(module: object, name: str) -> None:
    def _compat(*args: object, **kwargs: object) -> object:
        return globals()[name](*args, **kwargs)

    setattr(module, name, _compat)


class AsyncHyperliquid(AsyncHyperliquidActionsClient):
    """Public client facade with the historical import path intact."""


AsyncHyper = AsyncHyperliquid

# This module intentionally remains a compatibility shim for the historical
# `async_hyperliquid.async_hyperliquid` import path. Keep legacy re-exports and
# patch-propagation hooks here so downstream imports and monkeypatches do not
# break when internal implementation modules are reorganized.
for _module, _names in (
    (_info_module, ("get_coin_dex", "get_timestamp_ms")),
    (
        _orders_module,
        (
            "encode_order",
            "get_coin_dex",
            "limit_order_type",
            "orders_to_action",
            "round_float",
            "round_px",
        ),
    ),
    (
        _actions_module,
        (
            "get_timestamp_ms",
            "round_token_amount",
            "sign_approve_agent_action",
            "sign_approve_builder_fee_action",
            "sign_convert_to_multi_sig_user_action",
            "sign_send_asset_action",
            "sign_spot_transfer_action",
            "sign_staking_deposit_action",
            "sign_staking_withdraw_action",
            "sign_token_delegate_action",
            "sign_usd_class_transfer_action",
            "sign_usd_transfer_action",
            "sign_user_dex_abstraction_action",
            "sign_user_set_abstraction_action",
            "sign_withdraw_action",
        ),
    ),
):
    for _name in _names:
        _bind_compat_function(_module, _name)

__all__ = [
    "Abstraction",
    "Account",
    "AccountState",
    "AgentAbstraction",
    "AsyncAPI",
    "AsyncHyper",
    "AsyncHyperliquid",
    "BatchCancelRequest",
    "BatchPlaceOrderRequest",
    "ClearinghouseState",
    "ClientSession",
    "ClientTimeout",
    "Cloid",
    "EVMExchange",
    "EVMInfo",
    "ExchangeAPI",
    "GroupOptions",
    "HL_RPC_URL",
    "HL_TESTNET_RPC_URL",
    "HYPE_FACTOR",
    "InfoAPI",
    "LimitTif",
    "Literal",
    "LocalAccount",
    "MAINNET_API_URL",
    "Metas",
    "ONE_HOUR_MS",
    "OrderBuilder",
    "OrderType",
    "OrderWithStatus",
    "PERP_DEX_OFFSET",
    "PerpMeta",
    "PlaceOrderRequest",
    "Portfolio",
    "Position",
    "SPOT_OFFSET",
    "SpotClearinghouseState",
    "SpotMeta",
    "SpotTokenMeta",
    "TESTNET_API_URL",
    "USD_FACTOR",
    "UserDeposit",
    "UserNonFundingDelta",
    "UserOpenOrders",
    "UserSetAbstraction",
    "UserTransfer",
    "UserWithdraw",
    "asyncio",
    "encode_order",
    "get_coin_dex",
    "get_timestamp_ms",
    "limit_order_type",
    "math",
    "orders_to_action",
    "private_key_required",
    "re",
    "round_float",
    "round_px",
    "round_token_amount",
    "sign_approve_agent_action",
    "sign_approve_builder_fee_action",
    "sign_convert_to_multi_sig_user_action",
    "sign_send_asset_action",
    "sign_spot_transfer_action",
    "sign_staking_deposit_action",
    "sign_staking_withdraw_action",
    "sign_token_delegate_action",
    "sign_usd_class_transfer_action",
    "sign_usd_transfer_action",
    "sign_user_dex_abstraction_action",
    "sign_user_set_abstraction_action",
    "sign_withdraw_action",
    "warnings",
]
