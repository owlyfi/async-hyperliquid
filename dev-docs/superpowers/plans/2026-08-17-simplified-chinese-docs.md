# Simplified Chinese Documentation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a complete, maintainable Simplified Chinese documentation build using Sphinx gettext while preserving English API identifiers and autodoc content.

**Architecture:** English RST/Markdown files remain canonical. Sphinx extracts their messages into gettext catalogs, and committed `zh_CN` `.po` files translate narrative domains; independent English and Chinese warning-as-error builds protect both outputs.

**Tech Stack:** Python 3.12, uv, Sphinx 9, sphinx-intl, Furo, gettext PO catalogs, pytest

## Global Constraints

- Locale code is exactly `zh_CN`.
- English source documents remain the only structural source of truth.
- Python identifiers, signatures, type names, module paths, code blocks, wire fields, and autodoc-generated content remain English.
- Do not translate the canonical MIT license literal block.
- Both language builds run offline with `-E -a -W --keep-going`.
- Do not commit generated `.pot`, `.mo`, or `docs/_build/**` files.
- Leave this implementation uncommitted unless the user separately requests a commit.

---

### Task 1: Add gettext infrastructure and failing bilingual build contracts

**Files:**
- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Modify: `docs/conf.py`
- Modify: `tests/package/test_docs.py`

**Interfaces:**
- Consumes: canonical docs under `docs/` and the locked `docs` dependency group
- Produces: Sphinx locale discovery at `docs/locale/` and independent `en`/`zh_CN` HTML artifacts

- [ ] **Step 1: Extend rendered-artifact tests before adding catalogs**

Refactor the existing Sphinx subprocess into a helper that accepts a language
and output directory. Build `en` and `zh_CN`, then require representative
Chinese text in `zh_CN/index.html` and `zh_CN/howto/orders.html`, require
`AsyncHyperliquid`, `InfoClient`, and `PlaceOrderRequest` to remain present in
the Chinese reference output, and scan both sites for the private author email.

- [ ] **Step 2: Run the focused test and verify RED**

Run: `uv run pytest -q tests/package/test_docs.py`

Expected: FAIL because the Chinese build falls back to English and contains no
representative Chinese narrative.

- [ ] **Step 3: Add locked gettext tooling and Sphinx configuration**

Add `sphinx-intl` to `[dependency-groups].docs`, run `uv lock`, and configure:

```python
locale_dirs = ["locale/"]
gettext_compact = False
gettext_uuid = True
```

- [ ] **Step 4: Extract catalogs and initialize zh_CN PO files**

Run:

```bash
uv run --group docs sphinx-build -E -a -W --keep-going -b gettext docs docs/_build/gettext
uv run --group docs sphinx-intl update -p docs/_build/gettext -l zh_CN -d docs/locale
```

Expected: one catalog per source doc under
`docs/locale/zh_CN/LC_MESSAGES/`, with no generated output outside ignored
`docs/_build/`.

- [ ] **Step 5: Run the focused test and confirm it still fails only for untranslated messages**

Run: `uv run pytest -q tests/package/test_docs.py`

Expected: FAIL on the representative Chinese assertions, not configuration,
catalog discovery, network, or Sphinx warnings.

---

### Task 2: Translate narrative catalogs while preserving the API boundary

**Files:**
- Create/Modify: `docs/locale/zh_CN/LC_MESSAGES/index.po`
- Create/Modify: `docs/locale/zh_CN/LC_MESSAGES/introduction/*.po`
- Create/Modify: `docs/locale/zh_CN/LC_MESSAGES/howto/*.po`
- Create/Modify: `docs/locale/zh_CN/LC_MESSAGES/project/*.po`
- Create/Modify: `docs/locale/zh_CN/LC_MESSAGES/coin-name-mapping.po`
- Create/Modify: `docs/locale/zh_CN/LC_MESSAGES/migration-0.5-to-1.0.po`
- Create/Modify: `docs/locale/zh_CN/LC_MESSAGES/reference/index.po`
- Create: `dev-docs/readthedocs-localization.md`
- Test: `tests/package/test_docs.py`

**Interfaces:**
- Consumes: gettext msgids extracted from the canonical English sources
- Produces: Simplified Chinese narrative with English protocol/API vocabulary and autodoc fallback

- [ ] **Step 1: Translate every selected narrative msgstr**

Translate root, Introduction, How-to, mapping, migration, Project, and API
Reference navigation messages. Preserve every RST role, target, substitution,
literal, URL, protocol field, and Python identifier exactly.

- [ ] **Step 2: Keep autodoc and literal content untranslated**

Do not translate catalogs whose only purpose is an automodule/autoclass page.
Leave code examples, signatures, wire fields, and the MIT literal include in
English. Do not enable `gettext_additional_targets` for literal blocks.

- [ ] **Step 3: Document the maintenance and hosted setup workflow**

Create `dev-docs/readthedocs-localization.md` with exact extraction, catalog
update, English/Chinese preview commands, and the external Read the Docs steps:
create a Simplified Chinese project using the same repository, set Language to
Simplified Chinese, then add it as a Translation of the English parent project.

- [ ] **Step 4: Add a selected-domain translation completeness gate**

Use `babel.messages.pofile.read_po` to load the committed narrative catalogs.
For the explicit root, Introduction, How-to, mapping, migration, Project, and
Reference-index domain list, fail when a non-obsolete message with a non-empty
msgid has an empty `msgstr`. Do not include autodoc-only Reference domains or
literal blocks in this gate.

- [ ] **Step 5: Verify the bilingual rendered-artifact contract turns GREEN**

Run: `uv run pytest -q tests/package/test_docs.py`

Expected: both offline builds pass, representative narrative is Chinese, API
identifiers remain English, and neither rendered site exposes the author email.

---

### Task 3: Gate both languages in CI, release, and packaging

**Files:**
- Modify: `.github/workflows/ci.yml`
- Modify: `.github/workflows/release.yml`
- Modify: `tests/package/test_release_workflow.py`
- Modify: `tests/package/test_wheel.py`

**Interfaces:**
- Consumes: the docs dependency group and committed `zh_CN` PO catalogs
- Produces: mandatory English and Chinese docs gates and sdist locale coverage

- [ ] **Step 1: Write failing workflow and package assertions**

Require CI and release to build English into `docs/_build/html/en` and Chinese
with `-D language=zh_CN` into `docs/_build/html/zh_CN`. Require the sdist to
include committed `docs/locale/zh_CN/LC_MESSAGES/*.po` files and exclude `.mo`,
gettext, and HTML build output.

- [ ] **Step 2: Run focused package tests and verify RED**

Run: `uv run pytest -q tests/package/test_release_workflow.py tests/package/test_wheel.py`

Expected: FAIL because workflows still build only English and the fresh
artifact has not yet been checked for locale catalogs.

- [ ] **Step 3: Add the two strict workflow commands**

Use separate English and Chinese Sphinx invocations, both with
`-E -a -W --keep-going`; pass `-D language=zh_CN` only to the Chinese build.

- [ ] **Step 4: Run complete verification**

Run:

```bash
uv lock --check
uv run ruff format
uv run ruff check src tests benchmarks docs/conf.py scripts
uv run ty check
uv run pytest -q tests/unit tests/public_api tests/contracts tests/package
uv build --no-sources --clear
ASYNC_HYPERLIQUID_WHEEL_DIR=dist uv run pytest -q tests/package
git diff --check
```

Expected: all commands exit zero; both strict Sphinx builds occur inside the
package tests; the implementation remains uncommitted.
