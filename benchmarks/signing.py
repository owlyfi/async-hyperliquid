"""Parity-gated Hyperliquid signing benchmark; see ``benchmarks/README.md``."""

from __future__ import annotations

import argparse
import gc
import json
import math
import os
import statistics
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter_ns
from typing import Protocol, TypedDict, cast


class BenchmarkFailure(RuntimeError):
    """The benchmark did not produce trustworthy comparable samples."""


@dataclass(frozen=True, slots=True)
class ProviderCommand:
    name: str
    argv: tuple[str, ...]
    cwd: Path | None = None
    env: Mapping[str, str] | None = None


class Summary(TypedDict):
    median_ns: float
    mad_ns: float
    p95_ns: float
    ops_per_second: float


class SigningBenchmarkReport(TypedDict):
    schema_version: int
    rounds: int
    warmups: int
    providers: list[str]
    results: dict[str, dict[str, Summary]]


class _CcxtOrder(TypedDict):
    symbol: str
    type: str
    side: str
    amount: str
    price: str
    params: dict[str, str]


class _Probe(Protocol):
    def __call__(self) -> object: ...


_PROVIDERS = ("ccxt", "sdk", "async-hyperliquid")
_TEST_KEY = "0x" + "11" * 32
_NONCE = 1_750_000_000_000
_EXPECTED_SINGLE_HASH = bytes.fromhex(
    "80ee1af6940bba00da597b83f01bbbb2aa88b10cd0b61aa4be1dede7bef84856"
)
_EXPECTED_SINGLE_SIGNATURE = {
    "r": "0x78e220566a337906ef346c4047d45b27446058978f84e7a944311a33ed58e98a",
    "s": "0x71715923504615a8452afd9744c613dfdb0e8ff6af925e3c134255891d05eff8",
    "v": 28,
}
_EXPECTED_BATCH_SIGNATURE = {
    "r": "0xd4961f3ab0f52168b33a570edaf45475b59ec449004290437aab806156bd08f6",
    "s": "0x35999891a61433b22bc100154001551de9d6819ec6df03c31cbc51c44f9dbfd1",
    "v": 27,
}
_SINGLE_ACTION = {
    "type": "order",
    "orders": [
        {
            "a": 0,
            "b": True,
            "p": "100000",
            "s": "0.01",
            "r": False,
            "t": {"limit": {"tif": "Gtc"}},
        }
    ],
    "grouping": "na",
}
_BATCH_ACTION = {
    "type": "order",
    "orders": [
        {
            "a": asset,
            "b": True,
            "p": "100000",
            "s": "0.01",
            "r": False,
            "t": {"limit": {"tif": "Gtc"}},
        }
        for asset in range(10)
    ],
    "grouping": "na",
}


def rotate_providers(
    providers: Sequence[ProviderCommand], *, rounds: int
) -> tuple[tuple[ProviderCommand, ...], ...]:
    if rounds < 1:
        raise ValueError("rounds must be positive")
    if not providers:
        raise ValueError("providers must not be empty")
    items = tuple(providers)
    return tuple(
        items[offset:] + items[:offset]
        for round_index in range(rounds)
        for offset in (round_index % len(items),)
    )


def summarize(samples: Sequence[float]) -> Summary:
    if not samples:
        raise ValueError("samples must not be empty")
    ordered = sorted(samples)
    median = float(statistics.median(ordered))
    deviations = [abs(sample - median) for sample in ordered]
    rank = max(0, math.ceil(0.95 * len(ordered)) - 1)
    return {
        "median_ns": median,
        "mad_ns": float(statistics.median(deviations)),
        "p95_ns": float(ordered[rank]),
        "ops_per_second": 1_000_000_000 / median,
    }


def _parse_result(command: ProviderCommand, stdout: str) -> dict[str, float]:
    lines = [line for line in stdout.splitlines() if line.strip()]
    if not lines:
        raise BenchmarkFailure(f"{command.name} produced no JSON result")
    try:
        decoded = cast(object, json.loads(lines[-1]))
    except json.JSONDecodeError as error:
        raise BenchmarkFailure(
            f"{command.name} produced invalid benchmark JSON"
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
            raise BenchmarkFailure(f"{command.name} produced an invalid sample")
        result[name] = float(value)
    return result


def _run(command: ProviderCommand) -> dict[str, float]:
    env = os.environ.copy()
    if command.env is not None:
        env.update(command.env)
    try:
        completed = subprocess.run(
            command.argv,
            cwd=command.cwd,
            env=env,
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as error:
        raise BenchmarkFailure(f"{command.name} could not start") from error
    if completed.returncode:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise BenchmarkFailure(
            f"{command.name} failed with exit code {completed.returncode}: {detail}"
        )
    return _parse_result(command, completed.stdout)


def run_benchmark(
    providers: Sequence[ProviderCommand], *, rounds: int, warmups: int
) -> SigningBenchmarkReport:
    if warmups < 0:
        raise ValueError("warmups must not be negative")
    provider_names = [provider.name for provider in providers]
    if len(set(provider_names)) != len(provider_names):
        raise ValueError("provider names must be unique")
    schedule = rotate_providers(providers, rounds=rounds)

    for _ in range(warmups):
        for provider in providers:
            _run(provider)

    samples: dict[str, dict[str, list[float]]] = {
        provider.name: {} for provider in providers
    }
    operation_names: set[str] | None = None
    for ordered_providers in schedule:
        for provider in ordered_providers:
            result = _run(provider)
            names = set(result)
            if operation_names is None:
                operation_names = names
            elif names != operation_names:
                raise BenchmarkFailure(
                    f"{provider.name} operation set does not match other providers"
                )
            for name, value in result.items():
                samples[provider.name].setdefault(name, []).append(value)

    if operation_names is None:
        raise BenchmarkFailure("benchmark produced no operations")
    results: dict[str, dict[str, Summary]] = {}
    for operation in sorted(operation_names):
        results[operation] = {
            provider.name: summarize(samples[provider.name][operation])
            for provider in providers
        }
    return {
        "schema_version": 1,
        "rounds": rounds,
        "warmups": warmups,
        "providers": provider_names,
        "results": results,
    }


def _measure(probe: _Probe, iterations: int) -> float:
    for _ in range(max(10, iterations // 100)):
        probe()
    gc.collect()
    gc.disable()
    started = perf_counter_ns()
    try:
        for _ in range(iterations):
            probe()
    finally:
        elapsed = perf_counter_ns() - started
        gc.enable()
    return elapsed / iterations


def _validate_probe(
    provider: str,
    *,
    action_hash: bytes,
    single_signature: object,
    batch_signature: object,
    single_payload: Mapping[str, object],
    batch_payload: Mapping[str, object],
) -> None:
    if action_hash != _EXPECTED_SINGLE_HASH:
        raise BenchmarkFailure(f"{provider} action hash parity failed")
    if single_signature != _EXPECTED_SINGLE_SIGNATURE:
        raise BenchmarkFailure(f"{provider} single signature parity failed")
    if batch_signature != _EXPECTED_BATCH_SIGNATURE:
        raise BenchmarkFailure(f"{provider} batch signature parity failed")
    if (
        single_payload.get("action") != _SINGLE_ACTION
        or single_payload.get("signature") != _EXPECTED_SINGLE_SIGNATURE
    ):
        raise BenchmarkFailure(f"{provider} single payload parity failed")
    if (
        batch_payload.get("action") != _BATCH_ACTION
        or batch_payload.get("signature") != _EXPECTED_BATCH_SIGNATURE
    ):
        raise BenchmarkFailure(f"{provider} batch payload parity failed")


def _async_hyperliquid_probes() -> dict[str, Callable[[], object]]:
    from eth_account import Account

    from async_hyperliquid._encoding import encode_order
    from async_hyperliquid._signing import hash_action, sign_exchange_action
    from async_hyperliquid.types import (
        JsonObject,
        PlaceOrderRequest,
        TimeInForce,
        limit_order_type,
    )

    account = Account.from_key(_TEST_KEY)
    order: PlaceOrderRequest = {
        "coin": "BTC",
        "is_buy": True,
        "sz": 0.01,
        "px": 100_000.0,
        "is_market": False,
        "ro": False,
        "order_type": limit_order_type(TimeInForce.GTC),
    }
    orders: tuple[PlaceOrderRequest, ...] = tuple(
        cast(PlaceOrderRequest, {**order, "coin": f"ASSET-{asset}"})
        for asset in range(10)
    )

    def sign(action: JsonObject) -> object:
        return sign_exchange_action(account, action, None, _NONCE, "b")

    def payload_for(items: Sequence[PlaceOrderRequest]) -> dict[str, object]:
        action: JsonObject = {
            "type": "order",
            "orders": [
                encode_order(
                    item, asset=asset, size_decimals=5, is_spot=False, is_outcome=False
                )
                for asset, item in enumerate(items)
            ],
            "grouping": "na",
        }
        return {
            "action": action,
            "nonce": _NONCE,
            "signature": sign(action),
            "vaultAddress": None,
            "expiresAfter": None,
        }

    probes: dict[str, Callable[[], object]] = {
        "action_hash": lambda: hash_action(
            cast(JsonObject, _SINGLE_ACTION), None, _NONCE
        ),
        "sign_l1_single": lambda: sign(cast(JsonObject, _SINGLE_ACTION)),
        "sign_l1_batch_10": lambda: sign(cast(JsonObject, _BATCH_ACTION)),
        "build_payload_single": lambda: payload_for((order,)),
        "build_payload_batch_10": lambda: payload_for(orders),
    }
    _validate_probe(
        "async-hyperliquid",
        action_hash=cast(bytes, probes["action_hash"]()),
        single_signature=probes["sign_l1_single"](),
        batch_signature=probes["sign_l1_batch_10"](),
        single_payload=cast(Mapping[str, object], probes["build_payload_single"]()),
        batch_payload=cast(Mapping[str, object], probes["build_payload_batch_10"]()),
    )
    return probes


def _sdk_probes() -> dict[str, Callable[[], object]]:
    from eth_account import Account
    from hyperliquid.utils.signing import (
        OrderRequest,
        action_hash,
        order_request_to_order_wire,
        order_wires_to_order_action,
        sign_l1_action,
    )

    account = Account.from_key(_TEST_KEY)
    order: OrderRequest = {
        "coin": "BTC",
        "is_buy": True,
        "sz": 0.01,
        "limit_px": 100_000.0,
        "order_type": {"limit": {"tif": "Gtc"}},
        "reduce_only": False,
    }
    orders: tuple[OrderRequest, ...] = tuple(
        cast(OrderRequest, {**order, "coin": f"ASSET-{asset}"}) for asset in range(10)
    )

    def sign(action: object) -> object:
        return sign_l1_action(account, action, None, _NONCE, None, False)

    def payload_for(items: Sequence[OrderRequest]) -> dict[str, object]:
        wires = [
            order_request_to_order_wire(item, asset) for asset, item in enumerate(items)
        ]
        action = order_wires_to_order_action(wires)
        return {
            "action": action,
            "nonce": _NONCE,
            "signature": sign(action),
            "vaultAddress": None,
            "expiresAfter": None,
        }

    probes: dict[str, Callable[[], object]] = {
        "action_hash": lambda: action_hash(_SINGLE_ACTION, None, _NONCE, None),
        "sign_l1_single": lambda: sign(_SINGLE_ACTION),
        "sign_l1_batch_10": lambda: sign(_BATCH_ACTION),
        "build_payload_single": lambda: payload_for((order,)),
        "build_payload_batch_10": lambda: payload_for(orders),
    }
    _validate_probe(
        "sdk",
        action_hash=cast(bytes, probes["action_hash"]()),
        single_signature=probes["sign_l1_single"](),
        batch_signature=probes["sign_l1_batch_10"](),
        single_payload=cast(Mapping[str, object], probes["build_payload_single"]()),
        batch_payload=cast(Mapping[str, object], probes["build_payload_batch_10"]()),
    )
    return probes


def _require_ccxt_coincurve_backend(
    signer: Callable[[object, object, object, bool], object],
) -> None:
    try:
        signer("00" * 32, "11" * 32, None, False)
    except Exception as error:
        raise BenchmarkFailure(
            "CCXT benchmark requires a working CoinCurve backend"
        ) from error


def _ccxt_probes() -> dict[str, Callable[[], object]]:
    import ccxt
    from eth_account import Account

    _require_ccxt_coincurve_backend(ccxt.Exchange._ecdsa_secp256k1_coincurve)
    address = Account.from_key(_TEST_KEY).address
    client = ccxt.hyperliquid(
        {
            "walletAddress": address,
            "privateKey": _TEST_KEY,
            "options": {"sandboxMode": True},
        }
    )
    symbols: list[str] = []
    markets: dict[str, dict[str, object]] = {}
    markets_by_id: dict[str, list[dict[str, object]]] = {}
    for asset in range(10):
        symbol = f"ASSET-{asset}/USDC:USDC"
        market: dict[str, object] = {
            "id": f"ASSET-{asset}",
            "symbol": symbol,
            "base": f"ASSET-{asset}",
            "quote": "USDC",
            "settle": "USDC",
            "baseId": str(asset),
            "quoteId": "0",
            "type": "swap",
            "spot": False,
            "margin": False,
            "swap": True,
            "future": False,
            "option": False,
            "active": True,
            "contract": True,
            "linear": True,
            "inverse": False,
            "contractSize": 1,
            "expiry": None,
            "expiryDatetime": None,
            "strike": None,
            "optionType": None,
            "precision": {"amount": 0.00001, "price": 1.0},
            "limits": {},
            "info": {},
        }
        symbols.append(symbol)
        markets[symbol] = market
        markets_by_id[f"ASSET-{asset}"] = [market]
    client.markets = markets
    client.markets_by_id = markets_by_id
    setattr(client, "milliseconds", lambda: _NONCE)
    orders: tuple[_CcxtOrder, ...] = tuple(
        _CcxtOrder(
            symbol=symbol,
            type="limit",
            side="buy",
            amount="0.01",
            price="100000",
            params={"timeInForce": "Gtc"},
        )
        for symbol in symbols
    )

    def payload_for(items: Sequence[_CcxtOrder]) -> dict[str, object]:
        return cast(dict[str, object], client.create_orders_request(list(items)))

    probes: dict[str, Callable[[], object]] = {
        "action_hash": lambda: client.action_hash(_SINGLE_ACTION, None, _NONCE, None),
        "sign_l1_single": lambda: client.sign_l1_action(_SINGLE_ACTION, _NONCE),
        "sign_l1_batch_10": lambda: client.sign_l1_action(_BATCH_ACTION, _NONCE),
        "build_payload_single": lambda: payload_for(orders[:1]),
        "build_payload_batch_10": lambda: payload_for(orders),
    }
    _validate_probe(
        "ccxt",
        action_hash=cast(bytes, probes["action_hash"]()),
        single_signature=probes["sign_l1_single"](),
        batch_signature=probes["sign_l1_batch_10"](),
        single_payload=cast(Mapping[str, object], probes["build_payload_single"]()),
        batch_payload=cast(Mapping[str, object], probes["build_payload_batch_10"]()),
    )
    return probes


def run_provider_probe(provider: str, *, iterations: int) -> dict[str, float]:
    if iterations < 1:
        raise ValueError("iterations must be positive")
    if provider == "ccxt":
        probes = _ccxt_probes()
    elif provider == "sdk":
        probes = _sdk_probes()
    elif provider == "async-hyperliquid":
        probes = _async_hyperliquid_probes()
    else:
        raise ValueError(f"unknown provider: {provider}")

    signing_iterations = max(100, iterations // 10)
    batch_iterations = max(100, iterations // 20)
    return {
        "action_hash": _measure(probes["action_hash"], iterations),
        "sign_l1_single": _measure(probes["sign_l1_single"], signing_iterations),
        "sign_l1_batch_10": _measure(probes["sign_l1_batch_10"], signing_iterations),
        "build_payload_single": _measure(
            probes["build_payload_single"], signing_iterations
        ),
        "build_payload_batch_10": _measure(
            probes["build_payload_batch_10"], batch_iterations
        ),
    }


def provider_commands(*, iterations: int) -> tuple[ProviderCommand, ...]:
    script = Path(__file__).resolve()
    root = script.parents[1]
    return tuple(
        ProviderCommand(
            name=provider,
            argv=(
                sys.executable,
                str(script),
                "--provider",
                provider,
                "--iterations",
                str(iterations),
            ),
            cwd=root,
        )
        for provider in _PROVIDERS
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Parity-gated Hyperliquid signing benchmark."
    )
    parser.add_argument("--provider", choices=_PROVIDERS, help=argparse.SUPPRESS)
    parser.add_argument("--iterations", type=int, default=5_000)
    parser.add_argument("--rounds", type=int, default=7)
    parser.add_argument("--warmups", type=int, default=1)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.provider is not None:
        print(
            json.dumps(
                run_provider_probe(args.provider, iterations=args.iterations),
                sort_keys=True,
            )
        )
        return

    report = run_benchmark(
        provider_commands(iterations=args.iterations),
        rounds=args.rounds,
        warmups=args.warmups,
    )
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output is None:
        print(rendered, end="")
    else:
        args.output.write_text(rendered)


if __name__ == "__main__":
    main()
