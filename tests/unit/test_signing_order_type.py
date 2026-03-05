import pytest

from async_hyperliquid.utils.signing import ensure_order_type


def test_ensure_order_type_rejects_malformed_dual_variant() -> None:
    malformed = {
        "limit": {"tif": "Ioc"},
        "trigger": {"isMarket": False, "triggerPx": "100", "tpsl": "tp"},
    }
    with pytest.raises(ValueError, match="Invalid order type"):
        ensure_order_type(malformed)  # type: ignore[arg-type]
