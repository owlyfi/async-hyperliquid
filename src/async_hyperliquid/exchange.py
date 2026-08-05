import json
import logging
import math
from collections.abc import Sequence
from time import time_ns
from typing import Literal, cast, overload

from eth_account.signers.local import LocalAccount
from eth_utils import is_address, to_normalized_address

from ._internal.encoding import _wire_float
from ._internal.exchange import (
    ResponseType,
    amount_in_units,
    exact_signed_units,
    expect_action_response,
    format_token_amount,
    positive_wire_amount,
)
from ._internal.http import _HttpTransport, _validate_endpoint_url
from ._internal.signing import (
    _APPROVE_AGENT_SPEC,
    _APPROVE_BUILDER_FEE_SPEC,
    _CONVERT_TO_MULTI_SIG_USER_SPEC,
    _SEND_ASSET_SPEC,
    _SEND_TO_EVM_WITH_DATA_SPEC,
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
    _sign_user_action,
    sign_exchange_action,
)
from .errors import HttpError, IndeterminateActionError, ProtocolError
from .types import (
    AgentAbstraction,
    Builder,
    JsonObject,
    Network,
    OrderGrouping,
    UserAbstraction,
)
from .types.exchange import (
    ActionEnvelope,
    ActionResponse,
    AgentEnableDexAbstractionAction,
    AgentSendAssetAction,
    AgentSetAbstractionAction,
    ApproveAgentAction,
    AuthorizeAqav2RoleAction,
    BatchModifyAction,
    CancelAction,
    CancelByCloidAction,
    CancelOrderResponse,
    CancelTwapResponse,
    ClaimRewardsAction,
    CreateSubAccountAction,
    DefaultActionResponse,
    EncodedBuilder,
    EncodedCancel,
    EncodedCancelByCloid,
    EncodedModify,
    EncodedOrder,
    EncodedTwapDetails,
    EncodedTwapOrder,
    EvmUserModifyAction,
    ExchangeAction,
    Hip3LiquidatorTransferAction,
    MergeOutcomeAction,
    MergeQuestionAction,
    ModifyAction,
    NegateOutcomeAction,
    NoopAction,
    OrderAction,
    PlaceOrderResponse,
    PlaceTwapResponse,
    ReserveRequestWeightAction,
    ScheduleCancelAction,
    SetReferrerAction,
    Signature,
    SplitOutcomeAction,
    TwapCancelAction,
    TwapOrderAction,
    UpdateIsolatedMarginAction,
    UpdateLeverageAction,
    ValidatorL1StreamAction,
    VaultTransferAction,
)


logger = logging.getLogger(__name__)

__all__ = ["ExchangeClient"]

_HYPE_DECIMALS = 8
_USD_DECIMALS = 6
_ROOT_SCOPED_ACTIONS = frozenset(
    {
        "createSubAccount",
        "evmUserModify",
        "reserveRequestWeight",
        "setReferrer",
        "vaultTransfer",
    }
)
_ACTION_SCOPED_TRANSFERS = frozenset({"sendAsset", "usdClassTransfer"})


class ExchangeClient:
    """Transport-bound signed action client owned by ``AsyncHyperliquid``."""

    __slots__ = (
        "_account",
        "_account_address",
        "_exchange_url",
        "_last_nonce",
        "_network",
        "_transport",
        "_vault_address",
    )

    _transport: _HttpTransport
    _account: LocalAccount
    _account_address: str
    _vault_address: str | None
    _network: Network
    _exchange_url: str
    _last_nonce: int

    def __init__(
        self,
        transport: _HttpTransport,
        account: LocalAccount,
        *,
        account_address: str,
        vault_address: str | None,
        network: Network,
        exchange_url: str | None = None,
    ) -> None:
        if not is_address(account_address):
            raise ValueError("account_address must be a 20-byte hex address")
        if vault_address is not None and not is_address(vault_address):
            raise ValueError("vault_address must be a 20-byte hex address")

        self._transport = transport
        self._account = account
        self._account_address = to_normalized_address(account_address)
        self._vault_address = (
            None if vault_address is None else to_normalized_address(vault_address)
        )
        self._network = network
        self._exchange_url = _validate_endpoint_url(
            network.exchange_url if exchange_url is None else exchange_url
        )
        self._last_nonce = 0

    @property
    def exchange_url(self) -> str:
        return self._exchange_url

    @property
    def execution_address(self) -> str:
        return self._vault_address or self._account_address

    def _next_nonce(self) -> int:
        self._last_nonce = max(time_ns() // 1_000_000, self._last_nonce + 1)
        return self._last_nonce

    async def _submit_orders(
        self,
        orders: Sequence[EncodedOrder],
        *,
        grouping: OrderGrouping = OrderGrouping.NA,
        builder: Builder | None = None,
        expires_after: int | None = None,
    ) -> PlaceOrderResponse:
        encoded = list(orders)
        if not encoded:
            raise ValueError("orders must not be empty")
        action: OrderAction = {
            "type": "order",
            "orders": encoded,
            "grouping": grouping.value,
        }
        if builder is not None:
            action["builder"] = EncodedBuilder(
                b=builder.address.lower(), f=builder.fee_tenths_bps
            )
        return await self._submit_action(action, "order", expires_after=expires_after)

    async def _submit_cancels(
        self, cancels: Sequence[EncodedCancel], *, expires_after: int | None = None
    ) -> CancelOrderResponse:
        encoded = list(cancels)
        if not encoded:
            raise ValueError("orders must not be empty")
        action = CancelAction(type="cancel", cancels=encoded)
        return await self._submit_action(action, "cancel", expires_after=expires_after)

    async def _submit_cloid_cancels(
        self,
        cancels: Sequence[EncodedCancelByCloid],
        *,
        expires_after: int | None = None,
    ) -> CancelOrderResponse:
        encoded = list(cancels)
        if not encoded:
            raise ValueError("orders must not be empty")
        action = CancelByCloidAction(type="cancelByCloid", cancels=encoded)
        return await self._submit_action(action, "cancel", expires_after=expires_after)

    async def _post_envelope(
        self,
        action: ExchangeAction,
        signature: Signature,
        nonce: int,
        expected_type: ResponseType,
        *,
        vault_address: str | None,
        expires_after: int | None = None,
    ) -> ActionResponse:
        envelope: ActionEnvelope = {
            "action": action,
            "nonce": nonce,
            "signature": signature,
            "vaultAddress": vault_address,
            "expiresAfter": expires_after,
        }
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
            return expect_action_response(value, expected_type)
        except (TimeoutError, HttpError, ProtocolError):
            raise IndeterminateActionError(str(action_type), nonce) from None

    @overload
    async def _submit_action(
        self,
        action: OrderAction | ModifyAction | BatchModifyAction,
        expected_type: Literal["order"],
        *,
        expires_after: int | None = None,
        nonce: int | None = None,
    ) -> PlaceOrderResponse: ...

    @overload
    async def _submit_action(
        self,
        action: CancelAction | CancelByCloidAction,
        expected_type: Literal["cancel"],
        *,
        expires_after: int | None = None,
        nonce: int | None = None,
    ) -> CancelOrderResponse: ...

    @overload
    async def _submit_action(
        self,
        action: TwapOrderAction,
        expected_type: Literal["twapOrder"],
        *,
        expires_after: int | None = None,
        nonce: int | None = None,
    ) -> PlaceTwapResponse: ...

    @overload
    async def _submit_action(
        self,
        action: TwapCancelAction,
        expected_type: Literal["twapCancel"],
        *,
        expires_after: int | None = None,
        nonce: int | None = None,
    ) -> CancelTwapResponse: ...

    @overload
    async def _submit_action(
        self,
        action: ExchangeAction,
        expected_type: Literal["default"],
        *,
        expires_after: int | None = None,
        nonce: int | None = None,
    ) -> DefaultActionResponse: ...

    async def _submit_action(
        self,
        action: ExchangeAction,
        expected_type: ResponseType,
        *,
        expires_after: int | None = None,
        nonce: int | None = None,
    ) -> ActionResponse:
        if nonce is None:
            nonce = self._next_nonce()
        action_type = cast(str, cast(JsonObject, action)["type"])
        vault_address = (
            None if action_type in _ROOT_SCOPED_ACTIONS else self._vault_address
        )
        signature = sign_exchange_action(
            self._account,
            cast(JsonObject, action),
            vault_address,
            nonce,
            self._network.signature_source,
            expires_after,
        )
        return await self._post_envelope(
            action,
            signature,
            nonce,
            expected_type,
            vault_address=vault_address,
            expires_after=expires_after,
        )

    async def _submit_user_action(
        self, action: JsonObject, spec: _UserSigningSpec, nonce: int
    ) -> DefaultActionResponse:
        wire_action, signature = _sign_user_action(
            self._account, action, spec, self._network
        )
        vault_address = (
            None if action["type"] in _ACTION_SCOPED_TRANSFERS else self._vault_address
        )
        return cast(
            DefaultActionResponse,
            await self._post_envelope(
                cast(ExchangeAction, wire_action),
                signature,
                nonce,
                "default",
                vault_address=vault_address,
            ),
        )

    async def _submit_modify(
        self, modify: EncodedModify, *, expires_after: int | None = None
    ) -> DefaultActionResponse:
        action = ModifyAction(type="modify", oid=modify["oid"], order=modify["order"])
        return await self._submit_action(action, "default", expires_after=expires_after)

    async def _submit_modifies(
        self, modifies: Sequence[EncodedModify], *, expires_after: int | None = None
    ) -> PlaceOrderResponse:
        encoded = list(modifies)
        if not encoded:
            raise ValueError("orders must not be empty")
        action = BatchModifyAction(type="batchModify", modifies=encoded)
        return await self._submit_action(action, "order", expires_after=expires_after)

    async def schedule_cancel(
        self, cancel_at: int | None = None, *, expires_after: int | None = None
    ) -> DefaultActionResponse:
        action = ScheduleCancelAction(type="scheduleCancel")
        if cancel_at is not None:
            if cancel_at < 0:
                raise ValueError("cancel_at must not be negative")
            action["time"] = cancel_at
        return await self._submit_action(action, "default", expires_after=expires_after)

    async def _update_leverage(
        self,
        asset: int,
        leverage: int,
        *,
        is_cross: bool = True,
        expires_after: int | None = None,
    ) -> DefaultActionResponse:
        action = UpdateLeverageAction(
            type="updateLeverage", asset=asset, isCross=is_cross, leverage=leverage
        )
        return await self._submit_action(action, "default", expires_after=expires_after)

    async def _update_isolated_margin(
        self, asset: int, amount: float, *, expires_after: int | None = None
    ) -> DefaultActionResponse:
        action = UpdateIsolatedMarginAction(
            type="updateIsolatedMargin",
            asset=asset,
            isBuy=True,
            ntli=exact_signed_units(amount, _USD_DECIMALS),
        )
        return await self._submit_action(action, "default", expires_after=expires_after)

    async def _submit_twap(
        self,
        twap: EncodedTwapOrder,
        *,
        details: EncodedTwapDetails | None = None,
        expires_after: int | None = None,
    ) -> PlaceTwapResponse:
        action = TwapOrderAction(type="twapOrder", twap=twap)
        if details is not None:
            action["details"] = details
        return await self._submit_action(
            action, "twapOrder", expires_after=expires_after
        )

    async def _submit_twap_cancel(
        self, asset: int, twap_id: int, *, expires_after: int | None = None
    ) -> CancelTwapResponse:
        action = TwapCancelAction(type="twapCancel", a=asset, t=twap_id)
        return await self._submit_action(
            action, "twapCancel", expires_after=expires_after
        )

    async def set_referrer_code(
        self, code: str, *, expires_after: int | None = None
    ) -> DefaultActionResponse:
        action = SetReferrerAction(type="setReferrer", code=code)
        return await self._submit_action(action, "default", expires_after=expires_after)

    async def create_sub_account(
        self, name: str, *, expires_after: int | None = None
    ) -> DefaultActionResponse:
        action = CreateSubAccountAction(type="createSubAccount", name=name)
        return await self._submit_action(action, "default", expires_after=expires_after)

    async def vault_transfer(
        self,
        vault_address: str,
        amount: float,
        *,
        is_deposit: bool = True,
        expires_after: int | None = None,
    ) -> DefaultActionResponse:
        action = VaultTransferAction(
            type="vaultTransfer",
            vaultAddress=vault_address,
            isDeposit=is_deposit,
            usd=amount_in_units(amount, _USD_DECIMALS),
        )
        return await self._submit_action(action, "default", expires_after=expires_after)

    async def hip3_liquidator_transfer(
        self,
        dex: str,
        amount: float,
        *,
        is_deposit: bool = True,
        expires_after: int | None = None,
    ) -> DefaultActionResponse:
        notional = exact_signed_units(amount, _USD_DECIMALS)
        if notional <= 0 or notional % 1_000_000_000:
            raise ValueError("amount must be a positive multiple of 1000 quote tokens")
        action = Hip3LiquidatorTransferAction(
            type="hip3LiquidatorTransfer", dex=dex, ntl=notional, isDeposit=is_deposit
        )
        return await self._submit_action(action, "default", expires_after=expires_after)

    async def reserve_request_weight(
        self, weight: int, *, expires_after: int | None = None
    ) -> DefaultActionResponse:
        if weight < 0:
            raise ValueError("weight must not be negative")
        action = ReserveRequestWeightAction(type="reserveRequestWeight", weight=weight)
        return await self._submit_action(action, "default", expires_after=expires_after)

    async def noop(
        self, nonce: int | None = None, *, expires_after: int | None = None
    ) -> DefaultActionResponse:
        if nonce is None:
            nonce = self._next_nonce()
        elif nonce < 0:
            raise ValueError("nonce must not be negative")
        else:
            self._last_nonce = max(self._last_nonce, nonce)
        return await self._submit_action(
            NoopAction(type="noop"), "default", expires_after=expires_after, nonce=nonce
        )

    async def use_big_blocks(
        self, enabled: bool, *, expires_after: int | None = None
    ) -> DefaultActionResponse:
        action = EvmUserModifyAction(type="evmUserModify", usingBigBlocks=enabled)
        return await self._submit_action(action, "default", expires_after=expires_after)

    async def usd_transfer(
        self, amount: float, destination: str
    ) -> DefaultActionResponse:
        nonce = self._next_nonce()
        action: JsonObject = {
            "type": "usdSend",
            "amount": format_token_amount(amount, 2),
            "destination": destination,
            "time": nonce,
        }
        return await self._submit_user_action(action, _USD_SEND_SPEC, nonce)

    async def _spot_transfer(
        self, token: str, wei_decimals: int, amount: float, destination: str
    ) -> DefaultActionResponse:
        nonce = self._next_nonce()
        action: JsonObject = {
            "type": "spotSend",
            "destination": destination,
            "token": token,
            "amount": format_token_amount(amount, wei_decimals),
            "time": nonce,
        }
        return await self._submit_user_action(action, _SPOT_SEND_SPEC, nonce)

    async def withdraw(
        self, amount: float, *, destination: str | None = None
    ) -> DefaultActionResponse:
        nonce = self._next_nonce()
        action: JsonObject = {
            "type": "withdraw3",
            "amount": format_token_amount(amount, 2),
            "time": nonce,
            "destination": destination or self._account_address,
        }
        return await self._submit_user_action(action, _WITHDRAW_SPEC, nonce)

    async def usd_class_transfer(
        self, amount: float, *, to_perp: bool = False
    ) -> DefaultActionResponse:
        nonce = self._next_nonce()
        formatted_amount = format_token_amount(amount, 2)
        if self._vault_address is not None:
            formatted_amount += f" subaccount:{self._vault_address}"
        action: JsonObject = {
            "type": "usdClassTransfer",
            "amount": formatted_amount,
            "toPerp": to_perp,
            "nonce": nonce,
        }
        return await self._submit_user_action(action, _USD_CLASS_TRANSFER_SPEC, nonce)

    async def _send_asset(
        self,
        token: str,
        wei_decimals: int,
        amount: float,
        destination: str,
        *,
        source_dex: str,
        destination_dex: str,
    ) -> DefaultActionResponse:
        nonce = self._next_nonce()
        action: JsonObject = {
            "type": "sendAsset",
            "token": token,
            "amount": format_token_amount(amount, wei_decimals),
            "destination": destination,
            "sourceDex": source_dex,
            "destinationDex": destination_dex,
            "fromSubAccount": self._vault_address or "",
            "nonce": nonce,
        }
        return await self._submit_user_action(action, _SEND_ASSET_SPEC, nonce)

    async def _agent_send_asset(
        self,
        token: str,
        wei_decimals: int,
        amount: float,
        destination: str,
        *,
        source_dex: str,
        destination_dex: str,
        expires_after: int | None = None,
    ) -> DefaultActionResponse:
        nonce = self._next_nonce()
        action = AgentSendAssetAction(
            type="agentSendAsset",
            destination=destination,
            sourceDex=source_dex,
            destinationDex=destination_dex,
            token=token,
            amount=format_token_amount(amount, wei_decimals),
            fromSubAccount=self._vault_address or "",
            nonce=nonce,
        )
        return await self._submit_action(
            action, "default", expires_after=expires_after, nonce=nonce
        )

    async def _send_to_evm_with_data(
        self,
        token: str,
        wei_decimals: int,
        amount: float,
        destination_recipient: str,
        *,
        source_dex: str,
        address_encoding: Literal["hex", "base58"],
        destination_chain_id: int,
        gas_limit: int,
        data: str,
    ) -> DefaultActionResponse:
        nonce = self._next_nonce()
        action: JsonObject = {
            "type": "sendToEvmWithData",
            "token": token,
            "amount": format_token_amount(amount, wei_decimals),
            "sourceDex": source_dex,
            "destinationRecipient": destination_recipient,
            "addressEncoding": address_encoding,
            "destinationChainId": destination_chain_id,
            "gasLimit": gas_limit,
            "data": data,
            "nonce": nonce,
        }
        return await self._submit_user_action(
            action, _SEND_TO_EVM_WITH_DATA_SPEC, nonce
        )

    async def staking_deposit(self, amount: float) -> DefaultActionResponse:
        nonce = self._next_nonce()
        action: JsonObject = {
            "type": "cDeposit",
            "wei": amount_in_units(amount, _HYPE_DECIMALS),
            "nonce": nonce,
        }
        return await self._submit_user_action(action, _STAKING_TRANSFER_SPEC, nonce)

    async def staking_withdraw(self, amount: float) -> DefaultActionResponse:
        nonce = self._next_nonce()
        action: JsonObject = {
            "type": "cWithdraw",
            "wei": amount_in_units(amount, _HYPE_DECIMALS),
            "nonce": nonce,
        }
        return await self._submit_user_action(action, _STAKING_WITHDRAW_SPEC, nonce)

    async def token_delegate(
        self, validator: str, amount: float, *, undelegate: bool = False
    ) -> DefaultActionResponse:
        nonce = self._next_nonce()
        action: JsonObject = {
            "type": "tokenDelegate",
            "validator": validator,
            "wei": amount_in_units(amount, _HYPE_DECIMALS),
            "isUndelegate": undelegate,
            "nonce": nonce,
        }
        return await self._submit_user_action(action, _TOKEN_DELEGATE_SPEC, nonce)

    async def approve_agent(
        self, agent_address: str, *, name: str | None = None
    ) -> DefaultActionResponse:
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
        return cast(
            DefaultActionResponse,
            await self._post_envelope(
                cast(ApproveAgentAction, wire_action),
                signature,
                nonce,
                "default",
                vault_address=self._vault_address,
            ),
        )

    async def approve_builder_fee(
        self, builder_address: str, max_fee_rate: float
    ) -> DefaultActionResponse:
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
    ) -> DefaultActionResponse:
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

    async def user_dex_abstraction(self, *, enabled: bool) -> DefaultActionResponse:
        nonce = self._next_nonce()
        action: JsonObject = {
            "type": "userDexAbstraction",
            "user": self._vault_address or self._account_address,
            "enabled": enabled,
            "nonce": nonce,
        }
        return await self._submit_user_action(action, _USER_DEX_ABSTRACTION_SPEC, nonce)

    async def user_set_abstraction(
        self, abstraction: UserAbstraction
    ) -> DefaultActionResponse:
        nonce = self._next_nonce()
        action: JsonObject = {
            "type": "userSetAbstraction",
            "user": self._vault_address or self._account_address,
            "abstraction": abstraction.value,
            "nonce": nonce,
        }
        return await self._submit_user_action(action, _USER_SET_ABSTRACTION_SPEC, nonce)

    async def agent_enable_dex_abstraction(
        self, *, expires_after: int | None = None
    ) -> DefaultActionResponse:
        action = AgentEnableDexAbstractionAction(type="agentEnableDexAbstraction")
        return await self._submit_action(action, "default", expires_after=expires_after)

    async def agent_set_abstraction(
        self, abstraction: AgentAbstraction, *, expires_after: int | None = None
    ) -> DefaultActionResponse:
        action = AgentSetAbstractionAction(
            type="agentSetAbstraction", abstraction=abstraction.value
        )
        return await self._submit_action(action, "default", expires_after=expires_after)

    async def split_outcome(
        self, outcome: int, amount: float, *, expires_after: int | None = None
    ) -> DefaultActionResponse:
        if outcome < 0:
            raise ValueError("outcome must not be negative")
        action = SplitOutcomeAction(
            type="userOutcome",
            splitOutcome={"outcome": outcome, "amount": positive_wire_amount(amount)},
        )
        return await self._submit_action(action, "default", expires_after=expires_after)

    async def merge_outcome(
        self,
        outcome: int,
        amount: float | None = None,
        *,
        expires_after: int | None = None,
    ) -> DefaultActionResponse:
        if outcome < 0:
            raise ValueError("outcome must not be negative")
        action = MergeOutcomeAction(
            type="userOutcome",
            mergeOutcome={
                "outcome": outcome,
                "amount": None if amount is None else positive_wire_amount(amount),
            },
        )
        return await self._submit_action(action, "default", expires_after=expires_after)

    async def merge_question(
        self,
        question: int,
        amount: float | None = None,
        *,
        expires_after: int | None = None,
    ) -> DefaultActionResponse:
        if question < 0:
            raise ValueError("question must not be negative")
        action = MergeQuestionAction(
            type="userOutcome",
            mergeQuestion={
                "question": question,
                "amount": None if amount is None else positive_wire_amount(amount),
            },
        )
        return await self._submit_action(action, "default", expires_after=expires_after)

    async def negate_outcome(
        self,
        question: int,
        outcome: int,
        amount: float,
        *,
        expires_after: int | None = None,
    ) -> DefaultActionResponse:
        if question < 0 or outcome < 0:
            raise ValueError("question and outcome must not be negative")
        action = NegateOutcomeAction(
            type="userOutcome",
            negateOutcome={
                "question": question,
                "outcome": outcome,
                "amount": positive_wire_amount(amount),
            },
        )
        return await self._submit_action(action, "default", expires_after=expires_after)

    async def vote_risk_free_rate(
        self, rate: float, *, expires_after: int | None = None
    ) -> DefaultActionResponse:
        if not math.isfinite(rate) or rate < 0:
            raise ValueError("rate must be finite and non-negative")
        action = ValidatorL1StreamAction(
            type="validatorL1Stream", riskFreeRate=_wire_float(rate)
        )
        return await self._submit_action(action, "default", expires_after=expires_after)

    async def authorize_aqav2_role(
        self,
        token: int,
        role: Literal["technical", "treasury"],
        *,
        expires_after: int | None = None,
    ) -> DefaultActionResponse:
        if token < 0:
            raise ValueError("token must not be negative")
        action = AuthorizeAqav2RoleAction(
            type="authorizeAqav2Role", token=token, role=role
        )
        return await self._submit_action(action, "default", expires_after=expires_after)

    async def claim_rewards(
        self, *, expires_after: int | None = None
    ) -> DefaultActionResponse:
        return await self._submit_action(
            ClaimRewardsAction(type="claimRewards"),
            "default",
            expires_after=expires_after,
        )
