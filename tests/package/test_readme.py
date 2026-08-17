import re
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from markdown_it import MarkdownIt
import tomllib


ROOT = Path(__file__).parents[2]


def _readme_destinations(readme: str) -> tuple[set[str], set[str]]:
    links: set[str] = set()
    images: set[str] = set()
    for token in MarkdownIt("commonmark").parse(readme):
        for child in token.children or ():
            if child.type == "link_open":
                href = child.attrGet("href")
                if href is not None:
                    links.add(href)
            elif child.type == "image":
                src = child.attrGet("src")
                if src is not None:
                    images.add(src)
    return links, images


def test_readme_uses_current_release_badge_and_explicit_latest_docs() -> None:
    readme = (ROOT / "README.md").read_text()
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    links, images = _readme_destinations(readme)

    badge = next(url for url in images if "/pypi/v/async-hyperliquid" in url)
    assert parse_qs(urlparse(badge).query) == {"v": [project["version"]]}
    assert "https://async-hyperliquid.readthedocs.io/en/latest/" in links
    assert (
        "https://async-hyperliquid.readthedocs.io/en/latest/reference/index.html"
        in links
    )
    assert (
        "https://async-hyperliquid.readthedocs.io/en/latest/"
        "migration-0.5-to-1.0.html"
        in links
    )
    assert "https://async-hyperliquid.readthedocs.io/" not in links


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
