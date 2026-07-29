from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import subprocess
import sys
import zipfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TypedDict, cast


class BenchmarkFailure(RuntimeError):
    """The benchmark did not produce trustworthy comparable samples."""


@dataclass(frozen=True, slots=True)
class BenchmarkCommand:
    name: str
    argv: tuple[str, ...]
    cwd: Path | None = None
    env: Mapping[str, str] | None = None


class Summary(TypedDict):
    median_ns: float
    mad_ns: float
    p95_ns: float


class Comparison(TypedDict):
    baseline: Summary
    candidate: Summary
    candidate_delta_percent: float


class BenchmarkReport(TypedDict):
    schema_version: int
    rounds: int
    warmups: int
    results: dict[str, Comparison]


BASELINE_WHEEL_PROBE = r"""
import gc
import json
import os
from time import perf_counter_ns

from eth_account import Account

from async_hyperliquid.utils.miscs import round_float, round_px
from async_hyperliquid.utils.signing import (
    encode_order as encode_wire_order,
    orders_to_action,
    sign_action,
)
from async_hyperliquid.utils.types import LimitTif, limit_order_type

iterations = int(os.environ["BENCH_ITERATIONS"])
account = Account.from_key("0x" + "11" * 32)
order = {
    "asset": 0,
    "is_buy": True,
    "px": 100_000.0,
    "sz": 0.001,
    "ro": False,
    "order_type": limit_order_type(LimitTif.GTC),
    "cloid": None,
}
orders = [dict(order, asset=index) for index in range(10)]


def prepare_order(order):
    rounded = {
        **order,
        "px": round_px(order["px"], 1),
        "sz": round_float(order["sz"], 5),
    }
    return encode_wire_order(rounded)


encoded_order = prepare_order(order)
single_action = orders_to_action([encoded_order])
batch_action = orders_to_action([prepare_order(item) for item in orders])


def measure(fn, count):
    for _ in range(max(10, count // 100)):
        fn()
    gc.collect()
    gc.disable()
    started = perf_counter_ns()
    try:
        for _ in range(count):
            fn()
    finally:
        elapsed = perf_counter_ns() - started
        gc.enable()
    return elapsed / count


results = {
    "prepare_order": measure(lambda: prepare_order(order), iterations),
    "prepare_batch_10": measure(
        lambda: orders_to_action([prepare_order(item) for item in orders]),
        max(100, iterations // 10),
    ),
    "sign_order": measure(
        lambda: sign_action(account, single_action, None, 1_750_000_000_000, True),
        max(100, iterations // 20),
    ),
    "sign_batch_10": measure(
        lambda: sign_action(account, batch_action, None, 1_750_000_000_000, True),
        max(100, iterations // 20),
    ),
}
print(json.dumps(results, sort_keys=True))
"""

CANDIDATE_WHEEL_PROBE = r"""
import gc
import json
import os
from time import perf_counter_ns

from eth_account import Account

from async_hyperliquid._signing import encode_order, sign_exchange_action
from async_hyperliquid.types import LimitOrder, Network, Side

iterations = int(os.environ["BENCH_ITERATIONS"])
account = Account.from_key("0x" + "11" * 32)
order = LimitOrder("BTC", Side.BUY, 0.001, 100_000.0)
orders = tuple(
    LimitOrder(f"ASSET-{index}", Side.BUY, 0.001, 100_000.0)
    for index in range(10)
)
encoded_order = encode_order(order, asset=0, size_decimals=5)
single_action = {
    "type": "order",
    "orders": [encoded_order],
    "grouping": "na",
}
batch_action = {
    "type": "order",
    "orders": [
        encode_order(item, asset=index, size_decimals=5)
        for index, item in enumerate(orders)
    ],
    "grouping": "na",
}


def measure(fn, count):
    for _ in range(max(10, count // 100)):
        fn()
    gc.collect()
    gc.disable()
    started = perf_counter_ns()
    try:
        for _ in range(count):
            fn()
    finally:
        elapsed = perf_counter_ns() - started
        gc.enable()
    return elapsed / count


results = {
    "prepare_order": measure(
        lambda: encode_order(order, asset=0, size_decimals=5),
        iterations,
    ),
    "prepare_batch_10": measure(
        lambda: {
            "type": "order",
            "orders": [
                encode_order(item, asset=index, size_decimals=5)
                for index, item in enumerate(orders)
            ],
            "grouping": "na",
        },
        max(100, iterations // 10),
    ),
    "sign_order": measure(
        lambda: sign_exchange_action(
            account,
            single_action,
            None,
            1_750_000_000_000,
            Network.MAINNET.signature_source,
        ),
        max(100, iterations // 20),
    ),
    "sign_batch_10": measure(
        lambda: sign_exchange_action(
            account,
            batch_action,
            None,
            1_750_000_000_000,
            Network.MAINNET.signature_source,
        ),
        max(100, iterations // 20),
    ),
}
print(json.dumps(results, sort_keys=True))
"""


def alternate_candidates(
    baseline: BenchmarkCommand, candidate: BenchmarkCommand, *, rounds: int
) -> tuple[tuple[BenchmarkCommand, BenchmarkCommand], ...]:
    if rounds < 1:
        raise ValueError("rounds must be positive")
    return tuple(
        (baseline, candidate) if index % 2 == 0 else (candidate, baseline)
        for index in range(rounds)
    )


def summarize(samples: Sequence[float]) -> Summary:
    if not samples:
        raise ValueError("samples must not be empty")
    ordered = sorted(samples)
    median = statistics.median(ordered)
    deviations = [abs(sample - median) for sample in ordered]
    rank = max(0, math.ceil(0.95 * len(ordered)) - 1)
    return {
        "median_ns": float(median),
        "mad_ns": float(statistics.median(deviations)),
        "p95_ns": float(ordered[rank]),
    }


def _parse_result(command: BenchmarkCommand, stdout: str) -> dict[str, float]:
    lines = [line for line in stdout.splitlines() if line.strip()]
    if not lines:
        raise BenchmarkFailure(f"{command.name} produced no JSON result")
    try:
        decoded = cast(object, json.loads(lines[-1]))
    except json.JSONDecodeError as error:
        raise BenchmarkFailure(
            f"{command.name} produced invalid JSON: {error}"
        ) from error
    if not isinstance(decoded, dict) or not decoded:
        raise BenchmarkFailure(f"{command.name} produced an empty result")

    result: dict[str, float] = {}
    for name, value in decoded.items():
        if (
            not isinstance(name, str)
            or isinstance(value, bool)
            or not isinstance(value, int | float)
            or not math.isfinite(value)
            or value <= 0
        ):
            raise BenchmarkFailure(
                f"{command.name} produced invalid sample {name!r}={value!r}"
            )
        result[name] = float(value)
    return result


def _run(command: BenchmarkCommand) -> dict[str, float]:
    env = os.environ.copy()
    if command.env is not None:
        env.update(command.env)
    completed = subprocess.run(
        command.argv,
        cwd=command.cwd,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise BenchmarkFailure(
            f"{command.name} failed with exit code {completed.returncode}: {detail}"
        )
    return _parse_result(command, completed.stdout)


def run_ab_ba(
    baseline: BenchmarkCommand,
    candidate: BenchmarkCommand,
    *,
    rounds: int,
    warmups: int,
) -> BenchmarkReport:
    if warmups < 0:
        raise ValueError("warmups must not be negative")
    for _ in range(warmups):
        _run(baseline)
        _run(candidate)

    samples: dict[str, dict[str, list[float]]] = {baseline.name: {}, candidate.name: {}}
    operation_names: set[str] | None = None
    for pair in alternate_candidates(baseline, candidate, rounds=rounds):
        for command in pair:
            result = _run(command)
            names = set(result)
            if operation_names is None:
                operation_names = names
            elif names != operation_names:
                raise BenchmarkFailure(
                    f"{command.name} operation set does not match the baseline"
                )
            for name, value in result.items():
                samples[command.name].setdefault(name, []).append(value)

    assert operation_names is not None
    comparisons: dict[str, Comparison] = {}
    for operation in sorted(operation_names):
        baseline_summary = summarize(samples[baseline.name][operation])
        candidate_summary = summarize(samples[candidate.name][operation])
        comparisons[operation] = {
            "baseline": baseline_summary,
            "candidate": candidate_summary,
            "candidate_delta_percent": (
                candidate_summary["median_ns"] / baseline_summary["median_ns"] - 1
            )
            * 100,
        }
    return {
        "schema_version": 1,
        "rounds": rounds,
        "warmups": warmups,
        "results": comparisons,
    }


def _wheel_command(
    name: str, wheel: Path, destination: Path, *, iterations: int, probe: str
) -> BenchmarkCommand:
    if wheel.suffix != ".whl" or not wheel.is_file():
        raise BenchmarkFailure(f"{name} wheel does not exist: {wheel}")
    destination.mkdir(parents=True)
    with zipfile.ZipFile(wheel) as archive:
        members = archive.infolist()
        for member in members:
            path = Path(member.filename)
            if path.is_absolute() or ".." in path.parts:
                raise BenchmarkFailure(
                    f"{name} has unsafe wheel member: {member.filename}"
                )
        if not any(
            Path(member.filename).parts == ("async_hyperliquid", "__init__.py")
            for member in members
        ):
            raise BenchmarkFailure(f"{name} wheel does not contain async_hyperliquid")
        archive.extractall(destination)
    bootstrap = (
        f"import pathlib,sys;sys.path.insert(0, {str(destination)!r});"
        "import async_hyperliquid as package;"
        "assert pathlib.Path(package.__file__).resolve().is_relative_to("
        f"pathlib.Path({str(destination)!r}).resolve());"
        f"exec({probe!r})"
    )
    return BenchmarkCommand(
        name=name,
        argv=(sys.executable, "-I", "-c", bootstrap),
        cwd=destination,
        env={"BENCH_ITERATIONS": str(iterations)},
    )


def compare_wheels(
    baseline_wheel: Path,
    candidate_wheel: Path,
    *,
    rounds: int,
    warmups: int,
    iterations: int,
) -> BenchmarkReport:
    with TemporaryDirectory(prefix="async-hyperliquid-benchmark-") as temp:
        root = Path(temp)
        baseline = _wheel_command(
            "baseline",
            baseline_wheel,
            root / "baseline",
            iterations=iterations,
            probe=BASELINE_WHEEL_PROBE,
        )
        candidate = _wheel_command(
            "candidate",
            candidate_wheel,
            root / "candidate",
            iterations=iterations,
            probe=CANDIDATE_WHEEL_PROBE,
        )
        return run_ab_ba(baseline, candidate, rounds=rounds, warmups=warmups)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare installed wheel hot paths using alternating AB/BA rounds."
    )
    parser.add_argument("--baseline-wheel", type=Path, required=True)
    parser.add_argument("--candidate-wheel", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--rounds", type=int, default=7)
    parser.add_argument("--warmups", type=int, default=1)
    parser.add_argument("--iterations", type=int, default=5_000)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report = compare_wheels(
        args.baseline_wheel,
        args.candidate_wheel,
        rounds=args.rounds,
        warmups=args.warmups,
        iterations=args.iterations,
    )
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output is None:
        print(rendered, end="")
    else:
        args.output.write_text(rendered)


if __name__ == "__main__":
    main()
