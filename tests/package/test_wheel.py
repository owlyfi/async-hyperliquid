import os
import tarfile
import tomllib
import zipfile
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[2]
WHEEL_DIR = Path(os.environ.get("ASYNC_HYPERLIQUID_WHEEL_DIR", ROOT / "dist"))
WHEELS = tuple(WHEEL_DIR.glob("async_hyperliquid-*.whl"))
SDISTS = tuple(WHEEL_DIR.glob("async_hyperliquid-*.tar.gz"))


def test_project_declares_python_compatibility() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text())
    classifiers = pyproject["project"]["classifiers"]

    assert pyproject["project"]["requires-python"] == ">=3.12"
    assert (ROOT / ".python-version").read_text().strip() == "3.12"
    assert not any(
        classifier.startswith("Programming Language :: Python :: 3.")
        for classifier in classifiers
    )
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
def test_built_wheel_contract() -> None:
    assert len(WHEELS) == 1
    with zipfile.ZipFile(WHEELS[0]) as wheel:
        assert "async_hyperliquid/py.typed" in wheel.namelist()
        metadata_path = next(
            name for name in wheel.namelist() if name.endswith(".dist-info/METADATA")
        )
        metadata = wheel.read(metadata_path).decode()

    assert "\nRequires-Python: >=3.12\n" in metadata
    assert "\nClassifier: Development Status :: 5 - Production/Stable\n" in metadata
    assert "\nClassifier: Development Status :: 4 - Beta\n" not in metadata


@pytest.mark.skipif(
    not SDISTS, reason="build an sdist or set ASYNC_HYPERLIQUID_WHEEL_DIR"
)
def test_sdist_contains_public_docs_but_excludes_internal_docs() -> None:
    assert len(SDISTS) == 1
    with tarfile.open(SDISTS[0]) as sdist:
        names = sdist.getnames()

    expected_docs = {
        "docs/conf.py",
        "docs/index.rst",
        "docs/introduction/quickstart.rst",
        "docs/project/benchmarks.md",
        "docs/reference/async-hyperliquid.rst",
        "docs/coin-name-mapping.md",
        "docs/migration-0.5-to-1.0.md",
        "docs/locale/zh_CN/LC_MESSAGES/index.po",
        "docs/locale/zh_CN/LC_MESSAGES/howto/orders.po",
        "docs/locale/zh_CN/LC_MESSAGES/migration-0.5-to-1.0.po",
        "docs/locale/zh_CN/LC_MESSAGES/project/benchmarks.po",
    }
    archive_docs = {
        name.split("/", maxsplit=1)[1] for name in names if "/docs/" in name
    }

    assert expected_docs <= archive_docs
    assert not any("/dev-docs/" in name for name in names)
    assert not any("/docs/_build/" in name for name in names)
    assert not any(name.endswith(".mo") for name in names)
