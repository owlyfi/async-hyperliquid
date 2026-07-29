import asyncio
import json
import logging
import math
from collections.abc import Sequence
from decimal import ROUND_DOWN, Decimal
from time import time_ns
from typing import Literal, Self, cast, overload

from eth_account.signers.local import LocalAccount

from ._http import _HttpTransport, _validate_endpoint_url
from ._signing import (
    _APPROVE_AGENT_SPEC,
    _APPROVE_BUILDER_FEE_SPEC,
    _CONVERT_TO_MULTI_SIG_USER_SPEC,
    _SEND_ASSET_SPEC,
    _SPOT_SEND_SPEC,
    _STAKING_TRANSFER_SPEC,
    _STAKING_WITHDRAW_SPEC,
    _TOKEN_DELEGATE_SPEC,
    _USD_CLASS_TRANSFER_SPEC,
    _USD_SEND_SPEC,
    _USER_DEX_ABSTRACTION_SPEC,
    _USER_SET_ABSTRACTION_SPEC,
    _WITHDRAW_SPEC,
    _UserSigningSpec,
    _round_float,
    _sign_user_action,
    _wire_float,
    encode_order,
    sign_exchange_action,
)
from .errors import HttpError, IndeterminateActionError, ProtocolError
from .info import InfoClient
from .types import (
    AgentAbstraction,
    BuilderFee,
    CancelByCloid,
    CancelOrder,
    JsonObject,
    JsonValue,
    LimitOrder,
    MarketOrder,
    ModifyOrder,
    Network,
    OrderGrouping,
    Side,
    TimeInForce,
    TriggerOrder,
    UserAbstraction,
)
from .types.exchange import (
    ActionEnvelope,
    ActionResponse,
    AgentEnableDexAbstractionAction,
    AgentSetAbstractionAction,
    ApproveAgentAction,
    CancelAction,
    CancelByCloidAction,
    CancelOrderResponse,
    CreateSubAccountAction,
    EncodedBuilderFee,
    EncodedCancel,
    EncodedCancelByCloid,
    EncodedModify,
    EncodedTwapOrder,
    EvmUserModifyAction,
    ExchangeAction,
    ModifyAction,
    OrderAction,
    PlaceOrderResponse,
    ReserveRequestWeightAction,
    ScheduleCancelAction,
    SetReferrerAction,
    Signature,
    TwapCancelAction,
    TwapOrderAction,
    UpdateIsolatedMarginAction,
    UpdateLeverageAction,
    VaultTransferAction,
)


logger = logging.getLogger(__name__)

__all__ = ["ExchangeClient"]

_HYPE_DECIMALS = 8
_USD_DECIMALS = 6
_ResponseType = Literal["order", "cancel", "default"]


def _format_token_amount(amount: float, decimals: int) -> str:
    units = _amount_in_units(amount, decimals)
    factor = 10**decimals
    whole, fraction = divmod(units, factor)
    if not decimals:
        return str(whole)
    return f"{whole}.{fraction:0{decimals}d}".rstrip("0").rstrip(".")


def _amount_in_units(amount: float, decimals: int) -> int:
    if not math.isfinite(amount) or amount <= 0:
        raise ValueError("amount must be finite and greater than zero")
    units = int(
        Decimal(str(amount)).scaleb(decimals).to_integral_value(rounding=ROUND_DOWN)
    )
    if units == 0:
        raise ValueError("amount is below the token precision")
    return units


def _exact_signed_units(amount: float, decimals: int) -> int:
    if not math.isfinite(amount):
        raise ValueError("amount must be finite")
    scaled = Decimal(str(amount)).scaleb(decimals)
    integral = scaled.to_integral_value(rounding=ROUND_DOWN)
    if scaled != integral:
        raise ValueError("amount exceeds USD precision")
    return int(integral)


def _expect_action_response(
    value: JsonValue, expected_type: _ResponseType
) -> ActionResponse:
    if not isinstance(value, dict):
        raise ProtocolError("exchange response must be an object")

    status = value.get("status")
    response = value.get("response")
    if status == "err":
        if not isinstance(response, str):
            raise ProtocolError("exchange error response must be a string")
        return cast(ActionResponse, value)

    if status != "ok" or not isinstance(response, dict):
        raise ProtocolError("exchange response has an invalid status")
    if response.get("type") != expected_type:
        raise ProtocolError("exchange response has an unexpected type")
    return cast(ActionResponse, value)


class ExchangeClient:
    """Transport-bound signed action client owned by ``AsyncHyperliquid``."""

    __slots__ = (
        "_account",
        "_account_address",
        "_exchange_url",
        "_info",
        "_last_nonce",
        "_network",
        "_perp_dexes",
        "_transport",
    )

    _transport: _HttpTransport
    _info: InfoClient
    _account: LocalAccount
    _account_address: str
    _network: Network
    _perp_dexes: tuple[str, ...]
    _exchange_url: str
    _last_nonce: int

    def __init__(self) -> None:
        raise TypeError("ExchangeClient is created by AsyncHyperliquid")

    @classmethod
    def _from_transport(
        cls,
        transport: _HttpTransport,
        info: InfoClient,
        account: LocalAccount,
        *,
        account_address: str,
        network: Network,
        exchange_url: str | None = None,
        perp_dexes: tuple[str, ...] = ("",),
    ) -> Self:
        client = cls.__new__(cls)
        client._transport = transport
        client._info = info
        client._account = account
        client._account_address = account_address
        client._network = network
        client._perp_dexes = perp_dexes
        client._exchange_url = _validate_endpoint_url(
            network.exchange_url if exchange_url is None else exchange_url
        )
        client._last_nonce = 0
        return client

    @property
    def exchange_url(self) -> str:
        return self._exchange_url

    def _next_nonce(self) -> int:
        self._last_nonce = max(time_ns() // 1_000_000, self._last_nonce + 1)
        return self._last_nonce

    async def _encode_orders(
        self,
        orders: Sequence[LimitOrder | TriggerOrder],
        *,
        grouping: OrderGrouping = OrderGrouping.NA,
        builder_fee: BuilderFee | None = None,
    ) -> OrderAction:
        commands = tuple(orders)
        if not commands:
            raise ValueError("orders must not be empty")
        market_info = await self._info._market_infos(
            tuple(order.coin for order in commands)
        )
        encoded = [
            encode_order(order, asset=asset, size_decimals=size_decimals)
            for order, (asset, size_decimals) in zip(commands, market_info, strict=True)
        ]
        action: OrderAction = {
            "type": "order",
            "orders": encoded,
            "grouping": grouping.value,
        }
        if builder_fee is not None:
            action["builder"] = EncodedBuilderFee(
                b=builder_fee.address.lower(), f=builder_fee.fee_tenths_bps
            )
        return action

    async def _encode_market_orders(
        self, orders: Sequence[MarketOrder], *, builder_fee: BuilderFee | None = None
    ) -> OrderAction:
        commands = tuple(orders)
        if not commands:
            raise ValueError("orders must not be empty")
        mids = await asyncio.gather(
            *(self._info.mid_price(order.coin) for order in commands)
        )
        limits = tuple(
            LimitOrder(
                coin=order.coin,
                side=order.side,
                size=order.size,
                price=mid
                * (
                    1 + order.slippage if order.side is Side.BUY else 1 - order.slippage
                ),
                time_in_force=TimeInForce.IOC,
                reduce_only=order.reduce_only,
                client_order_id=order.client_order_id,
            )
            for order, mid in zip(commands, mids, strict=True)
        )
        return await self._encode_orders(limits, builder_fee=builder_fee)

    async def _post_envelope(
        self,
        action: ExchangeAction,
        signature: Signature,
        nonce: int,
        expected_type: _ResponseType,
        *,
        expires_after: int | None = None,
    ) -> ActionResponse:
        envelope: ActionEnvelope = {
            "action": action,
            "nonce": nonce,
            "signature": signature,
        }
        if expires_after is not None:
            envelope["expiresAfter"] = expires_after

        action_type = cast(JsonObject, action)["type"]
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "Submitting signed action type=%s nonce=%s expires=%s",
                action_type,
                nonce,
                expires_after is not None,
            )
        try:
            value = await self._transport.post_json(
                self._exchange_url, cast(JsonObject, envelope)
            )
            return _expect_action_response(value, expected_type)
        except (TimeoutError, HttpError, ProtocolError):
            raise IndeterminateActionError(str(action_type), nonce) from None

    @overload
    async def _submit_action(
        self,
        action: OrderAction | ModifyAction,
        expected_type: Literal["order"],
        *,
        expires_after: int | None = None,
    ) -> PlaceOrderResponse: ...

    @overload
    async def _submit_action(
        self,
        action: CancelAction | CancelByCloidAction,
        expected_type: Literal["cancel"],
        *,
        expires_after: int | None = None,
    ) -> CancelOrderResponse: ...

    @overload
    async def _submit_action(
        self,
        action: ExchangeAction,
        expected_type: Literal["default"],
        *,
        expires_after: int | None = None,
    ) -> ActionResponse: ...

    async def _submit_action(
        self,
        action: ExchangeAction,
        expected_type: _ResponseType,
        *,
        expires_after: int | None = None,
    ) -> ActionResponse:
        nonce = self._next_nonce()
        signature = sign_exchange_action(
            self._account,
            cast(JsonObject, action),
            None,
            nonce,
            self._network.signature_source,
            expires_after,
        )
        return await self._post_envelope(
            action, signature, nonce, expected_type, expires_after=expires_after
        )

    async def _submit_user_action(
        self, action: JsonObject, spec: _UserSigningSpec, nonce: int
    ) -> ActionResponse:
        wire_action, signature = _sign_user_action(
            self._account, action, spec, self._network
        )
        return await self._post_envelope(
            cast(ExchangeAction, wire_action), signature, nonce, "default"
        )

    async def place_limit_order(
        self,
        order: LimitOrder,
        *,
        builder_fee: BuilderFee | None = None,
        expires_after: int | None = None,
    ) -> PlaceOrderResponse:
        action = await self._encode_orders((order,), builder_fee=builder_fee)
        return await self._submit_action(action, "order", expires_after=expires_after)

    async def place_orders(
        self,
        orders: Sequence[LimitOrder | TriggerOrder],
        *,
        grouping: OrderGrouping = OrderGrouping.NA,
        builder_fee: BuilderFee | None = None,
        expires_after: int | None = None,
    ) -> PlaceOrderResponse:
        action = await self._encode_orders(
            orders, grouping=grouping, builder_fee=builder_fee
        )
        return await self._submit_action(action, "order", expires_after=expires_after)

    async def place_market_order(
        self,
        order: MarketOrder,
        *,
        builder_fee: BuilderFee | None = None,
        expires_after: int | None = None,
    ) -> PlaceOrderResponse:
        action = await self._encode_market_orders((order,), builder_fee=builder_fee)
        return await self._submit_action(action, "order", expires_after=expires_after)

    async def cancel_orders(
        self, orders: Sequence[CancelOrder], *, expires_after: int | None = None
    ) -> CancelOrderResponse:
        commands = tuple(orders)
        if not commands:
            raise ValueError("orders must not be empty")
        market_info = await self._info._market_infos(
            tuple(order.coin for order in commands)
        )
        cancels = [
            EncodedCancel(a=asset, o=order.order_id)
            for order, (asset, _) in zip(commands, market_info, strict=True)
        ]
        action = CancelAction(type="cancel", cancels=cancels)
        return await self._submit_action(action, "cancel", expires_after=expires_after)

    async def cancel_orders_by_cloid(
        self, orders: Sequence[CancelByCloid], *, expires_after: int | None = None
    ) -> CancelOrderResponse:
        commands = tuple(orders)
        if not commands:
            raise ValueError("orders must not be empty")
        market_info = await self._info._market_infos(
            tuple(order.coin for order in commands)
        )
        cancels = [
            EncodedCancelByCloid(asset=asset, cloid=str(order.client_order_id))
            for order, (asset, _) in zip(commands, market_info, strict=True)
        ]
        action = CancelByCloidAction(type="cancelByCloid", cancels=cancels)
        return await self._submit_action(action, "cancel", expires_after=expires_after)

    async def modify_orders(
        self, orders: Sequence[ModifyOrder], *, expires_after: int | None = None
    ) -> PlaceOrderResponse:
        commands = tuple(orders)
        if not commands:
            raise ValueError("orders must not be empty")
        market_info = await self._info._market_infos(
            tuple(command.order.coin for command in commands)
        )
        modifies = [
            EncodedModify(
                oid=(
                    command.order_id
                    if isinstance(command.order_id, int)
                    else str(command.order_id)
                ),
                order=encode_order(
                    command.order, asset=asset, size_decimals=size_decimals
                ),
            )
            for command, (asset, size_decimals) in zip(
                commands, market_info, strict=True
            )
        ]
        action = ModifyAction(type="batchModify", modifies=modifies)
        return await self._submit_action(action, "order", expires_after=expires_after)

    async def schedule_cancel(
        self, cancel_at: int | None = None, *, expires_after: int | None = None
    ) -> ActionResponse:
        action = ScheduleCancelAction(type="scheduleCancel")
        if cancel_at is not None:
            if cancel_at < 0:
                raise ValueError("cancel_at must not be negative")
            action["time"] = cancel_at
        return await self._submit_action(action, "default", expires_after=expires_after)

    async def update_leverage(
        self,
        coin: str,
        leverage: int,
        *,
        is_cross: bool = True,
        expires_after: int | None = None,
    ) -> ActionResponse:
        if leverage <= 0:
            raise ValueError("leverage must be greater than zero")
        action = UpdateLeverageAction(
            type="updateLeverage",
            asset=await self._info.asset_id(coin),
            isCross=is_cross,
            leverage=leverage,
        )
        return await self._submit_action(action, "default", expires_after=expires_after)

    async def update_isolated_margin(
        self, coin: str, amount: float, *, expires_after: int | None = None
    ) -> ActionResponse:
        action = UpdateIsolatedMarginAction(
            type="updateIsolatedMargin",
            asset=await self._info.asset_id(coin),
            isBuy=True,
            ntli=_exact_signed_units(amount, _USD_DECIMALS),
        )
        return await self._submit_action(action, "default", expires_after=expires_after)

    async def place_twap(
        self,
        coin: str,
        side: Side,
        size: float,
        minutes: int,
        *,
        reduce_only: bool = False,
        randomize: bool = False,
        expires_after: int | None = None,
    ) -> ActionResponse:
        if minutes <= 0:
            raise ValueError("minutes must be greater than zero")
        if not math.isfinite(size) or size <= 0:
            raise ValueError("size must be finite and greater than zero")
        asset, size_decimals = await self._info._market_info(coin)
        encoded = EncodedTwapOrder(
            a=asset,
            b=side is Side.BUY,
            s=_wire_float(_round_float(size, size_decimals)),
            r=reduce_only,
            m=minutes,
            t=randomize,
        )
        action = TwapOrderAction(type="twapOrder", twap=encoded)
        return await self._submit_action(action, "default", expires_after=expires_after)

    async def cancel_twap(
        self, coin: str, twap_id: int, *, expires_after: int | None = None
    ) -> ActionResponse:
        if twap_id < 0:
            raise ValueError("twap_id must not be negative")
        action = TwapCancelAction(
            type="twapCancel", a=await self._info.asset_id(coin), t=twap_id
        )
        return await self._submit_action(action, "default", expires_after=expires_after)

    async def close_positions(
        self,
        coins: Sequence[str] | None = None,
        *,
        perp_dexes: tuple[str, ...] | None = None,
        slippage: float = 0.05,
        builder_fee: BuilderFee | None = None,
        expires_after: int | None = None,
    ) -> PlaceOrderResponse | None:
        requested = None if coins is None else frozenset(coins)
        if requested is not None and not requested:
            return None
        positions = await self._info.positions(
            self._account_address,
            perp_dexes=self._perp_dexes if perp_dexes is None else perp_dexes,
        )
        orders: list[MarketOrder] = []
        for position in positions:
            coin = position.get("coin")
            raw_size = position.get("szi")
            if not isinstance(coin, str) or not isinstance(raw_size, str):
                raise ProtocolError("position contains malformed coin or size")
            try:
                size = float(raw_size)
            except ValueError:
                raise ProtocolError("position contains an invalid size") from None
            if not math.isfinite(size):
                raise ProtocolError("position contains an invalid size")
            if size and (requested is None or coin in requested):
                orders.append(
                    MarketOrder(
                        coin=coin,
                        side=Side.BUY if size < 0 else Side.SELL,
                        size=abs(size),
                        slippage=slippage,
                        reduce_only=True,
                    )
                )
        if not orders:
            return None
        action = await self._encode_market_orders(orders, builder_fee=builder_fee)
        return await self._submit_action(action, "order", expires_after=expires_after)

    async def set_referrer_code(
        self, code: str, *, expires_after: int | None = None
    ) -> ActionResponse:
        action = SetReferrerAction(type="setReferrer", code=code)
        return await self._submit_action(action, "default", expires_after=expires_after)

    async def create_sub_account(
        self, name: str, *, expires_after: int | None = None
    ) -> ActionResponse:
        action = CreateSubAccountAction(type="createSubAccount", name=name)
        return await self._submit_action(action, "default", expires_after=expires_after)

    async def vault_transfer(
        self,
        vault_address: str,
        amount: float,
        *,
        is_deposit: bool = True,
        expires_after: int | None = None,
    ) -> ActionResponse:
        action = VaultTransferAction(
            type="vaultTransfer",
            vaultAddress=vault_address,
            isDeposit=is_deposit,
            usd=_amount_in_units(amount, _USD_DECIMALS),
        )
        return await self._submit_action(action, "default", expires_after=expires_after)

    async def reserve_request_weight(
        self, weight: int, *, expires_after: int | None = None
    ) -> ActionResponse:
        if weight < 0:
            raise ValueError("weight must not be negative")
        action = ReserveRequestWeightAction(type="reserveRequestWeight", weight=weight)
        return await self._submit_action(action, "default", expires_after=expires_after)

    async def use_big_blocks(
        self, enabled: bool, *, expires_after: int | None = None
    ) -> ActionResponse:
        action = EvmUserModifyAction(type="evmUserModify", usingBigBlocks=enabled)
        return await self._submit_action(action, "default", expires_after=expires_after)

    async def usd_transfer(self, amount: float, destination: str) -> ActionResponse:
        nonce = self._next_nonce()
        action: JsonObject = {
            "type": "usdSend",
            "amount": _format_token_amount(amount, 2),
            "destination": destination,
            "time": nonce,
        }
        return await self._submit_user_action(action, _USD_SEND_SPEC, nonce)

    async def spot_transfer(
        self, coin: str, amount: float, destination: str
    ) -> ActionResponse:
        token = await self._info.spot_token_metadata(coin)
        nonce = self._next_nonce()
        action: JsonObject = {
            "type": "spotSend",
            "destination": destination,
            "token": f"{token['name']}:{token['tokenId']}",
            "amount": _format_token_amount(amount, token["weiDecimals"]),
            "time": nonce,
        }
        return await self._submit_user_action(action, _SPOT_SEND_SPEC, nonce)

    async def withdraw(
        self, amount: float, *, destination: str | None = None
    ) -> ActionResponse:
        nonce = self._next_nonce()
        action: JsonObject = {
            "type": "withdraw3",
            "amount": _format_token_amount(amount, 2),
            "time": nonce,
            "destination": destination or self._account_address,
        }
        return await self._submit_user_action(action, _WITHDRAW_SPEC, nonce)

    async def usd_class_transfer(
        self, amount: float, *, to_perp: bool = False
    ) -> ActionResponse:
        nonce = self._next_nonce()
        action: JsonObject = {
            "type": "usdClassTransfer",
            "amount": _format_token_amount(amount, 2),
            "toPerp": to_perp,
            "nonce": nonce,
        }
        return await self._submit_user_action(action, _USD_CLASS_TRANSFER_SPEC, nonce)

    async def send_asset(
        self,
        coin: str,
        amount: float,
        destination: str,
        *,
        source_dex: str,
        destination_dex: str,
        from_sub_account: str = "",
    ) -> ActionResponse:
        token = await self._info.spot_token_metadata(coin)
        nonce = self._next_nonce()
        action: JsonObject = {
            "type": "sendAsset",
            "token": f"{token['name']}:{token['tokenId']}",
            "amount": _format_token_amount(amount, token["weiDecimals"]),
            "destination": destination,
            "sourceDex": source_dex,
            "destinationDex": destination_dex,
            "fromSubAccount": from_sub_account,
            "nonce": nonce,
        }
        return await self._submit_user_action(action, _SEND_ASSET_SPEC, nonce)

    async def staking_deposit(self, amount: float) -> ActionResponse:
        nonce = self._next_nonce()
        action: JsonObject = {
            "type": "cDeposit",
            "wei": _amount_in_units(amount, _HYPE_DECIMALS),
            "nonce": nonce,
        }
        return await self._submit_user_action(action, _STAKING_TRANSFER_SPEC, nonce)

    async def staking_withdraw(self, amount: float) -> ActionResponse:
        nonce = self._next_nonce()
        action: JsonObject = {
            "type": "cWithdraw",
            "wei": _amount_in_units(amount, _HYPE_DECIMALS),
            "nonce": nonce,
        }
        return await self._submit_user_action(action, _STAKING_WITHDRAW_SPEC, nonce)

    async def token_delegate(
        self, validator: str, amount: float, *, undelegate: bool = False
    ) -> ActionResponse:
        nonce = self._next_nonce()
        action: JsonObject = {
            "type": "tokenDelegate",
            "validator": validator,
            "wei": _amount_in_units(amount, _HYPE_DECIMALS),
            "isUndelegate": undelegate,
            "nonce": nonce,
        }
        return await self._submit_user_action(action, _TOKEN_DELEGATE_SPEC, nonce)

    async def approve_agent(
        self, agent_address: str, *, name: str | None = None
    ) -> ActionResponse:
        nonce = self._next_nonce()
        signing_action: JsonObject = {
            "type": "approveAgent",
            "agentAddress": agent_address,
            "agentName": name or "",
            "nonce": nonce,
        }
        wire_action, signature = _sign_user_action(
            self._account, signing_action, _APPROVE_AGENT_SPEC, self._network
        )
        if name is None:
            wire_action.pop("agentName")
        return await self._post_envelope(
            cast(ApproveAgentAction, wire_action), signature, nonce, "default"
        )

    async def approve_builder_fee(
        self, builder_address: str, max_fee_rate: float
    ) -> ActionResponse:
        if not math.isfinite(max_fee_rate) or max_fee_rate < 0:
            raise ValueError("max_fee_rate must be finite and non-negative")
        nonce = self._next_nonce()
        action: JsonObject = {
            "type": "approveBuilderFee",
            "maxFeeRate": f"{max_fee_rate:.3%}",
            "builder": builder_address,
            "nonce": nonce,
        }
        return await self._submit_user_action(action, _APPROVE_BUILDER_FEE_SPEC, nonce)

    async def convert_to_multi_sig_user(
        self, authorized_users: Sequence[str], threshold: int
    ) -> ActionResponse:
        users = sorted(authorized_users)
        if threshold <= 0 or threshold > len(users):
            raise ValueError("threshold must select at least one authorized user")
        nonce = self._next_nonce()
        action: JsonObject = {
            "type": "convertToMultiSigUser",
            "signers": json.dumps({"authorizedUsers": users, "threshold": threshold}),
            "nonce": nonce,
        }
        return await self._submit_user_action(
            action, _CONVERT_TO_MULTI_SIG_USER_SPEC, nonce
        )

    async def user_dex_abstraction(
        self, *, enabled: bool, user_address: str | None = None
    ) -> ActionResponse:
        nonce = self._next_nonce()
        action: JsonObject = {
            "type": "userDexAbstraction",
            "user": (user_address or self._account_address).lower(),
            "enabled": enabled,
            "nonce": nonce,
        }
        return await self._submit_user_action(action, _USER_DEX_ABSTRACTION_SPEC, nonce)

    async def user_set_abstraction(
        self, abstraction: UserAbstraction, *, user_address: str | None = None
    ) -> ActionResponse:
        nonce = self._next_nonce()
        action: JsonObject = {
            "type": "userSetAbstraction",
            "user": (user_address or self._account_address).lower(),
            "abstraction": abstraction.value,
            "nonce": nonce,
        }
        return await self._submit_user_action(action, _USER_SET_ABSTRACTION_SPEC, nonce)

    async def agent_enable_dex_abstraction(
        self, *, expires_after: int | None = None
    ) -> ActionResponse:
        action = AgentEnableDexAbstractionAction(type="agentEnableDexAbstraction")
        return await self._submit_action(action, "default", expires_after=expires_after)

    async def agent_set_abstraction(
        self, abstraction: AgentAbstraction, *, expires_after: int | None = None
    ) -> ActionResponse:
        action = AgentSetAbstractionAction(
            type="agentSetAbstraction", abstraction=abstraction.value
        )
        return await self._submit_action(action, "default", expires_after=expires_after)
