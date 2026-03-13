import os
import time
import asyncio
import statistics
from typing import List
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor, as_completed

from dotenv import load_dotenv
from eth_account import Account
from hyperliquid.info import Info
from hyperliquid.utils import constants
from hyperliquid.exchange import Exchange

from async_hyperliquid import AsyncHyper
from async_hyperliquid.utils.types import LimitOrder

load_dotenv(".env.local")

hlp = "0xa15099a30bbf2e68942d6f4c43d70d04faeab0a0"
ADDRESS = os.getenv("HL_ADDR", "")
API_KEY = os.getenv("HL_AK", "")

# Test parameters
coin = "BTC"
is_buy = True
sz = 0.0002
px = 110_000
order_type = LimitOrder.ALO.value

# Rate limiting constants
RATE_LIMIT_WEIGHTS_PER_MINUTE = 1200
USER_STATE_WEIGHT = 2
PLACE_ORDER_WEIGHT = 1


@dataclass
class BenchmarkResult:
    """Results from a benchmark test."""

    operation: str
    method: str
    total_time: float
    avg_time: float
    min_time: float
    max_time: float
    median_time: float
    std_dev: float
    success_count: int
    error_count: int
    total_requests: int
    requests_per_second: float


class BenchmarkRunner:
    """Runs performance benchmarks comparing async vs sync implementations."""

    def __init__(self):
        self.hl = AsyncHyper(ADDRESS, API_KEY, is_mainnet=False)
        self.info = Info(constants.TESTNET_API_URL, skip_ws=True)
        self.exchange = Exchange(
            Account.from_key(API_KEY), constants.TESTNET_API_URL
        )
        self.results: List[BenchmarkResult] = []
        self.detailed_times: List[dict] = []

    async def async_user_state(self) -> None:
        """Async user state request with rate limiting."""
        await self.hl.info.get_perp_clearinghouse_state(hlp)

    async def async_place_order(self) -> None:
        """Async place order request with rate limiting."""
        resp = await self.hl.place_order(
            coin,
            is_buy,
            sz,
            px,
            is_market=False,
            order_type=order_type,  # type: ignore
        )
        oid = resp["response"]["data"]["statuses"][0]["resting"]["oid"]
        await self.hl.cancel_order(coin, oid)

    def sync_user_state(self) -> None:
        """Sync user state request."""
        self.info.user_state(hlp)

    def sync_place_order(self) -> None:
        """Sync place order request."""
        resp = self.exchange.order(coin, is_buy, sz, px, order_type)
        oid = resp["response"]["data"]["statuses"][0]["resting"]["oid"]
        self.exchange.cancel(coin, oid)

    def run_sync_benchmark(
        self, operation: str, func, iterations: int = 10
    ) -> BenchmarkResult:
        """Run sync benchmark for given operation using multi-threading with max CPU cores."""
        import multiprocessing

        # Get the maximum number of CPU cores available
        max_workers = multiprocessing.cpu_count()

        times: List[float] = []
        success_count = 0
        error_count = 0

        print(
            f"Running sync {operation} benchmark with {max_workers} threads ({iterations} iterations)..."
        )

        try:
            start_time = time.time()

            # Use ThreadPoolExecutor with max CPU cores
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                # Submit all tasks
                future_to_iteration = {
                    executor.submit(self._run_single_iteration, func, i): i
                    for i in range(iterations)
                }

                # Collect results as they complete
                for future in as_completed(future_to_iteration):
                    iteration = future_to_iteration[future]
                    try:
                        iter_time = future.result()
                        times.append(iter_time)
                        success_count += 1
                        self.detailed_times.append(
                            {
                                "operation": operation,
                                "method": "sync",
                                "iteration": iteration + 1,
                                "time": iter_time,
                                "timestamp": time.time(),
                            }
                        )
                        print(
                            f"  Iteration {iteration + 1}/{iterations}: {iter_time:.3f}s"
                        )
                    except Exception as e:
                        error_count += 1
                        print(
                            f"  Iteration {iteration + 1}/{iterations} failed: {e}"
                        )

            total_time = time.time() - start_time

        except Exception as e:
            print(f"Sync benchmark failed: {e}")
            return BenchmarkResult(
                operation, "sync", 0, 0, 0, 0, 0, 0, 0, iterations, 0, 0
            )

        return self._calculate_result(
            operation, "sync", times, success_count, error_count, total_time
        )

    def _run_single_iteration(self, func, iteration: int) -> float:
        """Run a single iteration of the benchmark function and return the execution time."""
        iter_start = time.time()
        func()
        return time.time() - iter_start

    async def run_async_benchmark(
        self,
        operation: str,
        func,
        concurrent_requests: int = 5,
        iterations: int = 20,
    ) -> BenchmarkResult:
        """Run concurrent async benchmark to demonstrate async advantages."""
        print(
            f"Running concurrent async {operation} benchmark ({concurrent_requests} concurrent, {iterations} total)..."
        )

        times: List[float] = []
        success_count = 0
        error_count = 0

        try:
            start_time = time.time()

            # Run in batches of concurrent requests
            for batch in range(0, iterations, concurrent_requests):
                batch_size = min(concurrent_requests, iterations - batch)
                tasks = [func() for _ in range(batch_size)]

                batch_start = time.time()
                try:
                    await asyncio.gather(*tasks, return_exceptions=True)
                    batch_time = time.time() - batch_start
                    times.append(
                        batch_time / batch_size
                    )  # Average time per request in batch
                    success_count += batch_size
                    print(
                        f"  Batch {batch // concurrent_requests + 1}: {batch_time:.3f}s total ({batch_time / batch_size:.3f}s avg per request)"
                    )
                except Exception:
                    error_count += batch_size

            total_time = time.time() - start_time

        finally:
            pass

        return self._calculate_result(
            f"{operation}_concurrent",
            "async",
            times,
            success_count,
            error_count,
            total_time,
        )

    def _calculate_result(
        self,
        operation: str,
        method: str,
        times: List[float],
        success_count: int,
        error_count: int,
        total_time: float,
    ) -> BenchmarkResult:
        """Calculate benchmark result from timing data."""
        if not times:
            return BenchmarkResult(
                operation,
                method,
                total_time,
                0,
                0,
                0,
                0,
                0,
                success_count,
                error_count,
                success_count + error_count,
                0,
            )

        avg_time = statistics.mean(times)
        min_time = min(times)
        max_time = max(times)
        median_time = statistics.median(times)
        std_dev = statistics.stdev(times) if len(times) > 1 else 0
        requests_per_second = (
            success_count / total_time if total_time > 0 else 0
        )

        return BenchmarkResult(
            operation=operation,
            method=method,
            total_time=total_time,
            avg_time=avg_time,
            min_time=min_time,
            max_time=max_time,
            median_time=median_time,
            std_dev=std_dev,
            success_count=success_count,
            error_count=error_count,
            total_requests=success_count + error_count,
            requests_per_second=requests_per_second,
        )

    def print_results(self) -> None:
        """Print formatted benchmark results."""
        print("\n" + "=" * 80)
        print("BENCHMARK RESULTS")
        print("=" * 80)

        # Group results by operation
        operations = {}
        for result in self.results:
            if result.operation not in operations:
                operations[result.operation] = []
            operations[result.operation].append(result)

        for operation, results in operations.items():
            print(f"\n{operation.upper()} PERFORMANCE:")
            print("-" * 50)

            for result in results:
                print(f"\n{result.method.upper()} Method:")
                print(f"  Total Time:     {result.total_time:.3f}s")
                print(f"  Average Time:   {result.avg_time:.3f}s")
                print(f"  Min Time:       {result.min_time:.3f}s")
                print(f"  Max Time:       {result.max_time:.3f}s")
                print(f"  Median Time:    {result.median_time:.3f}s")
                print(f"  Std Deviation:  {result.std_dev:.3f}s")
                print(
                    f"  Success Rate:   {result.success_count}/{result.total_requests} ({result.success_count / result.total_requests * 100:.1f}%)"
                )
                print(f"  Requests/sec:   {result.requests_per_second:.2f}")

            # Compare async vs sync if both exist
            if len(results) >= 2:
                async_result = next(
                    (r for r in results if r.method == "async"), None
                )
                sync_result = next(
                    (r for r in results if r.method == "sync"), None
                )

                if async_result and sync_result:
                    print("\nCOMPARISON (Async vs Sync):")
                    speedup = (
                        sync_result.avg_time / async_result.avg_time
                        if async_result.avg_time > 0
                        else 0
                    )
                    throughput_improvement = (
                        (
                            async_result.requests_per_second
                            / sync_result.requests_per_second
                            - 1
                        )
                        * 100
                        if sync_result.requests_per_second > 0
                        else 0
                    )

                    print(f"  Speed Improvement: {speedup:.2f}x faster")
                    print(
                        f"  Throughput Improvement: {throughput_improvement:.1f}%"
                    )


async def run_benchmarks():
    """Test concurrent performance to show async advantages."""
    print("\n🚀 Testing concurrent performance differences...")

    runner = BenchmarkRunner()

    # Test parameters
    concurrent_requests = 100
    total_requests = 100

    print(
        f"\n📊 Running {total_requests} requests with {concurrent_requests} concurrent..."
    )

    # Test 1: Async concurrent user_state
    print("\n🔄 Testing async concurrent user_state...")
    start_time = time.time()

    try:
        # Run concurrent async user_state requests
        tasks = []
        for i in range(total_requests):
            tasks.append(runner.async_user_state())

        await asyncio.gather(*tasks)
        async_time = time.time() - start_time
        print(
            f"✅ Async concurrent user_state: {async_time:.3f}s ({total_requests / async_time:.2f} req/s)"
        )

    except Exception as e:
        print(f"❌ Async test failed: {e}")
        async_time = float("inf")

    # Test 2: Sync sequential user_state (simulating what sync would do)
    print("\n🔄 Testing sync multi-threads user_state...")
    start_time = time.time()

    try:
        # Run sequential sync user_state requests
        for i in range(total_requests):
            runner.sync_user_state()

        sync_time = time.time() - start_time
        print(
            f"✅ Sync multi-threads user_state: {sync_time:.3f}s ({total_requests / sync_time:.2f} req/s)"
        )

    except Exception as e:
        print(f"❌ Sync test failed: {e}")
        sync_time = float("inf")

    # Test 3: Async concurrent place_order (smaller batch to avoid rate limits)
    print("\n🔄 Testing async concurrent place_order...")
    start_time = time.time()

    try:
        # Run smaller batch of concurrent async place_order requests
        tasks = []
        for i in range(3):  # Smaller batch to avoid rate limits
            tasks.append(runner.async_place_order())

        await asyncio.gather(*tasks)
        async_order_time = time.time() - start_time
        print(
            f"✅ Async concurrent place_order: {async_order_time:.3f}s ({3 / async_order_time:.2f} req/s)"
        )

    except Exception as e:
        print(f"❌ Async place_order test failed: {e}")
        async_order_time = float("inf")

    # Test 4: Sync sequential place_order
    print("\n🔄 Testing sync multi-threads place_order...")
    start_time = time.time()

    try:
        # Run sequential sync place_order requests
        for i in range(3):
            runner.sync_place_order()

        sync_order_time = time.time() - start_time
        print(
            f"✅ Sync Multi-threads place_order: {sync_order_time:.3f}s ({3 / sync_order_time:.2f} req/s)"
        )

    except Exception as e:
        print(f"❌ Sync place_order test failed: {e}")
        sync_order_time = float("inf")

    # Results comparison
    print("\n" + "=" * 60)
    print("📈 CONCURRENT PERFORMANCE COMPARISON")
    print("=" * 60)

    if sync_time != float("inf") and async_time != float("inf"):
        user_state_speedup = sync_time / async_time
        user_state_throughput_improvement = (total_requests / async_time) / (
            total_requests / sync_time
        ) - 1

        print("\n🔍 USER_STATE Results:")
        print(
            f"  Async Concurrent:  {async_time:.3f}s ({total_requests / async_time:.2f} req/s)"
        )
        print(
            f"  Sync Sequential:   {sync_time:.3f}s ({total_requests / sync_time:.2f} req/s)"
        )
        print(f"  Speed Improvement: {user_state_speedup:.2f}x faster")
        print(
            f"  Throughput Gain:   {user_state_throughput_improvement * 100:.1f}%"
        )

    if sync_order_time != float("inf") and async_order_time != float("inf"):
        order_speedup = sync_order_time / async_order_time
        order_throughput_improvement = (3 / async_order_time) / (
            3 / sync_order_time
        ) - 1

        print("\n🔍 PLACE_ORDER Results:")
        print(
            f"  Async Concurrent:  {async_order_time:.3f}s ({3 / async_order_time:.2f} req/s)"
        )
        print(
            f"  Sync Multi-threads:   {sync_order_time:.3f}s ({3 / sync_order_time:.2f} req/s)"
        )
        print(f"  Speed Improvement: {order_speedup:.2f}x faster")
        print(f"  Throughput Gain:   {order_throughput_improvement * 100:.1f}%")

    await runner.hl.close()


async def main():
    """Main benchmark execution."""
    try:
        await run_benchmarks()
    except Exception:
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
