import pytest

from async_hyperliquid.types import CandleInterval, Cloid, Network


@pytest.mark.parametrize(
    ("network", "info_url", "exchange_url", "signature_source"),
    [
        (
            Network.MAINNET,
            "https://api.hyperliquid.xyz/info",
            "https://api.hyperliquid.xyz/exchange",
            "a",
        ),
        (
            Network.TESTNET,
            "https://api.hyperliquid-testnet.xyz/info",
            "https://api.hyperliquid-testnet.xyz/exchange",
            "b",
        ),
    ],
)
def test_network_owns_endpoints_and_signing_source(
    network: Network, info_url: str, exchange_url: str, signature_source: str
) -> None:
    assert network.info_url == info_url
    assert network.exchange_url == exchange_url
    assert network.signature_source == signature_source


def test_candle_intervals_keep_two_and_four_hours_distinct() -> None:
    assert CandleInterval.TWO_HOURS == "2h"
    assert CandleInterval.FOUR_HOURS == "4h"


def test_cloid_is_a_validated_wire_string() -> None:
    raw = "0x" + "a1" * 16

    cloid = Cloid(raw)

    assert cloid == raw
    assert isinstance(cloid, str)


@pytest.mark.parametrize(
    "raw", ["a1" * 16, "0x" + "a1" * 15, "0x" + "a1" * 17, "0x" + "zz" * 16]
)
def test_cloid_rejects_invalid_wire_values(raw: str) -> None:
    with pytest.raises(ValueError):
        Cloid(raw)
