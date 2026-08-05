import re
from pathlib import Path


ROOT = Path(__file__).parents[2]


def test_readme_python_examples_compile() -> None:
    readme = (ROOT / "README.md").read_text()
    examples = re.findall(r"```python\n(.*?)```", readme, re.DOTALL)

    assert examples
    for index, example in enumerate(examples):
        compile(example, f"README.md:python-example-{index}", "exec")


def test_readme_links_the_benchmark_manual() -> None:
    readme = (ROOT / "README.md").read_text()

    assert "benchmarks/README.md" in readme
    assert "benchmarks/signing.py" in readme
    assert "Local overall result" in readme
    assert "24,641 ops/s" in readme
    assert "scripts/signing_benchmark.py" not in readme
    assert (ROOT / "benchmarks" / "README.md").is_file()


def test_signing_benchmark_uses_sdk_as_its_only_relative_baseline() -> None:
    readmes = (
        (ROOT / "README.md").read_text(),
        (ROOT / "benchmarks" / "README.md").read_text(),
    )

    for readme in readmes:
        assert "Relative to fastest" not in readme
        assert "hyperliquid-python-sdk 0.24.0 | 16,874 ops/s | 1.000x" in readme or (
            "Official SDK | 16,874 ops/s | 1.000x" in readme
        )


def test_readme_documents_live_integration_commands_without_run_flags() -> None:
    readme = (ROOT / "README.md").read_text()

    for removed_flag in (
        "RUN_INFO_TESTS",
        "RUN_MAINNET_INFO_TESTS",
        "RUN_EXCHANGE_TESTS",
        "RUN_DESTRUCTIVE_EXCHANGE_TESTS",
    ):
        assert removed_flag not in readme

    assert "uv run pytest -q tests/integration/test_info.py" in readme
    assert "IS_MAINNET=false uv run pytest -q tests/integration/exchange" in readme
