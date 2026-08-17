# Read the Docs localization runbook

English files under `docs/` are the canonical documentation sources. Simplified
Chinese narrative translations live in
`docs/locale/zh_CN/LC_MESSAGES/*.po`. Keep Python names, signatures, type names,
code samples, and generated autodoc content in English.

## Update the catalogs

After changing an English documentation source, extract fresh messages and merge
them into the existing Simplified Chinese catalogs:

```console
uv run --group docs sphinx-build -E -a -W --keep-going -b gettext docs docs/_build/gettext
uv run --group docs sphinx-intl update -p docs/_build/gettext -l zh_CN -d docs/locale
```

Translate only the resulting `.po` files. Do not commit `.pot`, `.mo`, or
`docs/_build/` output. Before publishing, remove every fuzzy marker and fill every
narrative message checked by `tests/package/test_docs.py`.

## Preview both languages locally

Build both sites with the same strict settings used in CI:

```console
uv run --frozen --group docs sphinx-build -E -a -W --keep-going -D language=en -b html docs docs/_build/html/en
uv run --frozen --group docs sphinx-build -E -a -W --keep-going -D language=zh_CN -b html docs docs/_build/html/zh_CN
uv run python -m http.server 8000 -d docs/_build/html
```

Open `http://localhost:8000/en/` for English or
`http://localhost:8000/zh_CN/` for Simplified Chinese.

## Configure Read the Docs

Read the Docs hosts each language as a separate project. Keep the current project
as the English parent, then:

1. Import this same repository as a second Read the Docs project.
2. In the second project's settings, choose Simplified Chinese as its language.
3. Open the English project's **Translations** settings and add the Chinese
   project as a translation.
4. Build both projects and confirm that the Read the Docs language flyout links
   them in both directions.

The repository configuration and catalogs prepare both builds, but creating and
linking the second hosted project is an account-level Read the Docs operation.
See the official
[Sphinx translation guide](https://docs.readthedocs.com/platform/stable/guides/manage-translations-sphinx.html)
and [localization reference](https://docs.readthedocs.com/platform/latest/localization.html).

## Release checks

Run the focused documentation checks before a release:

```console
uv run --frozen pytest tests/package/test_docs.py
```

The CI and release workflows also build English and Simplified Chinese with
warnings treated as errors. Source distributions include `.po` catalogs so users
can reproduce either site, while generated `.mo` and `_build` output stay out of
the package.
