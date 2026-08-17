import os
import re
from importlib.metadata import metadata, version as package_version


project = "async-hyperliquid"
release = package_version(project)
version = release

requires_python = metadata(project)["Requires-Python"]
minimum_python = requires_python.removeprefix(">=")
if minimum_python == requires_python:
    raise RuntimeError(
        "documentation expects a minimum-only Requires-Python package constraint"
    )

rst_prolog = "\n".join(
    (
        f".. |minimum-python| replace:: {minimum_python}",
        f".. |requires-python| replace:: ``{requires_python}``",
    )
)

extensions = [
    "myst_parser",
    "sphinx.ext.autodoc",
    "sphinx_copybutton",
    "sphinx_inline_tabs",
]

locale_dirs = ["locale/"]
gettext_compact = False
gettext_uuid = True

exclude_patterns = ["_build"]
html_theme = "furo"

_HOSTED_TO_SPHINX_LANGUAGE = {"en": "en", "zh-cn": "zh_CN"}
_SPHINX_TO_HOSTED_LANGUAGE = {
    value: key for key, value in _HOSTED_TO_SPHINX_LANGUAGE.items()
}
_READTHEDOCS_VERSION = os.environ.get("READTHEDOCS_VERSION", "latest")
if not re.fullmatch(r"[a-z0-9._-]+", _READTHEDOCS_VERSION, flags=re.ASCII):
    raise RuntimeError(
        "READTHEDOCS_VERSION must be a non-empty Read the Docs version slug"
    )

rtd_language = os.environ.get("READTHEDOCS_LANGUAGE")
if rtd_language is not None:
    try:
        language = _HOSTED_TO_SPHINX_LANGUAGE[rtd_language]
    except KeyError as exc:
        raise RuntimeError(
            f"unsupported Read the Docs language: {rtd_language}"
        ) from exc

html_title = project
templates_path = ["_templates"]
html_static_path = ["_static"]
html_css_files = ["language-switcher.css"]
html_sidebars = {
    "**": [
        "sidebar/brand.html",
        "sidebar/language-switcher.html",
        "sidebar/search.html",
        "sidebar/scroll-start.html",
        "sidebar/navigation.html",
        "sidebar/ethical-ads.html",
        "sidebar/scroll-end.html",
        "sidebar/variant-selector.html",
    ]
}


def _add_documentation_context(app, pagename, templatename, context, doctree):
    del pagename, templatename, doctree
    rendered_language = app.config.language or "en"
    try:
        context["documentation_language"] = _SPHINX_TO_HOSTED_LANGUAGE[
            rendered_language
        ]
    except KeyError as exc:
        raise RuntimeError(
            f"unsupported Sphinx documentation language: {rendered_language}"
        ) from exc
    context["documentation_version"] = _READTHEDOCS_VERSION


def setup(app):
    app.connect("html-page-context", _add_documentation_context)
