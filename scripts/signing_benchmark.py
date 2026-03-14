from __future__ import annotations

import gc
import os
import statistics
from dataclasses import dataclass
from time import perf_counter_ns
from typing import Any, Callable, cast

from eth_account import Account
from eth_account.messages import encode_typed_data
from eth_account.signers.local import LocalAccount
from eth_keys.backends import CoinCurveECCBackend, NativeECCBackend
from eth_utils.conversions import to_hex

from async_hyperliquid.utils.constants import SIGNATURE_CHAIN_ID, USD_SEND_SIGN_TYPES
from async_hyperliquid.utils.signing import (
    _EXCHANGE_AGENT_PAYLOAD_BASE,
    hash_action,
    orders_to_action,
    sign_action,
    sign_user_signed_action,
    user_signed_payload,
)
from async_hyperliquid.utils.types import EncodedOrder

REPEATS = int(os.getenv("BENCH_REPEATS", "7"))
ITERATIONS = int(os.getenv("BENCH_SIGN_ITERATIONS", "5000"))
PAYLOAD_ITERATIONS = int(os.getenv("BENCH_PAYLOAD_ITERATIONS", "50000"))
ENCODE_ITERATIONS = int(os.getenv("BENCH_ENCODE_ITERATIONS", "5000"))
PRIVATE_KEY = "0x" + ("11" * 32)
HASH_ITERATIONS = int(os.getenv("BENCH_HASH_SIGN_ITERATIONS", "5000"))
BATCH_ITERATIONS = int(os.getenv("BENCH_BATCH_ITERATIONS", "1000"))
BATCH_SIZES = tuple(
    int(part.strip()) for part in os.getenv("BENCH_BATCH_SIZES", "2,5,10,20").split(",")
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


def legacy_exchange_payload(message: dict[str, Any]) -> dict[str, Any]:
    return {
        "domain": {
            "chainId": 1337,
            "name": "Exchange",
            "verifyingContract": "0x0000000000000000000000000000000000000000",
            "version": "1",
        },
        "types": {
            "Agent": [
                {"name": "source", "type": "string"},
                {"name": "connectionId", "type": "bytes32"},
            ],
            "EIP712Domain": [
                {"name": "name", "type": "string"},
                {"name": "version", "type": "string"},
                {"name": "chainId", "type": "uint256"},
                {"name": "verifyingContract", "type": "address"},
            ],
        },
        "primaryType": "Agent",
        "message": message,
    }


def current_exchange_payload(message: dict[str, Any]) -> dict[str, Any]:
    return {**_EXCHANGE_AGENT_PAYLOAD_BASE, "message": message}


def legacy_user_signed_payload(
    primary_type: str, payload_types: list[dict[str, str]], action: dict[str, Any]
) -> dict[str, Any]:
    chain_id = int(action["signatureChainId"], 16)
    return {
        "domain": {
            "name": "HyperliquidSignTransaction",
            "version": "1",
            "chainId": chain_id,
            "verifyingContract": "0x0000000000000000000000000000000000000000",
        },
        "types": {
            primary_type: payload_types,
            "EIP712Domain": [
                {"name": "name", "type": "string"},
                {"name": "version", "type": "string"},
                {"name": "chainId", "type": "uint256"},
                {"name": "verifyingContract", "type": "address"},
            ],
        },
        "primaryType": primary_type,
        "message": action,
    }


def sign_inner_legacy(wallet: LocalAccount, data: dict[str, Any]) -> dict[str, Any]:
    encodes = encode_typed_data(full_message=data)
    signed = wallet.sign_message(encodes)
    return {"r": to_hex(signed["r"]), "s": to_hex(signed["s"]), "v": signed["v"]}


def encode_only(data: dict[str, Any]) -> object:
    return encode_typed_data(full_message=data)


def legacy_sign_action(
    wallet: LocalAccount,
    action: dict[str, Any],
    active_pool: str | None,
    nonce: int,
    is_mainnet: bool,
    expires: int | None = None,
) -> dict[str, Any]:
    h = hash_action(action, active_pool, nonce, expires)
    msg = {"source": "a" if is_mainnet else "b", "connectionId": h}
    data = legacy_exchange_payload(msg)
    return sign_inner_legacy(wallet, data)


def legacy_sign_user_signed_action(
    wallet: LocalAccount,
    action: dict[str, Any],
    payload_types: list[dict[str, str]],
    primary_type: str,
    is_mainnet: bool,
) -> dict[str, Any]:
    mutable_action = action.copy()
    mutable_action["signatureChainId"] = SIGNATURE_CHAIN_ID
    mutable_action["hyperliquidChain"] = "Mainnet" if is_mainnet else "Testnet"
    data = legacy_user_signed_payload(primary_type, payload_types, mutable_action)
    return sign_inner_legacy(wallet, data)


def run_benchmark(
    name: str, iterations: int, setup: Callable[[], Callable[[], object]]
) -> BenchmarkResult:
    timings: list[float] = []
    for _ in range(REPEATS):
        benchmark_fn = setup()
        gc.collect()
        gc.disable()
        start = perf_counter_ns()
        for _ in range(iterations):
            benchmark_fn()
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


def print_pair(
    current: BenchmarkResult,
    legacy: BenchmarkResult,
    *,
    left_label: str = "current",
    right_label: str = "legacy",
) -> None:
    print(f"{current.name}:")
    print(
        f"  {left_label:<7} median: {current.median_ns:,.1f} ns/op ({current.ops_per_sec:,.0f} ops/s)"
    )
    print(
        f"  {right_label:<7} median: {legacy.median_ns:,.1f} ns/op ({legacy.ops_per_sec:,.0f} ops/s)"
    )
    print(f"  improvement:    {percent_delta(current, legacy):.2f}%")
    print()


def make_exchange_message() -> dict[str, Any]:
    return {"source": "a", "connectionId": b"\x01" * 32}


def make_user_action() -> dict[str, Any]:
    return {
        "type": "usdSend",
        "amount": "12.34",
        "destination": "0x1234567890123456789012345678901234567890",
        "time": 1_700_000_000_000,
        "signatureChainId": SIGNATURE_CHAIN_ID,
        "hyperliquidChain": "Mainnet",
    }


def set_account_backend(backend_name: str) -> None:
    account_api = cast(Any, Account)
    if backend_name == "native":
        account_api.set_key_backend(account_api, NativeECCBackend())
        return
    if backend_name == "coincurve":
        account_api.set_key_backend(account_api, CoinCurveECCBackend())
        return

    raise ValueError(f"Unsupported backend: {backend_name}")


def make_encoded_order(index: int) -> EncodedOrder:
    return {
        "a": index,
        "b": True,
        "p": "110000",
        "s": "0.1",
        "r": False,
        "t": {"limit": {"tif": "Alo"}},
    }


def main() -> None:
    wallet = Account.from_key(PRIVATE_KEY)
    current_backend_name = type(Account._keys.backend).__name__
    exchange_action = {
        "type": "order",
        "orders": [
            {
                "a": 0,
                "b": True,
                "p": "110000",
                "s": "0.1",
                "r": False,
                "t": {"limit": {"tif": "Alo"}},
            }
        ],
        "grouping": "na",
    }
    user_action = {
        "type": "usdSend",
        "amount": "12.34",
        "destination": "0x1234567890123456789012345678901234567890",
        "time": 1_700_000_000_000,
    }

    current_exchange_payload_result = run_benchmark(
        "exchange payload assembly",
        PAYLOAD_ITERATIONS,
        lambda: (lambda: current_exchange_payload(make_exchange_message())),
    )
    legacy_exchange_payload_result = run_benchmark(
        "exchange payload assembly",
        PAYLOAD_ITERATIONS,
        lambda: (lambda: legacy_exchange_payload(make_exchange_message())),
    )

    current_user_payload_result = run_benchmark(
        "user payload assembly",
        PAYLOAD_ITERATIONS,
        lambda: (
            lambda: user_signed_payload(
                "HyperliquidTransaction:UsdSend",
                USD_SEND_SIGN_TYPES,
                make_user_action(),
            )
        ),
    )
    legacy_user_payload_result = run_benchmark(
        "user payload assembly",
        PAYLOAD_ITERATIONS,
        lambda: (
            lambda: legacy_user_signed_payload(
                "HyperliquidTransaction:UsdSend",
                USD_SEND_SIGN_TYPES,
                make_user_action(),
            )
        ),
    )

    current_exchange_sign_result = run_benchmark(
        "exchange sign end-to-end",
        ITERATIONS,
        lambda: (
            lambda: sign_action(
                wallet, exchange_action, None, 1_700_000_000_000, True, None
            )
        ),
    )
    current_exchange_encode_result = run_benchmark(
        "exchange encode only",
        ENCODE_ITERATIONS,
        lambda: (
            lambda: encode_only(current_exchange_payload(make_exchange_message()))
        ),
    )
    legacy_exchange_encode_result = run_benchmark(
        "exchange encode only",
        ENCODE_ITERATIONS,
        lambda: (lambda: encode_only(legacy_exchange_payload(make_exchange_message()))),
    )
    legacy_exchange_sign_result = run_benchmark(
        "exchange sign end-to-end",
        ITERATIONS,
        lambda: (
            lambda: legacy_sign_action(
                wallet, exchange_action, None, 1_700_000_000_000, True, None
            )
        ),
    )

    current_user_sign_result = run_benchmark(
        "user sign end-to-end",
        ITERATIONS,
        lambda: (
            lambda: sign_user_signed_action(
                wallet,
                user_action.copy(),
                USD_SEND_SIGN_TYPES,
                "HyperliquidTransaction:UsdSend",
                True,
            )
        ),
    )
    legacy_user_sign_result = run_benchmark(
        "user sign end-to-end",
        ITERATIONS,
        lambda: (
            lambda: legacy_sign_user_signed_action(
                wallet,
                user_action,
                USD_SEND_SIGN_TYPES,
                "HyperliquidTransaction:UsdSend",
                True,
            )
        ),
    )
    current_user_encode_result = run_benchmark(
        "user encode only",
        ENCODE_ITERATIONS,
        lambda: (
            lambda: encode_only(
                user_signed_payload(
                    "HyperliquidTransaction:UsdSend",
                    USD_SEND_SIGN_TYPES,
                    make_user_action(),
                )
            )
        ),
    )
    legacy_user_encode_result = run_benchmark(
        "user encode only",
        ENCODE_ITERATIONS,
        lambda: (
            lambda: encode_only(
                legacy_user_signed_payload(
                    "HyperliquidTransaction:UsdSend",
                    USD_SEND_SIGN_TYPES,
                    make_user_action(),
                )
            )
        ),
    )
    native_hash_sign_result = run_benchmark(
        "raw ECDSA sign (unsafe_sign_hash)",
        HASH_ITERATIONS,
        lambda: (
            set_account_backend("native"),
            (
                lambda wallet=Account.from_key(PRIVATE_KEY): wallet.unsafe_sign_hash(
                    b"\x42" * 32
                )
            ),
        )[1],
    )
    coincurve_hash_sign_result = run_benchmark(
        "raw ECDSA sign (unsafe_sign_hash)",
        HASH_ITERATIONS,
        lambda: (
            set_account_backend("coincurve"),
            (
                lambda wallet=Account.from_key(PRIVATE_KEY): wallet.unsafe_sign_hash(
                    b"\x42" * 32
                )
            ),
        )[1],
    )
    native_exchange_sign_result = run_benchmark(
        "exchange sign end-to-end (backend compare)",
        ITERATIONS,
        lambda: (
            set_account_backend("native"),
            (
                lambda wallet=Account.from_key(PRIVATE_KEY): sign_action(
                    wallet, exchange_action, None, 1_700_000_000_000, True, None
                )
            ),
        )[1],
    )
    coincurve_exchange_sign_result = run_benchmark(
        "exchange sign end-to-end (backend compare)",
        ITERATIONS,
        lambda: (
            set_account_backend("coincurve"),
            (
                lambda wallet=Account.from_key(PRIVATE_KEY): sign_action(
                    wallet, exchange_action, None, 1_700_000_000_000, True, None
                )
            ),
        )[1],
    )
    native_user_sign_result = run_benchmark(
        "user sign end-to-end (backend compare)",
        ITERATIONS,
        lambda: (
            set_account_backend("native"),
            (
                lambda wallet=Account.from_key(PRIVATE_KEY): sign_user_signed_action(
                    wallet,
                    user_action.copy(),
                    USD_SEND_SIGN_TYPES,
                    "HyperliquidTransaction:UsdSend",
                    True,
                )
            ),
        )[1],
    )
    coincurve_user_sign_result = run_benchmark(
        "user sign end-to-end (backend compare)",
        ITERATIONS,
        lambda: (
            set_account_backend("coincurve"),
            (
                lambda wallet=Account.from_key(PRIVATE_KEY): sign_user_signed_action(
                    wallet,
                    user_action.copy(),
                    USD_SEND_SIGN_TYPES,
                    "HyperliquidTransaction:UsdSend",
                    True,
                )
            ),
        )[1],
    )
    set_account_backend("coincurve")

    print("Signing benchmark (current cached templates vs legacy rebuild-every-time)")
    print(
        "repeats="
        f"{REPEATS}, payload_iterations={PAYLOAD_ITERATIONS}, "
        f"encode_iterations={ENCODE_ITERATIONS}, sign_iterations={ITERATIONS}, "
        f"hash_sign_iterations={HASH_ITERATIONS}"
    )
    print(f"default backend at script start: {current_backend_name}")
    print()
    print_pair(current_exchange_payload_result, legacy_exchange_payload_result)
    print_pair(current_user_payload_result, legacy_user_payload_result)
    print_pair(current_exchange_encode_result, legacy_exchange_encode_result)
    print_pair(current_user_encode_result, legacy_user_encode_result)
    print_pair(current_exchange_sign_result, legacy_exchange_sign_result)
    print_pair(current_user_sign_result, legacy_user_sign_result)
    print("Backend comparison (same optimized code path)")
    print()
    print_pair(
        coincurve_hash_sign_result,
        native_hash_sign_result,
        left_label="coincurve",
        right_label="native",
    )
    print_pair(
        coincurve_exchange_sign_result,
        native_exchange_sign_result,
        left_label="coincurve",
        right_label="native",
    )
    print_pair(
        coincurve_user_sign_result,
        native_user_sign_result,
        left_label="coincurve",
        right_label="native",
    )
    print("Batching comparison (CoinCurve backend, optimized code path)")
    print()
    set_account_backend("coincurve")
    batch_wallet = Account.from_key(PRIVATE_KEY)
    for batch_size in BATCH_SIZES:
        batch_orders: list[EncodedOrder] = [
            make_encoded_order(i) for i in range(batch_size)
        ]
        single_order_actions: list[dict[str, Any]] = [
            cast(dict[str, Any], orders_to_action([order])) for order in batch_orders
        ]
        batched_action = cast(dict[str, Any], orders_to_action(batch_orders))

        individual_result = run_benchmark(
            f"order batching x{batch_size}",
            BATCH_ITERATIONS,
            lambda: (
                lambda: [
                    sign_action(
                        batch_wallet,
                        action,
                        None,
                        1_700_000_000_000 + index,
                        True,
                        None,
                    )
                    for index, action in enumerate(single_order_actions)
                ]
            ),
        )
        batched_result = run_benchmark(
            f"order batching x{batch_size}",
            BATCH_ITERATIONS,
            lambda: (
                lambda: sign_action(
                    batch_wallet, batched_action, None, 1_700_000_000_000, True, None
                )
            ),
        )

        print_pair(
            batched_result,
            individual_result,
            left_label="batched",
            right_label="single",
        )
        single_per_order = individual_result.median_ns / batch_size
        batched_per_order = batched_result.median_ns / batch_size
        print(
            "  per-order median:"
            f" batched={batched_per_order:,.1f} ns, "
            f"single={single_per_order:,.1f} ns, "
            f"gain={(1 - (batched_per_order / single_per_order)) * 100:.2f}%"
        )
        print(
            f"  signed requests: batched=1, single={batch_size}, "
            f"request reduction={(1 - (1 / batch_size)) * 100:.2f}%"
        )
        print()


if __name__ == "__main__":
    main()
