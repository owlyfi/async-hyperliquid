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


def test_v1_source_tree_has_no_legacy_topology_or_embedded_evm_dependency() -> None:
    package = ROOT / "src" / "async_hyperliquid"
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text())
    dependencies = pyproject["project"]["dependencies"]

    assert not (package / "async_api.py").exists()
    assert not (package / "async_hyperliquid.py").exists()
    assert not (package / "_async_hyperliquid").exists()
    assert not (package / "utils").exists()
    assert all(not dependency.startswith("hl-web3") for dependency in dependencies)


@pytest.mark.skipif(
    not WHEELS, reason="build a wheel or set ASYNC_HYPERLIQUID_WHEEL_DIR"
)
def test_built_wheel_contains_inline_typing_marker() -> None:
    assert len(WHEELS) == 1
    with zipfile.ZipFile(WHEELS[0]) as wheel:
        assert "async_hyperliquid/py.typed" in wheel.namelist()
