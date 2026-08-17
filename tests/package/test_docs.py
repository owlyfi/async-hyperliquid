import os
from pathlib import Path
import re
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[2]
PUBLIC_DOC_SUFFIXES = {".md", ".rst"}
NARRATIVE_CATALOGS = (
    "coin-name-mapping.po",
    "howto/index.po",
    "howto/info-queries.po",
    "howto/lifecycle-reconciliation.po",
    "howto/markets.po",
    "howto/orders.po",
    "howto/routing.po",
    "howto/transfers-administration.po",
    "index.po",
    "introduction/index.po",
    "introduction/installation.po",
    "introduction/quickstart.po",
    "migration-0.5-to-1.0.po",
    "project/about.po",
    "project/benchmarks.po",
    "project/index.po",
    "project/license.po",
    "reference/async-hyperliquid.po",
    "reference/errors.po",
    "reference/exchange-client.po",
    "reference/info-client.po",
    "reference/index.po",
    "reference/response-types.po",
    "reference/types.po",
)
OFFLINE_SPHINX_SCRIPT = """
import os
import sys

from sphinx.cmd.build import main


proxy = "http://127.0.0.1:1"
for name in (
    "ALL_PROXY",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "all_proxy",
    "http_proxy",
    "https_proxy",
):
    os.environ[name] = proxy
os.environ["NO_PROXY"] = ""
os.environ["no_proxy"] = ""
raise SystemExit(main(sys.argv[1:]))
"""
TRANSLATION_COMPLETENESS_SCRIPT = """
from pathlib import Path
import sys

from babel.messages.pofile import read_po


missing = []
protected_api_titles = {"AsyncHyperliquid", "ExchangeClient", "InfoClient"}
for filename in sys.argv[1:]:
    path = Path(filename)
    with path.open(encoding="utf-8") as catalog_file:
        catalog = read_po(catalog_file)
    for message in catalog:
        from_authored_document = any(
            filename.startswith("../../") for filename, _ in message.locations
        )
        if (
            not message.id
            or not from_authored_document
            or message.id in protected_api_titles
        ):
            continue
        translations = (
            message.string
            if isinstance(message.string, tuple)
            else (message.string,)
        )
        if message.fuzzy or not all(translations):
            missing.append(f"{path}:{message.lineno}: {message.id!r}")

if missing:
    print("Untranslated or fuzzy narrative messages:")
    print("\\n".join(missing))
    raise SystemExit(1)
"""


def test_public_docs_exclude_internal_project_material() -> None:
    public_sources = (
        path
        for path in sorted((ROOT / "docs").rglob("*"))
        if path.suffix in PUBLIC_DOC_SUFFIXES
    )

    for path in public_sources:
        public_text = path.read_text(encoding="utf-8")
        for internal_reference in ("Copycat", ".agent/", ".superpowers/", "dev-docs/"):
            assert internal_reference not in public_text, (
                f"{path.relative_to(ROOT)} exposes internal reference "
                f"{internal_reference!r}"
            )


def test_selected_narrative_translation_catalogs_are_complete() -> None:
    locale_root = Path("docs/locale/zh_CN/LC_MESSAGES")
    result = subprocess.run(
        [
            "uv",
            "run",
            "--frozen",
            "--group",
            "docs",
            "python",
            "-c",
            TRANSLATION_COMPLETENESS_SCRIPT,
            *(str(locale_root / relative) for relative in NARRATIVE_CATALOGS),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr


def test_translation_catalogs_do_not_publish_email_metadata() -> None:
    locale_root = ROOT / "docs" / "locale" / "zh_CN" / "LC_MESSAGES"
    email_pattern = re.compile(
        r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@"
        r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
        r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+"
    )

    for path in locale_root.rglob("*.po"):
        assert not email_pattern.search(path.read_text(encoding="utf-8")), (
            f"{path.relative_to(ROOT)} contains email metadata"
        )


def _run_docs(
    language: str, output_dir: Path, documentation_version: str | None = "latest"
) -> subprocess.CompletedProcess[str]:
    hosted_language = "zh-cn" if language == "zh_CN" else "en"
    environment = {**os.environ, "READTHEDOCS_LANGUAGE": hosted_language}
    if documentation_version is None:
        environment.pop("READTHEDOCS_VERSION", None)
    else:
        environment["READTHEDOCS_VERSION"] = documentation_version

    return subprocess.run(
        [
            "uv",
            "run",
            "--frozen",
            "--group",
            "docs",
            "python",
            "-c",
            OFFLINE_SPHINX_SCRIPT,
            "-E",
            "-a",
            "-W",
            "--keep-going",
            "-b",
            "html",
            "docs",
            str(output_dir),
        ],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


def _build_docs(
    language: str, output_dir: Path, documentation_version: str | None = "latest"
) -> None:
    result = _run_docs(language, output_dir, documentation_version)

    assert result.returncode == 0, result.stdout + result.stderr


def test_english_docs_build_with_warnings_as_errors(tmp_path: Path) -> None:
    output_dir = tmp_path / "en"
    _build_docs("en", output_dir)

    assert (output_dir / "index.html").is_file()

    english_index_html = (output_dir / "index.html").read_text(encoding="utf-8")
    about_html = (output_dir / "project" / "about.html").read_text(encoding="utf-8")
    benchmarks_html = (output_dir / "project" / "benchmarks.html").read_text(
        encoding="utf-8"
    )
    license_html = (output_dir / "project" / "license.html").read_text(encoding="utf-8")
    rendered_site = "\n".join(
        path.read_text(encoding="utf-8") for path in output_dir.rglob("*.html")
    )

    assert "Yuki" in about_html
    assert "Overall comparison" in benchmarks_html
    assert "local CPU reference" in benchmarks_html
    assert "not network latency or exchange throughput" in benchmarks_html
    assert "async-hyperliquid" in benchmarks_html
    assert "Official SDK" in benchmarks_html
    assert "CCXT" in benchmarks_html
    assert "24,641 ops/s" in benchmarks_html
    assert "1.460x" in benchmarks_html
    assert "16,874 ops/s" in benchmarks_html
    assert "1.000x" in benchmarks_html
    assert "803 ops/s" in benchmarks_html
    assert "0.0476x" in benchmarks_html
    assert "MIT License" in license_html
    brand = '<span class="sidebar-brand-text">async-hyperliquid</span>'
    english_index = "https://async-hyperliquid.readthedocs.io/en/latest/index.html"
    chinese_index = "https://async-hyperliquid.readthedocs.io/zh-cn/latest/index.html"

    assert brand in english_index_html
    assert "async-hyperliquid 1.0.0 documentation" not in english_index_html
    assert english_index in english_index_html
    assert chinese_index in english_index_html
    assert 'lang="en" aria-current="page"' in english_index_html
    assert "yuqi.lyle@gmail.com" not in rendered_site


def test_docs_version_falls_back_to_latest_when_environment_is_absent(
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "fallback"
    _build_docs("en", output_dir, documentation_version=None)

    index_html = (output_dir / "index.html").read_text(encoding="utf-8")
    assert "https://async-hyperliquid.readthedocs.io/en/latest/index.html" in index_html
    assert (
        "https://async-hyperliquid.readthedocs.io/zh-cn/latest/index.html" in index_html
    )


@pytest.mark.parametrize(
    "documentation_version",
    ["", 'latest"/../../hostile'],
    ids=["empty", "quote-and-path"],
)
def test_docs_build_rejects_empty_or_malformed_custom_version(
    tmp_path: Path, documentation_version: str
) -> None:
    result = _run_docs(
        "en", tmp_path / "malformed", documentation_version=documentation_version
    )

    output = result.stdout + result.stderr
    assert result.returncode != 0, output
    assert (
        "READTHEDOCS_VERSION must be a non-empty Read the Docs version slug" in output
    )
    if documentation_version:
        assert documentation_version not in output


def test_simplified_chinese_docs_translate_narrative_and_preserve_api_names(
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "zh_CN"
    _build_docs("zh_CN", output_dir)

    chinese_index_html = (output_dir / "index.html").read_text(encoding="utf-8")
    orders_html = (output_dir / "howto" / "orders.html").read_text(encoding="utf-8")
    async_client_html = (output_dir / "reference" / "async-hyperliquid.html").read_text(
        encoding="utf-8"
    )
    info_client_html = (output_dir / "reference" / "info-client.html").read_text(
        encoding="utf-8"
    )
    types_html = (output_dir / "reference" / "types.html").read_text(encoding="utf-8")
    errors_html = (output_dir / "reference" / "errors.html").read_text(encoding="utf-8")
    benchmarks_html = (output_dir / "project" / "benchmarks.html").read_text(
        encoding="utf-8"
    )
    rendered_site = "\n".join(
        path.read_text(encoding="utf-8") for path in output_dir.rglob("*.html")
    )

    brand = '<span class="sidebar-brand-text">async-hyperliquid</span>'
    english_index = "https://async-hyperliquid.readthedocs.io/en/latest/index.html"
    chinese_index = "https://async-hyperliquid.readthedocs.io/zh-cn/latest/index.html"

    assert "异步、带类型的 Python 客户端" in chinese_index_html
    assert "单笔和批量操作" in orders_html
    assert "错误" in errors_html
    assert "总体比较" in benchmarks_html
    assert "本地 CPU 参考结果" in benchmarks_html
    assert "async-hyperliquid" in benchmarks_html
    assert "Official SDK" in benchmarks_html
    assert "CCXT" in benchmarks_html
    assert "24,641 ops/s" in benchmarks_html
    assert "1.460x" in benchmarks_html
    assert "16,874 ops/s" in benchmarks_html
    assert "1.000x" in benchmarks_html
    assert "803 ops/s" in benchmarks_html
    assert "0.0476x" in benchmarks_html
    assert "AsyncHyperliquid" in async_client_html
    assert "InfoClient" in info_client_html
    assert "PlaceOrderRequest" in types_html
    assert "Resource owner plus intent-level order workflows." in async_client_html
    assert (
        "Asynchronous, credential-free client for Hyperliquid Info endpoints."
        in info_client_html
    )
    assert "A validated 16-byte hexadecimal client order ID." in types_html
    assert brand in chinese_index_html
    assert "async-hyperliquid 1.0.0 documentation" not in chinese_index_html
    assert english_index in chinese_index_html
    assert chinese_index in chinese_index_html
    assert 'lang="zh-CN" aria-current="page"' in chinese_index_html
    assert (
        "https://async-hyperliquid.readthedocs.io/en/latest/howto/orders.html"
        in orders_html
    )
    assert (
        "https://async-hyperliquid.readthedocs.io/zh-cn/latest/howto/orders.html"
        in orders_html
    )
    assert "yuqi.lyle@gmail.com" not in rendered_site
