import os
import tomllib
import zipfile
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[2]
WHEEL_DIR = Path(os.environ.get("ASYNC_HYPERLIQUID_WHEEL_DIR", ROOT / "dist"))
WHEELS = tuple(WHEEL_DIR.glob("async_hyperliquid-*.whl"))


def test_project_requires_python_3_11_without_an_artificial_upper_bound() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text())

    assert pyproject["project"]["requires-python"] == ">=3.11"
    assert "poetry" not in pyproject["tool"]


def test_project_uses_unambiguous_pep_639_license_metadata() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]

    assert project["license"] == "MIT"
    assert project["license-files"] == ["LICENSE"]
    assert not any(
        classifier.startswith("License ::") for classifier in project["classifiers"]
    )


def test_source_package_declares_inline_typing() -> None:
    assert (ROOT / "src" / "async_hyperliquid" / "py.typed").is_file()


@pytest.mark.skipif(
    not WHEELS, reason="build a wheel or set ASYNC_HYPERLIQUID_WHEEL_DIR"
)
def test_built_wheel_contains_inline_typing_marker() -> None:
    assert len(WHEELS) == 1
    with zipfile.ZipFile(WHEELS[0]) as wheel:
        assert "async_hyperliquid/py.typed" in wheel.namelist()
