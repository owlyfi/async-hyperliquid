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

## Publish and link the hosted projects

The existing English Read the Docs project is the parent project
`async-hyperliquid`. Create one linked Simplified Chinese project from the same
repository, and keep both projects on the repository's `main` branch and the
`latest` version. Use this operator checklist:

1. Import `https://github.com/owlyfi/async-hyperliquid.git` as
   `async-hyperliquid-zh-cn`.
2. Set its language to Simplified Chinese, default branch to `main`, and default
   version to `latest`; use `/.readthedocs.yaml` from the repository root.
3. Add `async-hyperliquid-zh-cn` under the parent project's **Translations**
   page.
4. Require successful `latest` builds for both projects.
5. Verify `https://async-hyperliquid.readthedocs.io/en/latest/` and
   `https://async-hyperliquid.readthedocs.io/zh-cn/latest/`, including the root
   and nested pages, then click both sidebar language links. Confirm that each
   link preserves the current page and points to the corresponding language.
6. If the Chinese build fails, unlink the translation before removing the
   repository language fragment; never change `v1.0.0`.

For the validation in step 5, check the English and Chinese roots plus nested
pages such as `reference/index.html` and `migration-0.5-to-1.0.html` under each
language's `/latest/` path. The language switch must lead from English to
`/zh-cn/latest/` and back to `/en/latest/`; a missing target or failed build is
not a successful publication.

If rollback is needed, first unlink `async-hyperliquid-zh-cn` from the English
parent project's **Translations** page, then remove only the Read the Docs
language-specific repository fragment. Leave the English project, repository
configuration, `main`, `latest`, and the immutable `v1.0.0` release unchanged.

Do not put credentials or email addresses in this runbook or in repository
configuration. See the official
[Sphinx translation guide](https://docs.readthedocs.com/platform/stable/guides/manage-translations-sphinx.html)
and [localization reference](https://docs.readthedocs.com/platform/latest/localization.html)
for Read the Docs UI background.

## Release checks

Run the focused documentation checks before a release:

```console
uv run --frozen pytest tests/package/test_docs.py
```

The CI and release workflows also build English and Simplified Chinese with
warnings treated as errors. Source distributions include `.po` catalogs so users
can reproduce either site, while generated `.mo` and `_build` output stay out of
the package.
