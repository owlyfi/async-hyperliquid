import json
import sys

import pytest

from benchmarks import signing
from benchmarks.signing import (
    BenchmarkFailure,
    ProviderCommand,
    rotate_providers,
    run_benchmark,
    summarize,
)


def test_ccxt_benchmark_requires_a_working_coincurve_signer() -> None:
    def unavailable_signer(
        request: object, secret: object, hash_name: object, fixed_length: bool
    ) -> object:
        raise ImportError("coincurve is unavailable")

    with pytest.raises(BenchmarkFailure, match="CoinCurve"):
        signing._require_ccxt_coincurve_backend(unavailable_signer)


def _command(name: str, result: dict[str, float]) -> ProviderCommand:
    source = f"import json; print(json.dumps({result!r}))"
    return ProviderCommand(name, (sys.executable, "-c", source))


def test_providers_rotate_each_round() -> None:
    providers = (
        _command("ccxt", {"sign": 1.0}),
        _command("sdk", {"sign": 1.0}),
        _command("async-hyperliquid", {"sign": 1.0}),
    )

    assert rotate_providers(providers, rounds=4) == (
        providers,
        (providers[1], providers[2], providers[0]),
        (providers[2], providers[0], providers[1]),
        providers,
    )


def test_summary_reports_robust_latency_and_throughput() -> None:
    assert summarize([10.0, 20.0, 30.0, 40.0, 100.0]) == {
        "median_ns": 30.0,
        "mad_ns": 10.0,
        "p95_ns": 100.0,
        "ops_per_second": 1_000_000_000 / 30.0,
    }


def test_benchmark_rejects_provider_failure() -> None:
    broken = ProviderCommand(
        "broken", (sys.executable, "-c", "raise RuntimeError('probe failed')")
    )

    with pytest.raises(BenchmarkFailure, match="broken"):
        run_benchmark((broken,), rounds=1, warmups=0)


def test_benchmark_rejects_mismatched_operation_sets() -> None:
    providers = (_command("ccxt", {"sign": 1.0}), _command("sdk", {"hash": 1.0}))

    with pytest.raises(BenchmarkFailure, match="operation"):
        run_benchmark(providers, rounds=1, warmups=0)


def test_benchmark_report_contains_all_providers_and_is_json_serializable() -> None:
    providers = (
        _command("ccxt", {"sign": 3.0}),
        _command("sdk", {"sign": 2.0}),
        _command("async-hyperliquid", {"sign": 1.0}),
    )

    report = run_benchmark(providers, rounds=2, warmups=0)

    json.dumps(report)
    assert report["providers"] == ["ccxt", "sdk", "async-hyperliquid"]
    assert report["results"]["sign"]["async-hyperliquid"]["median_ns"] == 1.0


@pytest.mark.parametrize(("rounds", "warmups"), [(0, 0), (1, -1)])
def test_benchmark_rejects_invalid_run_counts(rounds: int, warmups: int) -> None:
    with pytest.raises(ValueError):
        run_benchmark(
            (_command("ccxt", {"sign": 1.0}),), rounds=rounds, warmups=warmups
        )
