from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).parents[2]


def test_exchange_tests_are_collected_by_default() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--collect-only",
            "-q",
            "tests/integration/exchange",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "test_place_limit_order" in result.stdout
