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
