import re
from pathlib import Path


ROOT = Path(__file__).parents[2]


def test_readme_python_examples_compile() -> None:
    readme = (ROOT / "README.md").read_text()
    examples = re.findall(r"```python\n(.*?)```", readme, re.DOTALL)

    assert len(examples) == 2
    for index, example in enumerate(examples):
        compile(example, f"README.md:python-example-{index}", "exec")


def test_benchmark_manual_documents_safe_failure_context_and_operator_actions() -> None:
    manual = (ROOT / "benchmarks" / "README.md").read_text()

    for field in (
        "phase",
        "logical_round",
        "measured_round",
        "operation",
        "launch_slot",
        "category",
        "failed_count",
        "successful_count",
        "recovery_attempted",
        "recovery_count",
        "recovery_ok",
    ):
        assert f"`{field}`" in manual
    assert "`rate_limited`" in manual
    assert "do not immediately rerun" in manual
    assert "`recovery_ok=false`" in manual
    assert "manual inspection" in manual
