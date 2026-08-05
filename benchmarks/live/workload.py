from __future__ import annotations

import math
from collections.abc import Sequence

from async_hyperliquid._internal.encoding import _round_price
from async_hyperliquid.types import Cloid

from .models import CanonicalOrder, OrderPair


def _canonical_price(mid: float, multiplier: float, size_decimals: int) -> float:
    maximum_decimals = 6 - size_decimals
    return float(_round_price(mid * multiplier, maximum_decimals))


def _canonical_size(
    price: float, *, size_decimals: int, target_notional: float
) -> float:
    scale = 10**size_decimals
    return math.ceil((target_notional / price) * scale) / scale


def build_order_pair(
    mid: float,
    size_decimals: int,
    *,
    target_notional: float,
    cloids: tuple[str, str],
    buy_multiplier: float = 0.90,
    sell_multiplier: float = 1.10,
) -> OrderPair:
    if not math.isfinite(mid) or mid <= 0:
        raise ValueError("mid must be positive and finite")
    if not 0 <= size_decimals <= 6:
        raise ValueError("size_decimals must be between 0 and 6")
    if not math.isfinite(target_notional) or target_notional <= 0:
        raise ValueError("target_notional must be positive and finite")
    if not math.isfinite(buy_multiplier) or not 0 < buy_multiplier < 1:
        raise ValueError("buy_multiplier must be between zero and one")
    if not math.isfinite(sell_multiplier) or sell_multiplier <= 1:
        raise ValueError("sell_multiplier must be greater than one")

    buy_cloid, sell_cloid = (str(Cloid(value)) for value in cloids)
    buy_price = _canonical_price(mid, buy_multiplier, size_decimals)
    sell_price = _canonical_price(mid, sell_multiplier, size_decimals)
    return OrderPair(
        buy=CanonicalOrder(
            is_buy=True,
            price=buy_price,
            size=_canonical_size(
                buy_price, size_decimals=size_decimals, target_notional=target_notional
            ),
            cloid=buy_cloid,
        ),
        sell=CanonicalOrder(
            is_buy=False,
            price=sell_price,
            size=_canonical_size(
                sell_price, size_decimals=size_decimals, target_notional=target_notional
            ),
            cloid=sell_cloid,
        ),
    )


def rotate_names(names: Sequence[str], round_index: int) -> tuple[str, ...]:
    if not names:
        raise ValueError("names must not be empty")
    if round_index < 0:
        raise ValueError("round_index must not be negative")
    items = tuple(names)
    offset = round_index % len(items)
    return items[offset:] + items[:offset]
