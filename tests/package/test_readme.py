import re
from pathlib import Path


ROOT = Path(__file__).parents[2]


def test_readme_python_examples_compile() -> None:
    readme = (ROOT / "README.md").read_text()
    examples = re.findall(r"```python\n(.*?)```", readme, re.DOTALL)

    assert examples
    for index, example in enumerate(examples):
        compile(example, f"README.md:python-example-{index}", "exec")
