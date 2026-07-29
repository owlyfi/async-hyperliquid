import math
from dataclasses import dataclass
from typing import Literal, NotRequired, TypeAlias, TypedDict

from .common import Cloid, Side, TimeInForce, TriggerKind


def _require_positive_finite(name: str, value: float) -> None:
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be finite and greater than zero")


def _require_non_negative(name: str, value: int) -> None:
    if value < 0:
        raise ValueError(f"{name} must not be negative")


@dataclass(frozen=True, slots=True)
class LimitOrder:
    coin: str
    side: Side
    size: float
    price: float
    time_in_force: TimeInForce = TimeInForce.GTC
    reduce_only: bool = False
    client_order_id: Cloid | None = None

    def __post_init__(self) -> None:
        _require_positive_finite("size", self.size)
        _require_positive_finite("price", self.price)


@dataclass(frozen=True, slots=True)
class TriggerOrder:
    coin: str
    side: Side
    size: float
    price: float
    trigger_price: float
    trigger_kind: TriggerKind
    is_market: bool = False
    reduce_only: bool = False
    client_order_id: Cloid | None = None

    def __post_init__(self) -> None:
        _require_positive_finite("size", self.size)
        _require_positive_finite("price", self.price)
        _require_positive_finite("trigger_price", self.trigger_price)


@dataclass(frozen=True, slots=True)
class MarketOrder:
    coin: str
    side: Side
    size: float
    slippage: float = 0.05
    reduce_only: bool = False
    client_order_id: Cloid | None = None

    def __post_init__(self) -> None:
        _require_positive_finite("size", self.size)
        if not math.isfinite(self.slippage) or not 0 <= self.slippage <= 1:
            raise ValueError("slippage must be finite and between zero and one")


@dataclass(frozen=True, slots=True)
class CancelOrder:
    coin: str
    order_id: int

    def __post_init__(self) -> None:
        _require_non_negative("order_id", self.order_id)


@dataclass(frozen=True, slots=True)
class CancelByCloid:
    coin: str
    client_order_id: Cloid


@dataclass(frozen=True, slots=True)
class ModifyOrder:
    order_id: int | Cloid
    order: LimitOrder | TriggerOrder

    def __post_init__(self) -> None:
        if isinstance(self.order_id, int):
            _require_non_negative("order_id", self.order_id)


@dataclass(frozen=True, slots=True)
class BuilderFee:
    address: str
    fee_tenths_bps: int

    def __post_init__(self) -> None:
        _require_non_negative("fee_tenths_bps", self.fee_tenths_bps)


class Signature(TypedDict):
    r: str
    s: str
    v: int


class EncodedLimitOptions(TypedDict):
    tif: Literal["Alo", "Ioc", "Gtc"]


class EncodedLimitType(TypedDict):
    limit: EncodedLimitOptions


class EncodedTriggerOptions(TypedDict):
    isMarket: bool
    triggerPx: str
    tpsl: Literal["tp", "sl"]


class EncodedTriggerType(TypedDict):
    trigger: EncodedTriggerOptions


EncodedOrderType: TypeAlias = EncodedLimitType | EncodedTriggerType


class EncodedOrder(TypedDict):
    a: int
    b: bool
    p: str
    s: str
    r: bool
    t: EncodedOrderType
    c: NotRequired[str]


class EncodedBuilderFee(TypedDict):
    b: str
    f: int


class OrderAction(TypedDict):
    type: Literal["order"]
    orders: list[EncodedOrder]
    grouping: Literal["na", "normalTpsl", "positionTpsl"]
    builder: NotRequired[EncodedBuilderFee]


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
    type: Literal["batchModify"]
    modifies: list[EncodedModify]


ExchangeAction: TypeAlias = (
    OrderAction | CancelAction | CancelByCloidAction | ModifyAction
)


class ActionEnvelope(TypedDict):
    action: ExchangeAction
    nonce: int
    signature: Signature
    vaultAddress: NotRequired[str]
    expiresAfter: NotRequired[int]


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


OrderStatus: TypeAlias = RestingStatus | FilledStatus | ErrorStatus
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
ActionResponse: TypeAlias = (
    PlaceOrderSuccess | CancelSuccess | DefaultSuccess | ExchangeError
)
