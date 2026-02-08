from enum import Enum
from typing import Any, Literal, TypedDict

from typing_extensions import NotRequired


class Cloid:
    def __init__(self, raw_cloid: str):
        self._raw_cloid: str = raw_cloid
        self._validate()

    def _validate(self) -> None:
        if not self._raw_cloid[:2] == "0x":
            raise TypeError("cloid is not a hex string")
        if not len(self._raw_cloid[2:]) == 32:
            raise TypeError("cloid is not 16 bytes")

    def __str__(self) -> str:
        return str(self._raw_cloid)

    def __repr__(self) -> str:
        return str(self._raw_cloid)

    @staticmethod
    def from_int(cloid: int) -> "Cloid":
        return Cloid(f"{cloid:#034x}")

    @staticmethod
    def from_str(cloid: str) -> "Cloid":
        return Cloid(cloid)

    def to_raw(self) -> str:
        return self._raw_cloid


class SignedAction(TypedDict):
    r: str
    s: str
    v: int


class LimitOrderOptions(TypedDict):
    tif: Literal["Alo", "Ioc", "Gtc"]


class LimitOrderType(TypedDict):
    limit: LimitOrderOptions


class LimitOrder(Enum):
    ALO = {"limit": {"tif": "Alo"}}
    IOC = {"limit": {"tif": "Ioc"}}
    GTC = {"limit": {"tif": "Gtc"}}


class TriggerOrderOptions(TypedDict):
    isMarket: bool
    triggerPx: str
    tpsl: Literal["tp", "sl"]


class TriggerOrderType(TypedDict):
    trigger: TriggerOrderOptions


OrderType = LimitOrderType | TriggerOrderType

GroupOptions = Literal["na", "normalTpsl", "positionTpsl"]


class BasicPlaceOrderRequest(TypedDict):
    is_buy: bool
    sz: float
    px: float
    ro: bool
    order_type: OrderType
    cloid: Cloid | None


class PlaceOrderRequest(BasicPlaceOrderRequest):
    asset: int


class PlaceOrdersRequest(BasicPlaceOrderRequest):
    coin: str


BatchPlaceOrderRequest = list[PlaceOrdersRequest]


class CancelOrderRequest(TypedDict):
    coin: str
    oid: int


class CancelOrderByCloid(TypedDict):
    coin: str
    cloid: Cloid | None


BatchCancelRequest = list[tuple[str, int]]


class EncodedOrder(TypedDict):
    a: int  # asset universe index
    b: bool  # is_buy
    p: str  # limit_px
    s: str  # size
    r: bool  # reduce_only
    t: OrderType  # order type
    c: NotRequired[Cloid]


class OrderBuilder(TypedDict):
    b: str  # builder address
    f: float


class OrderAction(TypedDict):
    type: Literal["order"]
    orders: list[EncodedOrder]
    grouping: Literal["na", "normalTpsl", "positionTpsl"]
    builder: NotRequired[OrderBuilder]


class Endpoint(str, Enum):
    INFO = "info"
    EXCHANGE = "exchange"


class RateLimit(TypedDict):
    cumVlm: str
    nRequestsUsed: int
    nRequestsCap: int


class Order(TypedDict):
    coin: str
    side: Literal["A", "B"]  # A: ask/sell/short, B: bid/buy/long
    limitPx: str
    sz: str
    oid: int
    timestamp: int
    origSz: str


class FrontendOrder(Order):
    triggerCondition: str
    isTrigger: bool
    triggerPx: str
    children: list["FrontendOrder"]
    isPositionTpsl: bool
    reduceOnly: bool
    orderType: str  # "Take Profit Market/Limit", "Stop Loss Market/Limit"
    tif: Literal["Gtc", "Alo"] | None
    cloid: str | None


UserOpenOrders = list[Order | FrontendOrder]


class FilledOrder(TypedDict):
    coin: str
    sz: str
    px: str
    side: Literal["A", "B"]
    time: int
    startPosition: str
    dir: str
    closedPnl: str
    hash: str
    oid: int
    crossed: bool
    fee: str
    tid: int
    feeToken: str
    builderFee: str | None


UserFills = list[FilledOrder]


class OrderStatus(str, Enum):
    OPEN = "open"
    FILLED = "filled"
    CANCELED = "canceled"
    TRIGGERED = "triggered"
    REJECTED = "rejected"
    MARGIN_CANCELED = "marginCanceled"
    VAULT_WITHDRAWAL_CANCELED = "vaultWithdrawalCanceled"
    OPEN_INSTEREST_CAP_CANCELED = "openInterestCapCanceled"
    SELF_TRADE_CANCELED = "selfTradeCanceled"
    REDUCE_ONLY_CANCELED = "reduceOnlyCanceled"
    SIBLING_FILLED_CANCELED = "siblingFilledCanceled"
    DELISTED_CANCELED = "delistedCanceled"
    LIQUIDATED_CANCELED = "liquidatedCanceled"
    SCHEDULED_CANCELED = "scheduledCanceled"


class InnerOrderWithStatus(TypedDict):
    order: FrontendOrder
    status: OrderStatus
    statusTimestamp: int


class OrderWithStatus(TypedDict):
    status: Literal["order", "unknowOid"]
    order: InnerOrderWithStatus | None


class L2Book(TypedDict):
    px: str
    sz: str
    n: int


class Depth(TypedDict):
    bids: list[L2Book]
    asks: list[L2Book]


class CandleInterval(str, Enum):
    OneMinute = "1m"
    ThreeMinutes = "3m"
    FiveMinutes = "5m"
    FifteenMinutes = "15m"
    ThirtyMinutes = "30m"
    OneHour = "1h"
    TwoHours = "4h"
    FourHours = "1d"
    EightHours = "8h"
    TwelveHours = "12h"
    OneDay = "1d"
    ThreeDays = "3d"
    OneWeek = "1w"
    OneMonth = "1M"


class Candle(TypedDict):
    T: int
    c: str
    h: str
    i: str
    l: str  # noqa: E741
    n: int
    o: str
    s: str
    t: int
    v: str


Candles = list[Candle]


class HistoricalOrder(TypedDict):
    order: FrontendOrder
    status: Literal[
        "filled", "open", "canceled", "triggered", "rejected", "marginCanceled"
    ]
    statusTimestamp: int


HistoricalOrders = list[HistoricalOrder]


class TwapFill(TypedDict):
    closedPnl: str
    coin: str
    crossed: bool
    dir: str
    hash: str
    oid: int
    px: str
    side: Literal["A", "B"]
    startPosition: str
    sz: str
    time: int
    fee: str
    feeToken: str
    tid: int


class TwapSliceFill(TypedDict):
    fill: TwapFill
    twapId: int


TwapSliceFills = list[TwapSliceFill]


class VaultDeposit(TypedDict):
    vaultAddress: str
    equity: str


VaultDeposits = list[VaultDeposit]


class UserRole(TypedDict):
    role: Literal["missing", "user", "agent", "vault", "subAccount"]
    data: NotRequired[dict[str, str]]


class PortfolioMeta(TypedDict):
    accountValueHistory: list[tuple[int, str]]
    pnlHistory: list[tuple[int, str]]
    vlm: str


Portfolio = list[
    tuple[
        Literal[
            "day",
            "week",
            "month",
            "allTime",
            "perpDay",
            "perpWeek",
            "perpMonth",
            "perpAllTime",
        ],
        PortfolioMeta,
    ]
]


class VaultFollower(TypedDict):
    user: str
    vaultEquity: str
    pnl: str
    allTimePnl: str
    daysFollowing: int
    vaultEntryTime: int
    lockupUntil: int


class VaultRelationshipData(TypedDict):
    childAddresses: list[str]


class VaultRelationship(TypedDict):
    type: str
    data: VaultRelationshipData


class VaultInfo(TypedDict):
    name: str
    vaultAddress: str
    leader: str
    description: str
    portfolio: Portfolio
    apr: float
    followerState: str | None
    leaderFraction: float
    leaderCommission: float
    followers: list[VaultFollower]
    maxDistributable: float
    maxWithdrawable: float
    isClosed: bool
    relationship: VaultRelationship
    allowDeposits: bool
    alwaysCloseOnWithdraw: bool


class ReferredBy(TypedDict):
    referrer: str
    code: str


class ReferralState(TypedDict):
    cumVlm: str
    cumRewardedFeesSinceReferred: str
    cumFeesRewardedToReferrer: str
    timeJoined: int
    user: str


class ReferrerStateData(TypedDict):
    code: str
    referralStates: list[ReferralState]


class referrerState(TypedDict):
    stage: str
    data: ReferrerStateData


class Referral(TypedDict):
    referredBy: ReferredBy
    cumVlm: str
    unclaimedRewards: str
    claimedRewards: str
    builderRewards: str
    referrerState: referrerState
    rewardHistory: list


class DailyUserVlm(TypedDict):
    date: str
    userCross: str
    userAdd: str
    exchange: str


class VipTier(TypedDict):
    ntlCutoff: str
    cross: str
    add: str
    spotCross: str
    spotAdd: str


class MMTier(TypedDict):
    makerFractionCutoff: str
    add: str


class FeeScheduleTiers(TypedDict):
    vip: list[VipTier]
    mm: list[MMTier]


class StakingDiscountTier(TypedDict):
    bpsOfMaxSupply: str
    discount: str


class FeeSchedule(TypedDict):
    cross: str
    add: str
    spotCross: str
    spotAdd: str
    tiers: FeeScheduleTiers
    referralDiscount: str
    stakingDiscount: list[StakingDiscountTier]


class StakingLink(TypedDict):
    type: str
    stakingUser: str


class UserFees(TypedDict):
    dailyUserVlm: list[DailyUserVlm]
    feeSchedule: FeeSchedule
    userCrossRate: str
    userAddRate: str
    userSpotCrossRate: str
    userSpotAddRate: str
    activeReferralDiscount: str
    trial: str | None
    feeTrialReward: str
    nextTrialAvailableTimestamp: int | None
    stakingLink: StakingLink
    activeStakingDiscount: StakingDiscountTier


class Delegation(TypedDict):
    validator: str
    amount: str
    lockedUntilTimestamp: int


Delegations = list[Delegation]


class StakingSummary(TypedDict):
    delegated: str
    undelegated: str
    totalPendingWithdrawal: str
    nPendingWithdrawals: int


class StakingDeltaDelegate(TypedDict):
    validator: str
    amount: str
    isUndelegate: bool


class StakingDelta(TypedDict):
    delegate: StakingDeltaDelegate


class StakingItem(TypedDict):
    time: int
    hash: str
    delta: StakingDelta


StakingHistory = list[StakingItem]


class StakingReward(TypedDict):
    time: int
    source: str  # delegation, commission
    totalAmount: str


StakingRewards = list[StakingReward]


class PerpMetaItem(TypedDict):
    name: str
    szDecimals: int
    maxLeverage: int
    onlyIsolated: bool | None
    isDelisted: bool | None


class PerpMeta(TypedDict):
    universe: list[PerpMetaItem]


class PerpMetaCtxItem(TypedDict):
    dayNtlVlm: str
    funding: str
    impactPxs: list[str]
    markPx: str
    midPx: str
    openInterest: str
    oraclePx: str
    premium: str
    prevDayPx: str


PerpMetaCtx = list[PerpMeta | list[PerpMetaCtxItem]]


DexAssetOICap = tuple[str, str]

DexSubDeployerAction = Literal[
    "registerAsset",
    "setOracle",
    "insertMarginTable",
    "setFeeRecipient",
    "haltTrading",
    "setMarginTableIds",
    "setOpenInterestCaps",
    "setFundingMultipliers",
    "setMarginModes",
    "setFeeScale",
    "setGrowthModes",
]

DexSubDeployer = tuple[DexSubDeployerAction, list[str]]


class PerpDex(TypedDict):
    name: str
    fullName: str
    deployer: str
    oracleUpdater: str | None
    feeRecipient: str
    assetToStreamingOiCap: list[DexAssetOICap]
    subDeployers: list[DexSubDeployer]
    lastDeployerFeeScaleChangeTime: str


PerpDexs = list[PerpDex | None]


class AssetFunding(TypedDict):
    allTime: str
    sinceChange: str
    sinceOpen: str


class AssetLeverage(TypedDict):
    rawUsd: str
    type: str
    value: int


class Position(TypedDict):
    coin: str
    cumFunding: AssetFunding
    entryPx: str
    leverage: AssetLeverage
    liquidationPx: str
    marginUsed: str
    maxLeverage: int
    positionValue: str
    returnOnEquity: str
    szi: str
    unrealizedPnl: str


class AssetPosition(TypedDict):
    type: str
    position: Position


class MarginSummary(TypedDict):
    accountValue: str
    totalMarginUsed: str
    totalNtlPos: str
    totalRawUsd: str


class ClearinghouseState(TypedDict):
    assetPositions: list[AssetPosition]
    crossMaintenanceMarginUsed: str
    crossMarginSummary: MarginSummary
    marginSummary: MarginSummary
    time: int
    withdrawable: str


class UserFundingDelta(TypedDict):
    coin: str
    fundingRate: str
    szi: str
    type: str
    usdc: str


class UserWithdraw(TypedDict):
    type: Literal["withdraw"]
    usdc: str
    nonce: int
    fee: str


class UserDeposit(TypedDict):
    type: Literal["deposit"]
    usdc: str


class UserTransfer(TypedDict):
    type: Literal["accountClassTransfer"]
    usdc: str
    toPerp: bool


class UserVaultDeposit(TypedDict):
    type: Literal["vaultDeposit"]
    vault: str
    usdc: str


class UserVaultWithdraw(TypedDict):
    type: Literal["vaultWithdraw"]
    vault: str
    user: str
    requestedUsd: str
    commission: str
    closingCost: str
    basis: str
    netWithdrawnUsd: str


UserNonFundingDelta = (
    UserDeposit
    | UserWithdraw
    | UserTransfer
    | UserVaultDeposit
    | UserVaultWithdraw
)


class UserFunding(TypedDict):
    delta: UserFundingDelta | UserNonFundingDelta
    hash: str
    time: int


UserFundings = list[UserFunding]


class FundingRate(TypedDict):
    coin: str
    fundingRate: str
    premium: str
    time: int


FundingRates = list[FundingRate]


class FundingInfo(TypedDict):
    fundingRate: str
    nextFundingTime: int


ExchangeFundingInfo = list[
    tuple[Literal["BinPerp", "HlPerp", "BybitPerp"], FundingInfo]
]

AssetFundingInfo = list[tuple[str, ExchangeFundingInfo]]


class PerpDeployStatus(TypedDict):
    startTimeSeconds: int
    durationSeconds: int
    startGas: str
    currentGas: str
    endGas: str | None


class Leverage(TypedDict):
    type: Literal["cross", "isolated"]
    value: int


class ActiveAssetData(TypedDict):
    user: str
    coin: str
    leverage: Leverage
    maxTradeSzs: list[str]
    availableToTrade: list[str]
    markPx: str


class Token(TypedDict):
    name: str
    index: int
    isCanonical: bool


class TokenPairs(Token):
    tokens: tuple[int, int]


class SpotTokenMeta(Token):
    szDecimals: int
    weiDecimals: int
    tokenId: str
    evmContract: str | None
    fullName: str | None


class SpotMeta(TypedDict):
    tokens: list[SpotTokenMeta]
    universe: list[TokenPairs]


class SpotMetaCtxItem(TypedDict):
    dayNtlVlm: str
    markPx: str
    midPx: str
    prevDayPx: str


SpotMetaCtx = list[SpotMeta | list[SpotMetaCtxItem]]


class TokenBalance(TypedDict):
    coin: str
    token: int
    hold: str
    total: str
    entryNtl: str


class SpotClearinghouseState(TypedDict):
    balances: list[TokenBalance]


class AccountState(TypedDict):
    perp: ClearinghouseState | dict
    spot: SpotClearinghouseState | dict
    dexs: dict[str, ClearinghouseState | dict]


class GasAuction(TypedDict):
    startTimeSeconds: int
    durationSeconds: int
    startGas: str
    currentGas: str | None
    endGas: str


class DeployStateSpec(TypedDict):
    name: str
    szDecimals: int
    weiDecimals: int


class DeployState(TypedDict):
    token: int
    spec: DeployStateSpec
    fullName: str
    spots: list[int]
    maxSupply: int
    hyperliquidityGenesisBalance: str
    totalGenesisBalanceWei: str
    userGenesisBalances: list[tuple[str, str]]
    existingTokenGenesisBalances: list[tuple[int, str]]


class SpotDeployState(TypedDict):
    states: list[DeployState]
    gasAuction: GasAuction


class TokenGenesis(TypedDict):
    userBalances: list[tuple[str, str]]
    existingTokenBalances: list[Any]


class TokenDetails(TypedDict):
    name: str
    maxSupply: str
    totalSupply: str
    circulatingSupply: str
    szDecimals: int
    weiDecimals: int
    midPx: str
    markPx: str
    prevDayPx: str
    genesis: list[TokenGenesis]
    deployer: str
    deployGas: str
    deployTime: str
    seededUsdc: str
    nonCirculatingUserBalances: list[Any]
    futureEmissions: str


class SubAccount(TypedDict):
    name: str
    subAccountUser: str
    master: str
    clearinghouseState: ClearinghouseState
    spotState: SpotClearinghouseState


SubAccounts = list[SubAccount]


class Metas(TypedDict):
    perp: PerpMeta | dict
    spot: SpotMeta | list
    dexs: dict[str, PerpMeta]


class SignType(str, Enum):
    SINGLE_SIG = "singleSig"
    MULTI_SIG = "multiSig"


Abstraction = Literal["unifiedAccount", "portfolioMargin", "disabled"]
AgentAbstraction = Literal["u", "p", "i"]
