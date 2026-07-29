import async_hyperliquid
from async_hyperliquid import AsyncHyperliquid, HyperliquidError, InfoClient


def test_v1_root_exports_are_exact() -> None:
    assert async_hyperliquid.__all__ == [
        "AsyncHyperliquid",
        "InfoClient",
        "HyperliquidError",
    ]
    assert AsyncHyperliquid.__name__ == "AsyncHyperliquid"
    assert InfoClient.__name__ == "InfoClient"
    assert issubclass(HyperliquidError, Exception)
