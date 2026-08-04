import json
import sys
import zipfile
from pathlib import Path

import pytest

from benchmarks.hotpath import (
    BenchmarkCommand,
    BenchmarkFailure,
    CANDIDATE_WHEEL_PROBE,
    alternate_candidates,
    compare_wheels,
    run_ab_ba,
    summarize,
)


def test_alternate_candidates_uses_ab_ba_rounds() -> None:
    baseline = BenchmarkCommand("baseline", (sys.executable, "-c", ""))
    candidate = BenchmarkCommand("candidate", (sys.executable, "-c", ""))

    assert alternate_candidates(baseline, candidate, rounds=4) == (
        (baseline, candidate),
        (candidate, baseline),
        (baseline, candidate),
        (candidate, baseline),
    )


def test_summary_reports_median_mad_and_nearest_rank_p95() -> None:
    assert summarize([10.0, 20.0, 30.0, 40.0, 100.0]) == {
        "median_ns": 30.0,
        "mad_ns": 10.0,
        "p95_ns": 100.0,
    }


def test_benchmark_fails_on_an_unexpected_child_exception() -> None:
    baseline = BenchmarkCommand(
        "baseline",
        (sys.executable, "-c", "import json; print(json.dumps({'encode_order': 1.0}))"),
    )
    candidate = BenchmarkCommand(
        "candidate", (sys.executable, "-c", "raise RuntimeError('broken benchmark')")
    )

    with pytest.raises(BenchmarkFailure, match="candidate"):
        run_ab_ba(baseline, candidate, rounds=1, warmups=0)


def test_benchmark_rejects_mismatched_operation_sets() -> None:
    baseline = BenchmarkCommand(
        "baseline",
        (sys.executable, "-c", "import json; print(json.dumps({'encode_order': 1.0}))"),
    )
    candidate = BenchmarkCommand(
        "candidate",
        (sys.executable, "-c", "import json; print(json.dumps({'sign_batch': 1.0}))"),
    )

    with pytest.raises(BenchmarkFailure, match="operation"):
        run_ab_ba(baseline, candidate, rounds=1, warmups=0)


def test_benchmark_output_is_json_serializable() -> None:
    baseline = BenchmarkCommand(
        "baseline",
        (sys.executable, "-c", "import json; print(json.dumps({'encode_order': 2.0}))"),
    )
    candidate = BenchmarkCommand(
        "candidate",
        (sys.executable, "-c", "import json; print(json.dumps({'encode_order': 1.0}))"),
    )

    report = run_ab_ba(baseline, candidate, rounds=2, warmups=0)

    json.dumps(report)
    assert report["results"]["encode_order"]["candidate"]["median_ns"] == 1.0


def test_benchmark_rejects_a_wheel_with_path_traversal(tmp_path: Path) -> None:
    wheel = tmp_path / "malicious.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("../outside.py", "raise RuntimeError")

    with pytest.raises(BenchmarkFailure, match="unsafe wheel member"):
        compare_wheels(wheel, wheel, rounds=1, warmups=0, iterations=1)


def test_v1_dependency_comparison_uses_independent_interpreters(tmp_path: Path) -> None:
    wheel = tmp_path / "package.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("async_hyperliquid/__init__.py", "")

    missing_python = tmp_path / "missing-python"
    with pytest.raises(BenchmarkFailure, match="baseline"):
        compare_wheels(
            wheel,
            wheel,
            rounds=1,
            warmups=0,
            iterations=1,
            baseline_probe=CANDIDATE_WHEEL_PROBE,
            baseline_python=missing_python,
            candidate_python=Path(sys.executable),
        )


def test_v1_probe_compares_pre_and_post_market_context_signatures(
    tmp_path: Path,
) -> None:
    baseline = tmp_path / "baseline.whl"
    candidate = tmp_path / "candidate.whl"
    common = {
        "async_hyperliquid/__init__.py": "",
        "async_hyperliquid/types/__init__.py": """
class _Mainnet:
    signature_source = "a"


class Network:
    MAINNET = _Mainnet()


class TimeInForce:
    GTC = "Gtc"


def limit_order_type(tif):
    return {"limit": {"tif": tif}}
""",
    }
    with zipfile.ZipFile(baseline, "w") as archive:
        for name, source in common.items():
            archive.writestr(name, source)
        archive.writestr(
            "async_hyperliquid/_signing.py",
            "def sign_exchange_action(*args):\n    return None\n",
        )
        archive.writestr(
            "async_hyperliquid/_encoding.py",
            "def encode_order(order, *, asset, size_decimals):\n"
            "    return {'a': asset}\n",
        )
    with zipfile.ZipFile(candidate, "w") as archive:
        for name, source in common.items():
            archive.writestr(name, source)
        archive.writestr("async_hyperliquid/_internal/__init__.py", "")
        archive.writestr(
            "async_hyperliquid/_internal/signing.py",
            "def sign_exchange_action(*args):\n    return None\n",
        )
        archive.writestr(
            "async_hyperliquid/_internal/encoding.py",
            "def encode_order(\n"
            "    order, *, asset, size_decimals, is_spot, is_outcome\n"
            "):\n"
            "    return {'a': asset}\n",
        )

    report = compare_wheels(
        baseline,
        candidate,
        rounds=1,
        warmups=0,
        iterations=1,
        baseline_probe=CANDIDATE_WHEEL_PROBE,
    )

    assert set(report["results"]) == {
        "prepare_batch_10",
        "prepare_order",
        "sign_batch_10",
        "sign_order",
    }
