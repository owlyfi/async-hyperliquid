from typing import Literal, NotRequired, TypeAlias, TypedDict

AllMids: TypeAlias = dict[str, str]


class OpenOrder(TypedDict):
    coin: str
    limitPx: str
    oid: int
    side: Literal["A", "B"]
    sz: str
    timestamp: int


class FrontendOrder(OpenOrder):
    children: list["FrontendOrder"]
    cloid: str | None
    isPositionTpsl: bool
    isTrigger: bool
    orderType: str
    origSz: str
    reduceOnly: bool
    tif: Literal["Alo", "Gtc", "Ioc", "FrontendMarket"] | None
    triggerCondition: str
    triggerPx: str


OpenOrders: TypeAlias = list[OpenOrder]
FrontendOpenOrders: TypeAlias = list[FrontendOrder]


class UserFill(TypedDict):
    builderFee: NotRequired[str]
    closedPnl: str
    coin: str
    crossed: bool
    dir: str
    fee: str
    feeToken: str
    hash: str
    oid: int
    px: str
    side: Literal["A", "B"]
    startPosition: str
    sz: str
    tid: int
    time: int


UserFills: TypeAlias = list[UserFill]


class UserRateLimit(TypedDict):
    cumVlm: str
    nRequestsUsed: int
    nRequestsCap: int
    nRequestsSurplus: int


OrderStatusValue: TypeAlias = Literal[
    "open",
    "filled",
    "canceled",
    "triggered",
    "rejected",
    "marginCanceled",
    "vaultWithdrawalCanceled",
    "openInterestCapCanceled",
    "selfTradeCanceled",
    "reduceOnlyCanceled",
    "siblingFilledCanceled",
    "delistedCanceled",
    "liquidatedCanceled",
    "scheduledCancel",
    "tickRejected",
    "minTradeNtlRejected",
    "perpMarginRejected",
    "reduceOnlyRejected",
    "badAloPxRejected",
    "iocCancelRejected",
    "badTriggerPxRejected",
    "marketOrderNoLiquidityRejected",
    "positionIncreaseAtOpenInterestCapRejected",
    "positionFlipAtOpenInterestCapRejected",
    "tooAggressiveAtOpenInterestCapRejected",
    "openInterestIncreaseRejected",
    "insufficientSpotBalanceRejected",
    "oracleRejected",
    "perpMaxPositionRejected",
]


class OrderStatusData(TypedDict):
    order: FrontendOrder
    status: OrderStatusValue
    statusTimestamp: int


class KnownOrderStatus(TypedDict):
    status: Literal["order"]
    order: OrderStatusData


class UnknownOrderStatus(TypedDict):
    status: Literal["unknownOid"]


OrderStatus: TypeAlias = KnownOrderStatus | UnknownOrderStatus


class L2Level(TypedDict):
    px: str
    sz: str
    n: int


class L2Book(TypedDict):
    coin: str
    time: int
    levels: list[list[L2Level]]


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


Candles: TypeAlias = list[Candle]


class HistoricalOrder(TypedDict):
    order: FrontendOrder
    status: OrderStatusValue
    statusTimestamp: int


HistoricalOrders: TypeAlias = list[HistoricalOrder]


class TwapSliceFill(TypedDict):
    fill: UserFill
    twapId: int


TwapSliceFills: TypeAlias = list[TwapSliceFill]


class VaultEquity(TypedDict):
    vaultAddress: str
    equity: str


VaultEquities: TypeAlias = list[VaultEquity]


class PlainUserRole(TypedDict):
    role: Literal["missing", "user", "vault"]


class AgentUserRoleData(TypedDict):
    user: str


class AgentUserRole(TypedDict):
    role: Literal["agent"]
    data: AgentUserRoleData


class SubAccountUserRoleData(TypedDict):
    master: str


class SubAccountUserRole(TypedDict):
    role: Literal["subAccount"]
    data: SubAccountUserRoleData


UserRole: TypeAlias = PlainUserRole | AgentUserRole | SubAccountUserRole


PortfolioPeriod: TypeAlias = Literal[
    "day", "week", "month", "allTime", "perpDay", "perpWeek", "perpMonth", "perpAllTime"
]
HistoryPoint: TypeAlias = list[int | str]


class PortfolioData(TypedDict):
    accountValueHistory: list[HistoryPoint]
    pnlHistory: list[HistoryPoint]
    vlm: str


PortfolioEntry: TypeAlias = list[PortfolioPeriod | PortfolioData]
Portfolio: TypeAlias = list[PortfolioEntry]


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


class VaultDetails(TypedDict):
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
    tokenToState: list["ReferralTokenEntry"]


class ReferralTokenState(TypedDict):
    cumVlm: str
    cumRewardedFeesSinceReferred: str
    cumFeesRewardedToReferrer: str


ReferralTokenEntry: TypeAlias = list[int | ReferralTokenState]


class ReadyReferrerData(TypedDict):
    code: str
    nReferrals: int
    referralStates: list[ReferralState]


class ReadyReferrerState(TypedDict):
    stage: Literal["ready"]
    data: ReadyReferrerData


class NewReferrerState(TypedDict):
    stage: Literal["needToCreateCode"]


class IneligibleReferrerData(TypedDict):
    required: str


class IneligibleReferrerState(TypedDict):
    stage: Literal["needToTrade"]
    data: IneligibleReferrerData


ReferrerState: TypeAlias = (
    ReadyReferrerState | NewReferrerState | IneligibleReferrerState
)


class TokenReferralState(TypedDict):
    cumVlm: str
    unclaimedRewards: str
    claimedRewards: str
    builderRewards: str


TokenReferralEntry: TypeAlias = list[int | TokenReferralState]


class ReferralReward(TypedDict):
    earned: str
    vlm: str
    referralVlm: str
    time: int


class Referral(TypedDict):
    referredBy: ReferredBy | None
    cumVlm: str
    unclaimedRewards: str
    claimedRewards: str
    builderRewards: str
    referrerState: ReferrerState
    rewardHistory: list[ReferralReward]
    tokenToState: list[TokenReferralEntry]


class DailyUserVolume(TypedDict):
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


class MarketMakerTier(TypedDict):
    makerFractionCutoff: str
    add: str


class FeeScheduleTiers(TypedDict):
    vip: list[VipTier]
    mm: list[MarketMakerTier]


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
    dailyUserVlm: list[DailyUserVolume]
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


Delegations: TypeAlias = list[Delegation]


class StakingSummary(TypedDict):
    delegated: str
    undelegated: str
    totalPendingWithdrawal: str
    nPendingWithdrawals: int


class DelegationChange(TypedDict):
    validator: str
    amount: str
    isUndelegate: bool


class StakingDelta(TypedDict):
    delegate: DelegationChange


class StakingHistoryItem(TypedDict):
    time: int
    hash: str
    delta: StakingDelta


StakingHistory: TypeAlias = list[StakingHistoryItem]


class StakingReward(TypedDict):
    time: int
    source: Literal["delegation", "commission"]
    totalAmount: str


StakingRewards: TypeAlias = list[StakingReward]
UserAbstractionState: TypeAlias = Literal[
    "unifiedAccount", "portfolioMargin", "disabled", "default", "dexAbstraction"
]


class AlignedQuoteTokenInfo(TypedDict):
    isAligned: bool
    firstAlignedTime: int
    evmMintedSupply: str
    dailyAmountOwed: list[list[str]]
    predictedRate: str


MarginMode: TypeAlias = Literal["strictIsolated", "noCross"]
GrowthMode: TypeAlias = Literal["enabled", "disabled"]


class PerpAsset(TypedDict):
    name: str
    szDecimals: int
    maxLeverage: int
    onlyIsolated: NotRequired[bool]
    isDelisted: NotRequired[bool]
    marginMode: NotRequired[MarginMode]
    marginTableId: NotRequired[int]
    growthMode: NotRequired[GrowthMode]
    lastGrowthModeChangeTime: NotRequired[str]


class MarginTier(TypedDict):
    lowerBound: str
    maxLeverage: int


class MarginTable(TypedDict):
    description: str
    marginTiers: list[MarginTier]


MarginTableEntry: TypeAlias = list[int | MarginTable]


class PerpMeta(TypedDict):
    universe: list[PerpAsset]
    marginTables: list[MarginTableEntry]
    collateralToken: NotRequired[int]


class PerpAssetContext(TypedDict):
    dayNtlVlm: str
    funding: str
    impactPxs: list[str] | None
    markPx: str
    midPx: str | None
    openInterest: str
    oraclePx: str
    premium: str | None
    prevDayPx: str
    dayBaseVlm: NotRequired[str]


PerpMetaAndContexts: TypeAlias = tuple[PerpMeta, list[PerpAssetContext]]
AllPerpMetas: TypeAlias = list[PerpMetaAndContexts]


class PerpDex(TypedDict):
    name: str
    fullName: str
    deployer: str
    oracleUpdater: str | None
    feeRecipient: str | None
    assetToStreamingOiCap: list[list[str]]
    assetToFundingMultiplier: list[list[str]]


PerpDexes: TypeAlias = list[PerpDex | None]


class CumulativeFunding(TypedDict):
    allTime: str
    sinceChange: str
    sinceOpen: str


class PositionLeverage(TypedDict):
    rawUsd: NotRequired[str]
    type: Literal["cross", "isolated"]
    value: int


class Position(TypedDict):
    coin: str
    cumFunding: CumulativeFunding
    entryPx: str
    leverage: PositionLeverage
    liquidationPx: str | None
    marginUsed: str
    maxLeverage: int
    positionValue: str
    returnOnEquity: str
    szi: str
    unrealizedPnl: str


class AssetPosition(TypedDict):
    type: Literal["oneWay"]
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


class FundingDelta(TypedDict):
    coin: str
    fundingRate: str
    szi: str
    type: Literal["funding"]
    usdc: str
    nSamples: NotRequired[int | None]


class DepositDelta(TypedDict):
    type: Literal["deposit"]
    usdc: str


class WithdrawDelta(TypedDict):
    type: Literal["withdraw"]
    usdc: str
    nonce: int
    fee: str


class AccountClassTransferDelta(TypedDict):
    type: Literal["accountClassTransfer"]
    usdc: str
    toPerp: bool


class VaultDepositDelta(TypedDict):
    type: Literal["vaultDeposit"]
    vault: str
    usdc: str


class VaultWithdrawDelta(TypedDict):
    type: Literal["vaultWithdraw"]
    vault: str
    user: str
    requestedUsd: str
    commission: str
    closingCost: str
    basis: str
    netWithdrawnUsd: str


LedgerDelta: TypeAlias = (
    FundingDelta
    | DepositDelta
    | WithdrawDelta
    | AccountClassTransferDelta
    | VaultDepositDelta
    | VaultWithdrawDelta
)


class LedgerUpdate(TypedDict):
    delta: LedgerDelta
    hash: str
    time: int


LedgerUpdates: TypeAlias = list[LedgerUpdate]


class FundingRate(TypedDict):
    coin: str
    fundingRate: str
    premium: str
    time: int


FundingRates: TypeAlias = list[FundingRate]


class PredictedFundingInfo(TypedDict):
    fundingRate: str
    nextFundingTime: int


FundingVenue: TypeAlias = Literal["BinPerp", "HlPerp", "BybitPerp"]
FundingVenueEntry: TypeAlias = list[FundingVenue | PredictedFundingInfo]
PredictedFundingEntry: TypeAlias = list[str | list[FundingVenueEntry]]
PredictedFundings: TypeAlias = list[PredictedFundingEntry]


class PerpDeployAuctionStatus(TypedDict):
    startTimeSeconds: int
    durationSeconds: int
    startGas: str
    currentGas: str
    endGas: str | None


class ActiveAssetLeverage(TypedDict):
    rawUsd: NotRequired[str]
    type: Literal["cross", "isolated"]
    value: int


class ActiveAssetData(TypedDict):
    user: str
    coin: str
    leverage: ActiveAssetLeverage
    maxTradeSzs: list[str]
    availableToTrade: list[str]
    markPx: str


class SpotToken(TypedDict):
    name: str
    index: int
    isCanonical: bool
    szDecimals: int
    weiDecimals: int
    tokenId: str
    evmContract: str | None
    fullName: str | None


class SpotPair(TypedDict):
    name: str
    index: int
    isCanonical: bool
    tokens: list[int]


class SpotMeta(TypedDict):
    tokens: list[SpotToken]
    universe: list[SpotPair]


class SpotAssetContext(TypedDict):
    dayNtlVlm: str
    markPx: str
    midPx: str | None
    prevDayPx: str


SpotMetaAndContexts: TypeAlias = tuple[SpotMeta, list[SpotAssetContext]]


class TokenBalance(TypedDict):
    coin: str
    token: int
    hold: str
    total: str
    entryNtl: str


class SpotClearinghouseState(TypedDict):
    balances: list[TokenBalance]


class GasAuction(TypedDict):
    startTimeSeconds: int
    durationSeconds: int
    startGas: str
    currentGas: str | None
    endGas: str


class TokenDeploySpec(TypedDict):
    name: str
    szDecimals: int
    weiDecimals: int


class TokenDeployState(TypedDict):
    token: int
    spec: TokenDeploySpec
    fullName: str
    spots: list[int]
    maxSupply: int
    hyperliquidityGenesisBalance: str
    totalGenesisBalanceWei: str
    userGenesisBalances: list[list[str]]
    existingTokenGenesisBalances: list[list[int | str]]


class SpotDeployState(TypedDict):
    states: list[TokenDeployState]
    gasAuction: GasAuction


class TokenGenesis(TypedDict):
    userBalances: list[list[str]]
    existingTokenBalances: list[list[int | str]]


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
    nonCirculatingUserBalances: list[list[str]]
    futureEmissions: str


class SubAccount(TypedDict):
    name: str
    subAccountUser: str
    master: str
    clearinghouseState: ClearinghouseState
    spotState: SpotClearinghouseState


SubAccounts: TypeAlias = list[SubAccount]
