from __future__ import annotations

import asyncio
import gc
import os
import statistics
import warnings
from dataclasses import dataclass
from time import perf_counter_ns
from types import SimpleNamespace
from typing import Any, Awaitable, Callable, cast

from async_hyperliquid._async_hyperliquid.orders import AsyncHyperliquidOrdersClient
from async_hyperliquid.utils.constants import PERP_DEX_OFFSET, SPOT_OFFSET
from async_hyperliquid.utils.miscs import round_float, round_px

REPEATS = int(os.getenv("BENCH_REPEATS", "7"))
IO_ITERATIONS = int(os.getenv("BENCH_IO_ITERATIONS", "50"))
LOOKUP_ITERATIONS = int(os.getenv("BENCH_LOOKUP_ITERATIONS", "50000"))
IO_LATENCY_MS = float(os.getenv("BENCH_IO_LATENCY_MS", "5.0"))
CANCEL_BATCH_SIZE = int(os.getenv("BENCH_CANCEL_BATCH_SIZE", "20"))

warnings.filterwarnings(
    "ignore",
    message="get_all_market_prices is deprecated and will remove in the future, use get_all_mids instead",
)


@dataclass(frozen=True)
class BenchmarkResult:
    name: str
    iterations: int
    median_ns: float
    mean_ns: float
    min_ns: float
    max_ns: float

    @property
    def ops_per_sec(self) -> float:
        return 1_000_000_000 / self.median_ns if self.median_ns else 0.0


class FakeInfoAPI:
    def __init__(self, latency_s: float) -> None:
        self.latency_s = latency_s
        self._perp_meta = {"universe": [{"name": "BTC", "szDecimals": 3}]}
        self._spot_meta = {
            "universe": [{"index": 0, "name": "PURR/USDC", "tokens": [0, 1]}],
            "tokens": [
                {"name": "PURR", "szDecimals": 2, "tokenId": "1", "weiDecimals": 8},
                {"name": "USDC", "szDecimals": 6, "tokenId": "2", "weiDecimals": 6},
            ],
        }
        self._perp_meta_ctx = ({}, [{"markPx": "105000"}])
        self._spot_meta_ctx = ({}, [{"markPx": "1.25"}])

    async def get_perp_meta(self, dex: str = "") -> dict[str, Any]:
        await asyncio.sleep(self.latency_s)
        return {
            "universe": [{"name": "BTC" if not dex else dex.upper(), "szDecimals": 3}]
        }

    async def get_spot_meta(self) -> dict[str, Any]:
        await asyncio.sleep(self.latency_s)
        return self._spot_meta

    async def get_spot_meta_ctx(self) -> tuple[dict[str, Any], list[dict[str, str]]]:
        await asyncio.sleep(self.latency_s)
        return self._spot_meta_ctx

    async def get_perp_meta_ctx(self) -> tuple[dict[str, Any], list[dict[str, str]]]:
        await asyncio.sleep(self.latency_s)
        return self._perp_meta_ctx


class MetaBenchmarkClient(AsyncHyperliquidOrdersClient):
    def __init__(self, latency_s: float) -> None:
        self.latency_s = latency_s
        self.info = FakeInfoAPI(latency_s)
        self.coin_assets = {"BTC": 0, "PURR/USDC": SPOT_OFFSET}
        self.coin_names = {"BTC": "BTC", "PURR/USDC": "PURR/USDC"}
        self.asset_sz_decimals = {0: 3, SPOT_OFFSET: 2}
        self.spot_tokens: dict[str, Any] = {}
        self.perp_dexs = ["", "dex-a", "dex-b", "dex-c"]

    async def init_metas(self) -> None:
        return None

    async def get_all_dex_name(self) -> list[str]:
        await asyncio.sleep(self.latency_s)
        return self.perp_dexs

    async def get_coin_name(self, coin: str) -> str:
        return self.coin_names[coin]


class CancelBenchmarkClient(AsyncHyperliquidOrdersClient):
    def __init__(self, latency_s: float) -> None:
        self.latency_s = latency_s
        self.assets = {f"COIN-{index}": index for index in range(CANCEL_BATCH_SIZE)}
        self.exchange = SimpleNamespace(post_action=self._post_action)
        self.vault = None
        self.expires = None

    async def _post_action(self, action: dict[str, Any], **_: Any) -> dict[str, Any]:
        return action

    async def get_coin_asset(self, coin: str) -> int:
        await asyncio.sleep(self.latency_s)
        return self.assets[coin]


async def legacy_get_metas(
    client: MetaBenchmarkClient, perp_only: bool = False
) -> dict[str, Any]:
    metas: dict[str, Any] = {"perp": {}, "spot": [], "dexs": {}}
    perp_meta = await client.info.get_perp_meta()
    if perp_only:
        metas["perp"] = perp_meta
        return metas

    metas["spot"] = await client.info.get_spot_meta()
    return metas


async def legacy_get_all_metas(client: MetaBenchmarkClient) -> dict[str, Any]:
    dexs = await client.get_all_dex_name()
    dex_metas: dict[str, Any] = {}
    for dex in dexs[1:]:
        dex_metas[dex] = await client.info.get_perp_meta(dex)

    spot_meta = await client.info.get_spot_meta()
    perp_meta = await client.info.get_perp_meta()
    return {"perp": perp_meta, "spot": spot_meta, "dexs": dex_metas}


async def legacy_get_all_market_prices(client: MetaBenchmarkClient) -> dict[str, float]:
    await client.init_metas()
    spot_data = cast(Any, await client.info.get_spot_meta_ctx())
    perp_data = cast(Any, await client.info.get_perp_meta_ctx())
    prices: dict[str, float] = {}
    for coin, asset in client.coin_assets.items():
        is_perp_asset = asset < SPOT_OFFSET
        is_spot_asset = SPOT_OFFSET <= asset < PERP_DEX_OFFSET
        if is_perp_asset:
            prices[coin] = float(perp_data[1][asset]["markPx"])
        if is_spot_asset:
            prices[coin] = float(spot_data[1][asset - SPOT_OFFSET]["markPx"])
    return prices


async def legacy_get_coin_asset(client: MetaBenchmarkClient, coin: str) -> int:
    coin_name = await client.get_coin_name(coin)
    return client.coin_assets[coin_name]


async def legacy_get_coin_sz_decimals(client: MetaBenchmarkClient, coin: str) -> int:
    coin_name = await client.get_coin_name(coin)
    asset = await legacy_get_coin_asset(client, coin_name)
    return client.asset_sz_decimals[asset]


async def legacy_round_sz_px(
    client: MetaBenchmarkClient, coin: str, sz: float, px: float
) -> tuple[int, float, float | int]:
    asset = await legacy_get_coin_asset(client, coin)
    is_spot = SPOT_OFFSET <= asset < PERP_DEX_OFFSET
    sz_decimals = await legacy_get_coin_sz_decimals(client, coin)
    px_decimals = (6 if not is_spot else 8) - sz_decimals
    return asset, round_float(sz, sz_decimals), round_px(px, px_decimals)


async def legacy_cancel_orders(
    client: CancelBenchmarkClient, cancels: list[tuple[str, int]]
) -> dict[str, Any]:
    action = {
        "type": "cancel",
        "cancels": [
            {"a": await client.get_coin_asset(coin), "o": oid} for coin, oid in cancels
        ],
    }
    return await client.exchange.post_action(
        action, vault=client.vault, expires=client.expires
    )


async def run_async_benchmark(
    name: str, iterations: int, setup: Callable[[], Callable[[], Awaitable[object]]]
) -> BenchmarkResult:
    timings: list[float] = []
    for _ in range(REPEATS):
        benchmark_fn = setup()
        gc.collect()
        gc.disable()
        start = perf_counter_ns()
        for _ in range(iterations):
            await benchmark_fn()
        elapsed = perf_counter_ns() - start
        gc.enable()
        timings.append(elapsed / iterations)

    return BenchmarkResult(
        name=name,
        iterations=iterations,
        median_ns=statistics.median(timings),
        mean_ns=statistics.mean(timings),
        min_ns=min(timings),
        max_ns=max(timings),
    )


def percent_delta(new: BenchmarkResult, old: BenchmarkResult) -> float:
    return ((old.median_ns - new.median_ns) / old.median_ns) * 100


def print_pair(current: BenchmarkResult, legacy: BenchmarkResult) -> None:
    print(f"{current.name}:")
    print(
        f"  current median: {current.median_ns:,.1f} ns/op ({current.ops_per_sec:,.1f} ops/s)"
    )
    print(
        f"  legacy  median: {legacy.median_ns:,.1f} ns/op ({legacy.ops_per_sec:,.1f} ops/s)"
    )
    print(f"  improvement:    {percent_delta(current, legacy):.2f}%")
    print()


async def main() -> None:
    io_latency_s = IO_LATENCY_MS / 1000.0
    meta_client = MetaBenchmarkClient(io_latency_s)
    cancel_client = CancelBenchmarkClient(io_latency_s)
    cancels = [(coin, index) for index, coin in enumerate(cancel_client.assets)]

    current_get_metas = await run_async_benchmark(
        "get_metas (spot + perp)",
        IO_ITERATIONS,
        lambda: (
            lambda client=meta_client: cast(Awaitable[object], client.get_metas())
        ),
    )
    legacy_get_metas_result = await run_async_benchmark(
        "get_metas (spot + perp)",
        IO_ITERATIONS,
        lambda: (lambda client=meta_client: legacy_get_metas(client)),
    )

    current_get_all_metas = await run_async_benchmark(
        "get_all_metas (3 extra dexs)",
        IO_ITERATIONS,
        lambda: (
            lambda client=meta_client: cast(Awaitable[object], client.get_all_metas())
        ),
    )
    legacy_get_all_metas_result = await run_async_benchmark(
        "get_all_metas (3 extra dexs)",
        IO_ITERATIONS,
        lambda: (lambda client=meta_client: legacy_get_all_metas(client)),
    )

    current_market_prices = await run_async_benchmark(
        "get_all_market_prices(all)",
        IO_ITERATIONS,
        lambda: (
            lambda client=meta_client: cast(
                Awaitable[object], client.get_all_market_prices(market="all")
            )
        ),
    )
    legacy_market_prices = await run_async_benchmark(
        "get_all_market_prices(all)",
        IO_ITERATIONS,
        lambda: (lambda client=meta_client: legacy_get_all_market_prices(client)),
    )

    current_round_sz_px = await run_async_benchmark(
        "_round_sz_px warm-cache lookup",
        LOOKUP_ITERATIONS,
        lambda: (
            lambda client=meta_client: cast(
                Awaitable[object], client._round_sz_px("PURR/USDC", 12.3456, 1.234567)
            )
        ),
    )
    legacy_round_sz_px_result = await run_async_benchmark(
        "_round_sz_px warm-cache lookup",
        LOOKUP_ITERATIONS,
        lambda: (
            lambda client=meta_client: legacy_round_sz_px(
                client, "PURR/USDC", 12.3456, 1.234567
            )
        ),
    )

    current_cancel_orders = await run_async_benchmark(
        f"cancel_orders asset resolution (batch={CANCEL_BATCH_SIZE})",
        IO_ITERATIONS,
        lambda: (
            lambda client=cancel_client: cast(
                Awaitable[object], client.cancel_orders(cancels)
            )
        ),
    )
    legacy_cancel_orders_result = await run_async_benchmark(
        f"cancel_orders asset resolution (batch={CANCEL_BATCH_SIZE})",
        IO_ITERATIONS,
        lambda: (lambda client=cancel_client: legacy_cancel_orders(client, cancels)),
    )

    print("Client hot-path benchmark")
    print(
        f"repeats={REPEATS}, io_iterations={IO_ITERATIONS}, "
        f"lookup_iterations={LOOKUP_ITERATIONS}, io_latency_ms={IO_LATENCY_MS}, "
        f"cancel_batch_size={CANCEL_BATCH_SIZE}"
    )
    print()
    print_pair(current_get_metas, legacy_get_metas_result)
    print_pair(current_get_all_metas, legacy_get_all_metas_result)
    print_pair(current_market_prices, legacy_market_prices)
    print_pair(current_round_sz_px, legacy_round_sz_px_result)
    print_pair(current_cancel_orders, legacy_cancel_orders_result)


if __name__ == "__main__":
    asyncio.run(main())
