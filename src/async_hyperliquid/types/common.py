from enum import StrEnum
from re import fullmatch
from typing import Literal, Self, TypeAlias


JsonScalar: TypeAlias = str | int | float | bool | None
JsonValue: TypeAlias = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject: TypeAlias = dict[str, JsonValue]


class Network(StrEnum):
    MAINNET = "mainnet"
    TESTNET = "testnet"

    @property
    def info_url(self) -> str:
        if self is Network.MAINNET:
            return "https://api.hyperliquid.xyz/info"
        return "https://api.hyperliquid-testnet.xyz/info"

    @property
    def exchange_url(self) -> str:
        if self is Network.MAINNET:
            return "https://api.hyperliquid.xyz/exchange"
        return "https://api.hyperliquid-testnet.xyz/exchange"

    @property
    def signature_source(self) -> Literal["a", "b"]:
        return "a" if self is Network.MAINNET else "b"


class TimeInForce(StrEnum):
    ALO = "Alo"
    IOC = "Ioc"
    GTC = "Gtc"


class TriggerKind(StrEnum):
    TAKE_PROFIT = "tp"
    STOP_LOSS = "sl"


class OrderGrouping(StrEnum):
    NA = "na"
    NORMAL_TPSL = "normalTpsl"
    POSITION_TPSL = "positionTpsl"


class CandleInterval(StrEnum):
    ONE_MINUTE = "1m"
    THREE_MINUTES = "3m"
    FIVE_MINUTES = "5m"
    FIFTEEN_MINUTES = "15m"
    THIRTY_MINUTES = "30m"
    ONE_HOUR = "1h"
    TWO_HOURS = "2h"
    FOUR_HOURS = "4h"
    EIGHT_HOURS = "8h"
    TWELVE_HOURS = "12h"
    ONE_DAY = "1d"
    THREE_DAYS = "3d"
    ONE_WEEK = "1w"
    ONE_MONTH = "1M"


class UserAbstraction(StrEnum):
    DISABLED = "disabled"
    UNIFIED_ACCOUNT = "unifiedAccount"
    PORTFOLIO_MARGIN = "portfolioMargin"


class AgentAbstraction(StrEnum):
    ISOLATED = "i"
    UNIFIED_ACCOUNT = "u"
    PORTFOLIO_MARGIN = "p"


class Cloid(str):
    """A validated 16-byte hexadecimal client order ID."""

    def __new__(cls, value: str) -> Self:
        if fullmatch(r"0x[0-9a-fA-F]{32}", value) is None:
            raise ValueError("client order ID must be 0x plus 32 hex characters")
        return str.__new__(cls, value)

    @classmethod
    def from_int(cls, value: int) -> Self:
        if value < 0 or value >= 1 << 128:
            raise ValueError("client order ID integer must fit in 16 bytes")
        return cls(f"{value:#034x}")
