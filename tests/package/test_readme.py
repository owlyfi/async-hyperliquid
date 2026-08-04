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
