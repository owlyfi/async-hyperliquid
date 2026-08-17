from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[2]
PUBLIC_DOC_SUFFIXES = {".md", ".rst"}
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


def test_docs_tree_builds_with_warnings_as_errors(tmp_path: Path) -> None:
    output_dir = tmp_path / "html"
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
            "-W",
            "--keep-going",
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
    assert (output_dir / "index.html").is_file()

    about_html = (output_dir / "project" / "about.html").read_text(encoding="utf-8")
    license_html = (output_dir / "project" / "license.html").read_text(encoding="utf-8")
    rendered_site = "\n".join(
        path.read_text(encoding="utf-8") for path in output_dir.rglob("*.html")
    )

    assert "Yuki" in about_html
    assert "MIT License" in license_html
    assert "yuqi.lyle@gmail.com" not in rendered_site
