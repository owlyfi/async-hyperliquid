"""Compare single-order cancel latency with fast=False and fast=True on testnet.

Each round places ``--orders`` resting BTC ALO buys far below mid in one batch,
then cancels them one at a time, alternating fast=False / fast=True. The method
that goes first swaps every round. Only the cancel request itself is timed;
pacing sleeps are excluded. Any non-success cancel invalidates the run.
"""

from __future__ import annotations

import argparse
import asyncio
import math
import os
import statistics
import sys
from collections.abc import Sequence
from pathlib import Path
from time import perf_counter_ns

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from async_hyperliquid import AsyncHyperliquid
from async_hyperliquid.types import (
    CancelOrder,
    CancelOrderResponse,
    Network,
    PlaceOrderRequest,
    TimeInForce,
    limit_order_type,
)
from benchmarks.live.models import MIN_INTERVAL_NS, BenchmarkFailure
from benchmarks.live.pacing import WeightedPacer
from benchmarks.live.preflight import Credentials, validate_roles

COIN = "BTC"
NOTIONAL_USDC = 12
PRICE_RATIO = 0.9


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rounds", type=int, default=30)
    parser.add_argument("--warmups", type=int, default=3)
    parser.add_argument("--orders", type=int, default=10, help="even, per round")
    parser.add_argument("--interval-ms", type=int, default=250)
    args = parser.parse_args(argv)
    if args.rounds < 1 or args.warmups < 0:
        parser.error("--rounds must be positive and --warmups non-negative")
    if args.orders < 2 or args.orders % 2:
        parser.error("--orders must be an even number >= 2")
    if args.interval_ms * 1_000_000 < MIN_INTERVAL_NS:
        parser.error(f"--interval-ms must be at least {MIN_INTERVAL_NS // 1_000_000}")
    return args


def fast_plan(round_index: int, count: int) -> tuple[bool, ...]:
    """Alternate fast flags; the first method swaps every round for fairness."""
    first = round_index % 2 == 1
    return tuple(first if i % 2 == 0 else not first for i in range(count))


def summarize(samples_ns: Sequence[int]) -> dict[str, float]:
    ms = sorted(sample / 1_000_000 for sample in samples_ns)
    cuts = statistics.quantiles(ms, n=100, method="inclusive")
    return {
        "n": len(ms),
        "mean": statistics.fmean(ms),
        "p50": statistics.median(ms),
        "p90": cuts[89],
        "p99": cuts[98],
        "min": ms[0],
        "max": ms[-1],
    }


def format_table(samples: dict[bool, list[int]]) -> str:
    columns = ("n", "mean", "p50", "p90", "p99", "min", "max")
    lines = [f"{'method':<12}" + "".join(f"{name:>10}" for name in columns)]
    for fast in (False, True):
        stats = summarize(samples[fast])
        cells = "".join(
            f"{stats[name]:>10d}" if name == "n" else f"{stats[name]:>10.2f}"
            for name in columns
        )
        lines.append(f"{f'fast={fast}':<12}" + cells)
    return "\n".join(lines) + "\n(latency in ms)"


def _cancelled(response: CancelOrderResponse) -> bool:
    return response["status"] == "ok" and response["response"]["data"]["statuses"] == [
        "success"
    ]


async def _place_round(
    client: AsyncHyperliquid, count: int, size_decimals: int
) -> list[int]:
    px = await client.info.mid_price(COIN) * PRICE_RATIO
    step = 10**size_decimals
    sz = math.ceil(NOTIONAL_USDC / px * step) / step
    order: PlaceOrderRequest = {
        "coin": COIN,
        "is_buy": True,
        "sz": sz,
        "px": px,
        "is_market": False,
        "order_type": limit_order_type(TimeInForce.ALO),
    }
    response = await client.place_orders([order.copy() for _ in range(count)])
    if response["status"] != "ok":
        raise BenchmarkFailure(f"placement failed: {response['response']}")
    oids: list[int] = []
    for status in response["response"]["data"]["statuses"]:
        resting = status.get("resting") if isinstance(status, dict) else None
        if not isinstance(resting, dict):
            raise BenchmarkFailure(f"order did not rest: {status!r}")
        oids.append(resting["oid"])
    return oids


async def _run(args: argparse.Namespace, credentials: Credentials) -> str:
    pacer = WeightedPacer(interval_ns=args.interval_ms * 1_000_000)
    samples: dict[bool, list[int]] = {False: [], True: []}
    async with AsyncHyperliquid(
        credentials.master_address,
        credentials.signing_key,
        vault_address=credentials.subaccount_address,
        network=Network.TESTNET,
    ) as client:
        await client.info.refresh_metadata()
        validate_roles(
            credentials.master_address,
            await client.info.user_role(credentials.api_wallet_address),
            await client.info.user_role(credentials.subaccount_address),
        )
        size_decimals = await client.info.size_decimals(COIN)
        pending: list[int] = []
        try:
            for round_index in range(args.warmups + args.rounds):
                await pacer.wait(weight=1)
                pending = await _place_round(client, args.orders, size_decimals)
                plan = fast_plan(round_index, len(pending))
                for oid, fast in zip(tuple(pending), plan, strict=True):
                    await pacer.wait(weight=1)
                    start = perf_counter_ns()
                    response = await client.cancel_order(
                        CancelOrder(COIN, oid), fast=fast
                    )
                    elapsed = perf_counter_ns() - start
                    if not _cancelled(response):
                        raise BenchmarkFailure(f"cancel failed: {response!r}")
                    pending.remove(oid)
                    if round_index >= args.warmups:
                        samples[fast].append(elapsed)
        finally:
            if pending:
                await client.cancel_orders(tuple(CancelOrder(COIN, o) for o in pending))
    return format_table(samples)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    from dotenv import load_dotenv

    load_dotenv(Path(".env.local"), override=False)
    try:
        credentials = Credentials.from_environ(os.environ)
        print(asyncio.run(_run(args, credentials)))
    except BenchmarkFailure as error:
        print(f"fast-cancel benchmark failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
