"""
Simple visualization script for Async-Hyper benchmark results.
"""

from importlib import import_module
import os
import time
import asyncio
from typing import Any, cast

from benchmarks import BenchmarkRunner  # type: ignore

sns = cast(Any, import_module("seaborn"))
plt = cast(Any, import_module("matplotlib.pyplot"))

# Set style for clean visualization
plt.style.use("seaborn-v0_8")
sns.set_palette("husl")


async def run_benchmarks_and_visualize() -> None:
    """Run actual benchmarks and create visualization from real data."""

    print("🚀 Running Async-Hyper benchmarks...")

    # Initialize benchmark runner
    runner = BenchmarkRunner()

    # Test parameters
    concurrent_requests = 100
    total_requests = 100

    print(
        f" Running {total_requests} requests with {concurrent_requests} concurrent..."
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
        async_rps = total_requests / async_time
        print(
            f"✅ Async concurrent user_state: {async_time:.3f}s ({async_rps:.2f} req/s)"
        )

    except Exception as e:
        print(f"❌ Async test failed: {e}")
        async_time = float("inf")
        async_rps = 0

    # Test 2: Sync sequential user_state
    print("\n🔄 Testing sync sequential user_state...")
    start_time = time.time()

    try:
        # Run sequential sync user_state requests
        for i in range(total_requests):
            runner.sync_user_state()

        sync_time = time.time() - start_time
        sync_rps = total_requests / sync_time
        print(
            f"✅ Sync sequential user_state: {sync_time:.3f}s ({sync_rps:.2f} req/s)"
        )

    except Exception as e:
        print(f"❌ Sync test failed: {e}")
        sync_time = float("inf")
        sync_rps = 0

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
        async_order_rps = 3 / async_order_time
        print(
            f"✅ Async concurrent place_order: {async_order_time:.3f}s ({async_order_rps:.2f} req/s)"
        )

    except Exception as e:
        print(f"❌ Async place_order test failed: {e}")
        async_order_time = float("inf")
        async_order_rps = 0

    # Test 4: Sync sequential place_order
    print("\n🔄 Testing sync sequential place_order...")
    start_time = time.time()

    try:
        # Run sequential sync place_order requests
        for i in range(3):
            runner.sync_place_order()

        sync_order_time = time.time() - start_time
        sync_order_rps = 3 / sync_order_time
        print(
            f"✅ Sync sequential place_order: {sync_order_time:.3f}s ({sync_order_rps:.2f} req/s)"
        )

    except Exception as e:
        print(f"❌ Sync place_order test failed: {e}")
        sync_order_time = float("inf")
        sync_order_rps = 0

    # Calculate performance metrics
    user_state_speedup = (
        sync_time / async_time
        if async_time != float("inf") and sync_time != float("inf")
        else 0
    )
    user_state_throughput_improvement = (
        (async_rps / sync_rps - 1) * 100 if sync_rps > 0 else 0
    )

    order_speedup = (
        sync_order_time / async_order_time
        if async_order_time != float("inf") and sync_order_time != float("inf")
        else 0
    )
    order_throughput_improvement = (
        (async_order_rps / sync_order_rps - 1) * 100
        if sync_order_rps > 0
        else 0
    )

    # Print results
    print("\n" + "=" * 60)
    print("📈 CONCURRENT PERFORMANCE COMPARISON")
    print("=" * 60)

    if sync_time != float("inf") and async_time != float("inf"):
        print("\n USER_STATE Results:")
        print(f"  Async Concurrent:  {async_time:.3f}s ({async_rps:.2f} req/s)")
        print(f"  Sync Sequential:   {sync_time:.3f}s ({sync_rps:.2f} req/s)")
        print(f"  Speed Improvement: {user_state_speedup:.2f}x faster")
        print(f"  Throughput Gain:   {user_state_throughput_improvement:.1f}%")

    if sync_order_time != float("inf") and async_order_time != float("inf"):
        print("\n🔍 PLACE_ORDER Results:")
        print(
            f"  Async Concurrent:  {async_order_time:.3f}s ({async_order_rps:.2f} req/s)"
        )
        print(
            f"  Sync Sequential:   {sync_order_time:.3f}s ({sync_order_rps:.2f} req/s)"
        )
        print(f"  Speed Improvement: {order_speedup:.2f}x faster")
        print(f"  Throughput Gain:   {order_throughput_improvement:.1f}%")

    # Create visualization with real data
    try:
        create_visualization(
            async_time,
            sync_time,
            async_rps,
            sync_rps,
            user_state_speedup,
            user_state_throughput_improvement,
            async_order_time,
            sync_order_time,
            async_order_rps,
            sync_order_rps,
            order_speedup,
            order_throughput_improvement,
        )
    except Exception as e:
        print(f"❌ Error creating visualization: {e}")

    # Clean up
    await runner.hl.close()


def create_visualization(
    async_time: float,
    sync_time: float,
    async_rps: float,
    sync_rps: float,
    user_state_speedup: float,
    user_state_throughput_improvement: float,
    async_order_time: float,
    sync_order_time: float,
    async_order_rps: float,
    sync_order_rps: float,
    order_speedup: float,
    order_throughput_improvement: float,
) -> None:
    """Create visualization from real benchmark data."""

    # Create figure with subplots in one row
    fig, (ax1, ax2, ax3, ax4) = plt.subplots(1, 4, figsize=(20, 6))

    # 1. Response Time Comparison
    operations = ["USER_STATE", "PLACE_ORDER"]
    async_times = [async_time, async_order_time]
    sync_times = [sync_time, sync_order_time]

    x = range(len(operations))
    width = 0.35

    ax1.bar(
        [i - width / 2 for i in x], async_times, width, label="Async", alpha=0.8
    )
    ax1.bar(
        [i + width / 2 for i in x], sync_times, width, label="Sync", alpha=0.8
    )

    ax1.set_xlabel("Operation")
    ax1.set_ylabel("Time (seconds)")
    ax1.set_title("Response Time Comparison")
    ax1.set_xticks(x)
    ax1.set_xticklabels(operations)
    ax1.legend()
    ax1.set_yscale("log")  # Log scale due to large differences

    # Add value labels
    for i, (async_val, sync_val) in enumerate(zip(async_times, sync_times)):
        if async_val != float("inf"):
            ax1.text(
                i - width / 2,
                async_val,
                f"{async_val:.3f}s",
                ha="center",
                va="bottom",
                fontsize=9,
            )
        if sync_val != float("inf"):
            ax1.text(
                i + width / 2,
                sync_val,
                f"{sync_val:.3f}s",
                ha="center",
                va="bottom",
                fontsize=9,
            )

    # 2. Throughput Comparison
    async_rps_list = [async_rps, async_order_rps]
    sync_rps_list = [sync_rps, sync_order_rps]

    ax2.bar(
        [i - width / 2 for i in x],
        async_rps_list,
        width,
        label="Async",
        alpha=0.8,
    )
    ax2.bar(
        [i + width / 2 for i in x],
        sync_rps_list,
        width,
        label="Sync",
        alpha=0.8,
    )

    ax2.set_xlabel("Operation")
    ax2.set_ylabel("Requests per Second")
    ax2.set_title("Throughput Comparison")
    ax2.set_xticks(x)
    ax2.set_xticklabels(operations)
    ax2.legend()

    # Add value labels
    for i, (async_val, sync_val) in enumerate(
        zip(async_rps_list, sync_rps_list)
    ):
        if async_val > 0:
            ax2.text(
                i - width / 2,
                async_val,
                f"{async_val:.1f}",
                ha="center",
                va="bottom",
                fontsize=9,
            )
        if sync_val > 0:
            ax2.text(
                i + width / 2,
                sync_val,
                f"{sync_val:.2f}",
                ha="center",
                va="bottom",
                fontsize=9,
            )

    # 3. Speed Improvement (x times faster)
    speed_improvements = [user_state_speedup, order_speedup]
    colors = ["#2E8B57", "#FF6347"]  # Green and Red

    bars = ax3.bar(operations, speed_improvements, color=colors, alpha=0.8)
    ax3.set_ylabel("Speed Improvement (x faster)")
    ax3.set_title("Performance Gains")
    ax3.set_yscale("log")

    # Add value labels
    for bar, value in zip(bars, speed_improvements):
        if value > 0:
            height = bar.get_height()
            ax3.text(
                bar.get_x() + bar.get_width() / 2.0,
                height,
                f"{value:.2f}x",
                ha="center",
                va="bottom",
                fontsize=10,
                fontweight="bold",
            )

    # 4. Throughput Gain Percentage
    throughput_gains = [
        user_state_throughput_improvement,
        order_throughput_improvement,
    ]

    bars = ax4.bar(operations, throughput_gains, color=colors, alpha=0.8)
    ax4.set_ylabel("Throughput Gain (%)")
    ax4.set_title("Throughput Improvements")

    # Add value labels
    for bar, value in zip(bars, throughput_gains):
        if value > 0:
            height = bar.get_height()
            ax4.text(
                bar.get_x() + bar.get_width() / 2.0,
                height,
                f"{value:.1f}%",
                ha="center",
                va="bottom",
                fontsize=10,
                fontweight="bold",
            )

    # Add summary text
    fig.suptitle(
        "Async-Hyper Benchmark Results (Live Data)",
        fontsize=16,
        fontweight="bold",
        y=0.95,
    )

    # Add summary statistics
    summary_text = (
        f"USER_STATE: Async is {user_state_speedup:.1f}x faster with {user_state_throughput_improvement:.1f}% throughput gain\n"
        f"PLACE_ORDER: Async is {order_speedup:.1f}x faster with {order_throughput_improvement:.1f}% throughput gain"
    )

    fig.text(
        0.5,
        0.02,
        summary_text,
        ha="center",
        fontsize=12,
        bbox=dict(boxstyle="round,pad=0.5", facecolor="lightgray", alpha=0.8),
    )

    plt.tight_layout()

    # Save the visualization
    os.makedirs("./benchmarks", exist_ok=True)
    filename = "./benchmarks/benchmarks.png"
    plt.savefig(filename, dpi=300, bbox_inches="tight")
    print(f"📊 Live benchmark visualization saved as: {filename}")

    plt.show()


async def main():
    """Main execution function."""
    try:
        await run_benchmarks_and_visualize()
    except Exception as e:
        print(f"❌ Error running benchmarks: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
