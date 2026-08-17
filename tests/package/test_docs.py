from pathlib import Path
import re
import subprocess


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


def _build_docs(language: str, output_dir: Path) -> None:
    result = subprocess.run(
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
            "-D",
            f"language={language}",
            "-b",
            "html",
            "docs",
            str(output_dir),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr


def test_english_docs_build_with_warnings_as_errors(tmp_path: Path) -> None:
    output_dir = tmp_path / "en"
    _build_docs("en", output_dir)

    assert (output_dir / "index.html").is_file()

    about_html = (output_dir / "project" / "about.html").read_text(encoding="utf-8")
    license_html = (output_dir / "project" / "license.html").read_text(encoding="utf-8")
    rendered_site = "\n".join(
        path.read_text(encoding="utf-8") for path in output_dir.rglob("*.html")
    )

    assert "Yuki" in about_html
    assert "MIT License" in license_html
    assert "yuqi.lyle@gmail.com" not in rendered_site


def test_simplified_chinese_docs_translate_narrative_and_preserve_api_names(
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "zh_CN"
    _build_docs("zh_CN", output_dir)

    index_html = (output_dir / "index.html").read_text(encoding="utf-8")
    orders_html = (output_dir / "howto" / "orders.html").read_text(encoding="utf-8")
    async_client_html = (output_dir / "reference" / "async-hyperliquid.html").read_text(
        encoding="utf-8"
    )
    info_client_html = (output_dir / "reference" / "info-client.html").read_text(
        encoding="utf-8"
    )
    types_html = (output_dir / "reference" / "types.html").read_text(encoding="utf-8")
    errors_html = (output_dir / "reference" / "errors.html").read_text(encoding="utf-8")
    rendered_site = "\n".join(
        path.read_text(encoding="utf-8") for path in output_dir.rglob("*.html")
    )

    assert "异步、带类型的 Python 客户端" in index_html
    assert "单笔和批量操作" in orders_html
    assert "错误" in errors_html
    assert "AsyncHyperliquid" in async_client_html
    assert "InfoClient" in info_client_html
    assert "PlaceOrderRequest" in types_html
    assert "Resource owner plus intent-level order workflows." in async_client_html
    assert (
        "Asynchronous, credential-free client for Hyperliquid Info endpoints."
        in info_client_html
    )
    assert "A validated 16-byte hexadecimal client order ID." in types_html
    assert "yuqi.lyle@gmail.com" not in rendered_site
