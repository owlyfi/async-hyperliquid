from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).parents[2]


def _collect(path: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", path],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def test_exchange_tests_are_collected_by_default() -> None:
    result = _collect("tests/integration/exchange")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "test_place_limit_order" in result.stdout


def test_info_tests_collect_both_networks() -> None:
    result = _collect("tests/integration/test_info.py")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "test_all_mids[mainnet]" in result.stdout
    assert "test_all_mids[testnet]" in result.stdout
