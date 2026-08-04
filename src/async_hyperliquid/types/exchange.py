from dataclasses import dataclass
from typing import Literal, NotRequired, TypeAlias, TypedDict

from .common import Cloid, TimeInForce, TriggerKind


def _require_non_negative(name: str, value: int) -> None:
    if value < 0:
        raise ValueError(f"{name} must not be negative")


class LimitOrderOption(TypedDict):
    tif: TimeInForce


class LimitOrderType(TypedDict):
    limit: LimitOrderOption


class TriggerOrderOption(TypedDict):
    isMarket: bool
    triggerPx: str
    tpsl: Literal["tp", "sl"]


class TriggerOrderType(TypedDict):
    trigger: TriggerOrderOption


OrderType: TypeAlias = LimitOrderType | TriggerOrderType


def limit_order_type(tif: TimeInForce) -> LimitOrderType:
    return {"limit": {"tif": tif}}


def trigger_order_type(
    *, is_market: bool, trigger_px: str, tpsl: TriggerKind
) -> TriggerOrderType:
    return {
        "trigger": {"isMarket": is_market, "triggerPx": trigger_px, "tpsl": tpsl.value}
    }


class BaseOrderRequest(TypedDict):
    coin: str
    is_buy: bool
    sz: float
    px: float
    cloid: NotRequired[Cloid | None]


class PlaceOrderRequest(BaseOrderRequest):
    is_market: bool
    ro: NotRequired[bool]
    order_type: NotRequired[OrderType | None]
    slippage: NotRequired[float]


class ModifyOrderRequest(BaseOrderRequest):
    oid: int | Cloid
    ro: NotRequired[bool]
    order_type: NotRequired[OrderType | None]


@dataclass(frozen=True, slots=True)
class CancelOrder:
    coin: str
    oid: int

    def __post_init__(self) -> None:
        _require_non_negative("oid", self.oid)


@dataclass(frozen=True, slots=True)
class CancelByCloid:
    coin: str
    cloid: Cloid


@dataclass(frozen=True, slots=True)
class Builder:
    address: str
    fee_tenths_bps: int

    def __post_init__(self) -> None:
        _require_non_negative("fee_tenths_bps", self.fee_tenths_bps)


class Signature(TypedDict):
    r: str
    s: str
    v: int


class EncodedLimitOrderOption(TypedDict):
    tif: Literal["Alo", "Ioc", "Gtc"]


class EncodedLimitOrderType(TypedDict):
    limit: EncodedLimitOrderOption


class EncodedTriggerOrderOption(TypedDict):
    isMarket: bool
    triggerPx: str
    tpsl: Literal["tp", "sl"]


class EncodedTriggerOrderType(TypedDict):
    trigger: EncodedTriggerOrderOption


EncodedOrderType: TypeAlias = EncodedLimitOrderType | EncodedTriggerOrderType


class EncodedOrder(TypedDict):
    a: int
    b: bool
    p: str
    s: str
    r: bool
    t: EncodedOrderType
    c: NotRequired[str]


class EncodedBuilder(TypedDict):
    b: str
    f: int


class OrderAction(TypedDict):
    type: Literal["order"]
    orders: list[EncodedOrder]
    grouping: Literal["na", "normalTpsl", "positionTpsl"]
    builder: NotRequired[EncodedBuilder]


class EncodedCancel(TypedDict):
    a: int
    o: int


class CancelAction(TypedDict):
    type: Literal["cancel"]
    cancels: list[EncodedCancel]


class EncodedCancelByCloid(TypedDict):
    asset: int
    cloid: str


class CancelByCloidAction(TypedDict):
    type: Literal["cancelByCloid"]
    cancels: list[EncodedCancelByCloid]


class EncodedModify(TypedDict):
    oid: int | str
    order: EncodedOrder


class ModifyAction(TypedDict):
    type: Literal["modify"]
    oid: int | str
    order: EncodedOrder


class BatchModifyAction(TypedDict):
    type: Literal["batchModify"]
    modifies: list[EncodedModify]


class ScheduleCancelAction(TypedDict):
    type: Literal["scheduleCancel"]
    time: NotRequired[int]


class UpdateLeverageAction(TypedDict):
    type: Literal["updateLeverage"]
    asset: int
    isCross: bool
    leverage: int


class UpdateIsolatedMarginAction(TypedDict):
    type: Literal["updateIsolatedMargin"]
    asset: int
    isBuy: bool
    ntli: int


class EncodedTwapOrder(TypedDict):
    a: int
    b: bool
    s: str
    r: bool
    m: int
    t: bool


class TwapOrderAction(TypedDict):
    type: Literal["twapOrder"]
    twap: EncodedTwapOrder


class TwapCancelAction(TypedDict):
    type: Literal["twapCancel"]
    a: int
    t: int


class SetReferrerAction(TypedDict):
    type: Literal["setReferrer"]
    code: str


class CreateSubAccountAction(TypedDict):
    type: Literal["createSubAccount"]
    name: str


class VaultTransferAction(TypedDict):
    type: Literal["vaultTransfer"]
    vaultAddress: str
    isDeposit: bool
    usd: int


class ReserveRequestWeightAction(TypedDict):
    type: Literal["reserveRequestWeight"]
    weight: int


class EvmUserModifyAction(TypedDict):
    type: Literal["evmUserModify"]
    usingBigBlocks: bool


class AgentEnableDexAbstractionAction(TypedDict):
    type: Literal["agentEnableDexAbstraction"]


class AgentSetAbstractionAction(TypedDict):
    type: Literal["agentSetAbstraction"]
    abstraction: Literal["i", "u", "p"]


class AgentSendAssetAction(TypedDict):
    type: Literal["agentSendAsset"]
    destination: str
    sourceDex: str
    destinationDex: str
    token: str
    amount: str
    fromSubAccount: str
    nonce: int


class Hip3LiquidatorTransferAction(TypedDict):
    type: Literal["hip3LiquidatorTransfer"]
    dex: str
    ntl: int
    isDeposit: bool


class NoopAction(TypedDict):
    type: Literal["noop"]


class SplitOutcome(TypedDict):
    outcome: int
    amount: str


class SplitOutcomeAction(TypedDict):
    type: Literal["userOutcome"]
    splitOutcome: SplitOutcome


class MergeOutcome(TypedDict):
    outcome: int
    amount: str | None


class MergeOutcomeAction(TypedDict):
    type: Literal["userOutcome"]
    mergeOutcome: MergeOutcome


class MergeQuestion(TypedDict):
    question: int
    amount: str | None


class MergeQuestionAction(TypedDict):
    type: Literal["userOutcome"]
    mergeQuestion: MergeQuestion


class NegateOutcome(TypedDict):
    question: int
    outcome: int
    amount: str


class NegateOutcomeAction(TypedDict):
    type: Literal["userOutcome"]
    negateOutcome: NegateOutcome


class ValidatorL1StreamAction(TypedDict):
    type: Literal["validatorL1Stream"]
    riskFreeRate: str


class AuthorizeAqav2RoleAction(TypedDict):
    type: Literal["authorizeAqav2Role"]
    token: int
    role: Literal["technical", "treasury"]


class ClaimRewardsAction(TypedDict):
    type: Literal["claimRewards"]


class UserSignedFields(TypedDict):
    signatureChainId: Literal["0x66eee"]
    hyperliquidChain: Literal["Mainnet", "Testnet"]


class UsdSendAction(UserSignedFields):
    type: Literal["usdSend"]
    amount: str
    destination: str
    time: int


class SpotSendAction(UserSignedFields):
    type: Literal["spotSend"]
    destination: str
    token: str
    amount: str
    time: int


class WithdrawAction(UserSignedFields):
    type: Literal["withdraw3"]
    amount: str
    time: int
    destination: str


class UsdClassTransferAction(UserSignedFields):
    type: Literal["usdClassTransfer"]
    amount: str
    toPerp: bool
    nonce: int


class SendAssetAction(UserSignedFields):
    type: Literal["sendAsset"]
    token: str
    amount: str
    destination: str
    sourceDex: str
    destinationDex: str
    fromSubAccount: str
    nonce: int


class SendToEvmWithDataAction(UserSignedFields):
    type: Literal["sendToEvmWithData"]
    token: str
    amount: str
    sourceDex: str
    destinationRecipient: str
    addressEncoding: Literal["hex", "base58"]
    destinationChainId: int
    gasLimit: int
    data: str
    nonce: int


class StakingDepositAction(UserSignedFields):
    type: Literal["cDeposit"]
    wei: int
    nonce: int


class StakingWithdrawAction(UserSignedFields):
    type: Literal["cWithdraw"]
    wei: int
    nonce: int


class TokenDelegateAction(UserSignedFields):
    type: Literal["tokenDelegate"]
    validator: str
    wei: int
    isUndelegate: bool
    nonce: int


class ApproveAgentAction(UserSignedFields):
    type: Literal["approveAgent"]
    agentAddress: str
    agentName: NotRequired[str]
    nonce: int


class ApproveBuilderFeeAction(UserSignedFields):
    type: Literal["approveBuilderFee"]
    maxFeeRate: str
    builder: str
    nonce: int


class ConvertToMultiSigUserAction(UserSignedFields):
    type: Literal["convertToMultiSigUser"]
    signers: str
    nonce: int


class UserDexAbstractionAction(UserSignedFields):
    type: Literal["userDexAbstraction"]
    user: str
    enabled: bool
    nonce: int


class UserSetAbstractionAction(UserSignedFields):
    type: Literal["userSetAbstraction"]
    user: str
    abstraction: Literal["disabled", "unifiedAccount", "portfolioMargin"]
    nonce: int


ExchangeAction: TypeAlias = (
    OrderAction
    | CancelAction
    | CancelByCloidAction
    | ModifyAction
    | BatchModifyAction
    | ScheduleCancelAction
    | UpdateLeverageAction
    | UpdateIsolatedMarginAction
    | TwapOrderAction
    | TwapCancelAction
    | SetReferrerAction
    | CreateSubAccountAction
    | VaultTransferAction
    | ReserveRequestWeightAction
    | EvmUserModifyAction
    | AgentEnableDexAbstractionAction
    | AgentSetAbstractionAction
    | AgentSendAssetAction
    | Hip3LiquidatorTransferAction
    | NoopAction
    | SplitOutcomeAction
    | MergeOutcomeAction
    | MergeQuestionAction
    | NegateOutcomeAction
    | ValidatorL1StreamAction
    | AuthorizeAqav2RoleAction
    | ClaimRewardsAction
    | UsdSendAction
    | SpotSendAction
    | WithdrawAction
    | UsdClassTransferAction
    | SendAssetAction
    | SendToEvmWithDataAction
    | StakingDepositAction
    | StakingWithdrawAction
    | TokenDelegateAction
    | ApproveAgentAction
    | ApproveBuilderFeeAction
    | ConvertToMultiSigUserAction
    | UserDexAbstractionAction
    | UserSetAbstractionAction
)


class ActionEnvelope(TypedDict):
    action: ExchangeAction
    nonce: int
    signature: Signature
    vaultAddress: str | None
    expiresAfter: int | None


class RestingOrderStatus(TypedDict):
    oid: int


class RestingStatus(TypedDict):
    resting: RestingOrderStatus


class FilledOrderStatus(TypedDict):
    totalSz: str
    avgPx: str
    oid: int


class FilledStatus(TypedDict):
    filled: FilledOrderStatus


class ErrorStatus(TypedDict):
    error: str


DeferredOrderStatus: TypeAlias = Literal["waitingForFill", "waitingForTrigger"]
OrderStatus: TypeAlias = (
    RestingStatus | FilledStatus | ErrorStatus | DeferredOrderStatus
)
CancelStatus: TypeAlias = Literal["success"] | ErrorStatus


class OrderResponseData(TypedDict):
    statuses: list[OrderStatus]


class OrderResponse(TypedDict):
    type: Literal["order"]
    data: OrderResponseData


class PlaceOrderSuccess(TypedDict):
    status: Literal["ok"]
    response: OrderResponse


class CancelResponseData(TypedDict):
    statuses: list[CancelStatus]


class CancelResponse(TypedDict):
    type: Literal["cancel"]
    data: CancelResponseData


class CancelSuccess(TypedDict):
    status: Literal["ok"]
    response: CancelResponse


class TwapRunningData(TypedDict):
    twapId: int


class TwapRunningStatus(TypedDict):
    running: TwapRunningData


TwapOrderStatus: TypeAlias = TwapRunningStatus | ErrorStatus


class TwapOrderResponseData(TypedDict):
    status: TwapOrderStatus


class TwapOrderResponse(TypedDict):
    type: Literal["twapOrder"]
    data: TwapOrderResponseData


class TwapOrderSuccess(TypedDict):
    status: Literal["ok"]
    response: TwapOrderResponse


class TwapCancelResponseData(TypedDict):
    status: CancelStatus


class TwapCancelResponse(TypedDict):
    type: Literal["twapCancel"]
    data: TwapCancelResponseData


class TwapCancelSuccess(TypedDict):
    status: Literal["ok"]
    response: TwapCancelResponse


class DefaultResponse(TypedDict):
    type: Literal["default"]


class DefaultSuccess(TypedDict):
    status: Literal["ok"]
    response: DefaultResponse


class ExchangeError(TypedDict):
    status: Literal["err"]
    response: str


PlaceOrderResponse: TypeAlias = PlaceOrderSuccess | ExchangeError
CancelOrderResponse: TypeAlias = CancelSuccess | ExchangeError
PlaceTwapResponse: TypeAlias = TwapOrderSuccess | ExchangeError
CancelTwapResponse: TypeAlias = TwapCancelSuccess | ExchangeError
DefaultActionResponse: TypeAlias = DefaultSuccess | ExchangeError
ActionResponse: TypeAlias = (
    PlaceOrderSuccess
    | CancelSuccess
    | TwapOrderSuccess
    | TwapCancelSuccess
    | DefaultActionResponse
)
