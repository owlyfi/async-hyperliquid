from importlib.metadata import version

import async_hyperliquid
from async_hyperliquid import AsyncHyper, AsyncHyperliquid, ExchangeAPI, InfoAPI


def test_0_5_1_root_exports_are_frozen() -> None:
    assert async_hyperliquid.__all__ == [
        "AsyncHyper",
        "InfoAPI",
        "ExchangeAPI",
        "AsyncHyperliquid",
    ]
    assert AsyncHyper is AsyncHyperliquid
    assert InfoAPI.__name__ == "InfoAPI"
    assert ExchangeAPI.__name__ == "ExchangeAPI"


def test_maintenance_baseline_has_0_5_1_version() -> None:
    assert version("async-hyperliquid") == "0.5.1"
