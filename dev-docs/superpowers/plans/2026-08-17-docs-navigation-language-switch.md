# Documentation Navigation and Language Switch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish accurate README badges and documentation links, simplify the Furo brand title, and provide a working English/Simplified Chinese switch backed by native Read the Docs translations.

**Architecture:** Keep English sources canonical and the existing `zh_CN` gettext catalogs unchanged. Read the Docs hosts one English parent project and one linked Simplified Chinese translation project; a small Furo sidebar fragment generates page-preserving links from Sphinx page context, while repository tests exercise the rendered HTML rather than template source text.

**Tech Stack:** Python 3.12, uv, Sphinx, Furo, Jinja templates, gettext catalogs, pytest, markdown-it-py, Read the Docs Community.

## Global Constraints

- Public documentation uses `https://async-hyperliquid.readthedocs.io/en/latest/` until the next immutable release advances `stable`.
- The visible sidebar/mobile brand is exactly `async-hyperliquid`.
- The switch is directly below the brand and reads `English | 简体中文`.
- Hosted Chinese URLs use `zh-cn`; Sphinx catalogs remain exactly `zh_CN`.
- Python identifiers, signatures, type names, code, and autodoc output remain English.
- Author email remains absent from rendered documentation.
- Do not move or replace `v1.0.0`.
- Use strict warning-as-error English and Chinese builds with network access blocked.
- Publish the existing parity-gated signing benchmark overall data; do not
  fabricate or rerun benchmark results for this documentation change.
- Label the benchmark as a `1.0.0rc1` local CPU reference, not network latency
  or exchange throughput.
- Keep the marker-delimited overall content identical in the detailed benchmark
  manual, root README, and Read the Docs source.

---

## File map

- `README.md`: consumer-facing badges and explicit Read the Docs destinations.
- `pyproject.toml`: canonical published Documentation project URL.
- `tests/package/test_readme.py`: parses README Markdown destinations and ties the cache key to package metadata.
- `tests/package/test_release_workflow.py`: enforces the published project URL contract.
- `benchmarks/README.md`: detailed benchmark record and canonical overall block.
- `docs/project/benchmarks.md`: public benchmark context and overall table.
- `docs/locale/zh_CN/LC_MESSAGES/project/benchmarks.po`: translated benchmark narrative.
- `tests/package/test_wheel.py`: ensures the new public page and catalog ship.
- `docs/conf.py`: concise title, Read the Docs locale normalization, page context, and Furo sidebar composition.
- `docs/_templates/sidebar/language-switcher.html`: accessible page-preserving language links only.
- `docs/_static/language-switcher.css`: minimal spacing and active-language styling only.
- `tests/package/test_docs.py`: builds real English/Chinese HTML and verifies visible title/switch behavior.
- `dev-docs/readthedocs-localization.md`: exact external project creation, linking, validation, and rollback runbook.

### Task 1: Refresh README badge and documentation destinations

**Files:**
- Modify: `tests/package/test_readme.py`
- Modify: `tests/package/test_release_workflow.py`
- Modify: `README.md`
- Modify: `pyproject.toml`

**Interfaces:**
- Consumes: `[project].version` from `pyproject.toml`.
- Produces: a dynamic Shields source whose `v` query equals `1.0.0`, plus explicit `/en/latest/` documentation links used by readers and package indexes.

- [ ] **Step 1: Write failing consumer-visible destination tests**

Add a Markdown destination helper and a focused test to `tests/package/test_readme.py`:

```python
from urllib.parse import parse_qs, urlparse

from markdown_it import MarkdownIt
import tomllib


def _readme_destinations(readme: str) -> tuple[set[str], set[str]]:
    links: set[str] = set()
    images: set[str] = set()
    for token in MarkdownIt("commonmark").parse(readme):
        for child in token.children or ():
            if child.type == "link_open":
                href = child.attrGet("href")
                if href is not None:
                    links.add(href)
            elif child.type == "image":
                src = child.attrGet("src")
                if src is not None:
                    images.add(src)
    return links, images


def test_readme_uses_current_release_badge_and_explicit_latest_docs() -> None:
    readme = (ROOT / "README.md").read_text()
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    links, images = _readme_destinations(readme)

    badge = next(url for url in images if "/pypi/v/async-hyperliquid" in url)
    assert parse_qs(urlparse(badge).query) == {"v": [project["version"]]}
    assert "https://async-hyperliquid.readthedocs.io/en/latest/" in links
    assert (
        "https://async-hyperliquid.readthedocs.io/en/latest/reference/index.html"
        in links
    )
    assert (
        "https://async-hyperliquid.readthedocs.io/en/latest/"
        "migration-0.5-to-1.0.html"
        in links
    )
    assert "https://async-hyperliquid.readthedocs.io/" not in links
```

Change `test_published_project_urls_use_current_repository` in
`tests/package/test_release_workflow.py` to require:

```python
assert (
    urls["Documentation"]
    == "https://async-hyperliquid.readthedocs.io/en/latest/"
)
```

The production mutations these tests catch are a stale badge cache key and a
link reverting to an unversioned, `stable`, or obsolete path.

- [ ] **Step 2: Run RED tests**

Run:

```bash
uv run --frozen pytest -q \
  tests/package/test_readme.py::test_readme_uses_current_release_badge_and_explicit_latest_docs \
  tests/package/test_release_workflow.py::test_published_project_urls_use_current_repository
```

Expected: both tests fail because the badge has no `v=1.0.0` cache key and the
Documentation URL is unversioned.

- [ ] **Step 3: Apply the minimal link changes**

Use these exact public destinations:

```markdown
[![Documentation Status](https://readthedocs.org/projects/async-hyperliquid/badge/?version=latest)](https://async-hyperliquid.readthedocs.io/en/latest/)
[![PyPI](https://img.shields.io/pypi/v/async-hyperliquid.svg?v=1.0.0)](https://pypi.org/project/async-hyperliquid/)
```

Set all three README prose links to the explicit `/en/latest/` root and set:

```toml
Documentation = "https://async-hyperliquid.readthedocs.io/en/latest/"
```

- [ ] **Step 4: Run GREEN tests**

Run the same two-test command. Expected: `2 passed`.

- [ ] **Step 5: Commit Task 1**

```bash
git add README.md pyproject.toml tests/package/test_readme.py tests/package/test_release_workflow.py
git commit -m "docs: refresh published documentation links"
```

### Task 2: Publish the overall signing benchmark at both public entry points

**Files:**
- Modify: `benchmarks/README.md`
- Modify: `README.md`
- Modify: `docs/project/index.rst`
- Create: `docs/project/benchmarks.md`
- Create: `docs/locale/zh_CN/LC_MESSAGES/project/benchmarks.po`
- Modify: `tests/package/test_readme.py`
- Modify: `tests/package/test_docs.py`
- Modify: `tests/package/test_wheel.py`

**Interfaces:**
- Consumes: the existing parity-gated signing benchmark overall values already
  published in `benchmarks/README.md`.
- Produces: one marker-delimited Markdown block copied unchanged to all three
  source entry points, plus rendered English and Simplified Chinese benchmark
  pages.

- [ ] **Step 1: Write failing consistency and rendered-page tests**

In `tests/package/test_readme.py`, add a strict marker extractor and compare the
three public copies:

```python
SIGNING_OVERALL_START = "<!-- signing-benchmark:overall:start -->"
SIGNING_OVERALL_END = "<!-- signing-benchmark:overall:end -->"


def _marked_block(text: str, start: str, end: str) -> str:
    assert text.count(start) == 1
    assert text.count(end) == 1
    return text.split(start, 1)[1].split(end, 1)[0].strip()


def test_public_signing_benchmark_overall_blocks_match() -> None:
    sources = (
        ROOT / "benchmarks" / "README.md",
        ROOT / "README.md",
        ROOT / "docs" / "project" / "benchmarks.md",
    )
    blocks = {
        _marked_block(path.read_text(), SIGNING_OVERALL_START, SIGNING_OVERALL_END)
        for path in sources
    }

    assert len(blocks) == 1
    block = blocks.pop()
    assert "| async-hyperliquid | 24,641 ops/s | 1.460x |" in block
    assert "| Official SDK | 16,874 ops/s | 1.000x |" in block
    assert "| CCXT | 803 ops/s | 0.0476x |" in block
```

Extend the English and Chinese rendered-document tests in
`tests/package/test_docs.py` to require `project/benchmarks.html`, the three
library names, all three throughput/relative values, and these presentation
contracts:

```python
assert "Overall comparison" in english_benchmarks_html
assert "local CPU reference" in english_benchmarks_html
assert "not network latency or exchange throughput" in english_benchmarks_html
assert "总体比较" in chinese_benchmarks_html
assert "本地 CPU 参考结果" in chinese_benchmarks_html
```

Add `project/benchmarks.po` to `NARRATIVE_CATALOGS`. Extend
`tests/package/test_wheel.py`'s expected public-doc subset with:

```python
"docs/project/benchmarks.md",
"docs/locale/zh_CN/LC_MESSAGES/project/benchmarks.po",
```

- [ ] **Step 2: Run RED tests**

Run:

```bash
UV_CACHE_DIR=/private/tmp/async-hyperliquid-docs-nav-uv-cache \
uv run --frozen pytest -q \
  tests/package/test_readme.py::test_public_signing_benchmark_overall_blocks_match \
  tests/package/test_docs.py::test_english_docs_build_with_warnings_as_errors \
  tests/package/test_docs.py::test_simplified_chinese_docs_translate_narrative_and_preserve_api_names
```

Expected: the benchmark contract fails because the public copies and markers do
not exist; rendered-page assertions fail because Sphinx has no benchmark page.

- [ ] **Step 3: Add the three identical overall blocks and benchmark page**

Wrap the existing detailed-manual table and its geometric-mean explanation in:

```markdown
<!-- signing-benchmark:overall:start -->
| Library | Geometric-mean throughput | Relative to SDK |
|---|---:|---:|
| async-hyperliquid | 24,641 ops/s | 1.460x |
| Official SDK | 16,874 ops/s | 1.000x |
| CCXT | 803 ops/s | 0.0476x |

The geometric mean gives each of the five operations equal weight, preventing
the faster `action_hash` workload from dominating the score.
<!-- signing-benchmark:overall:end -->
```

Copy that block without edits into a new README `Benchmarks` section immediately
after the project introduction and into `docs/project/benchmarks.md`. Outside
the markers, both public entry points must state that the values are from a
parity-gated `1.0.0rc1` local CPU reference run and are not network latency or
exchange throughput. Link each to the detailed `benchmarks/README.md` manual.

Add `benchmarks` to `docs/project/index.rst` immediately after `about`. Generate
the new gettext catalog through the existing Sphinx workflow and translate all
new narrative/presentation labels into Simplified Chinese. Keep
`async-hyperliquid`, `Official SDK`, `CCXT`, `action_hash`, versions, units, and
all numerical values unchanged.

- [ ] **Step 4: Run GREEN tests**

Run the same focused command. Expected: `3 passed`, both Sphinx builds strict
and offline with no warnings.

- [ ] **Step 5: Mutation-check the shared content contract**

Temporarily change `24,641` to `24,642` in only `README.md`, run the benchmark
consistency test, and confirm it fails. Restore the value and rerun to green.

- [ ] **Step 6: Commit Task 2**

```bash
git add benchmarks/README.md README.md docs/project/index.rst \
  docs/project/benchmarks.md \
  docs/locale/zh_CN/LC_MESSAGES/project/benchmarks.po \
  tests/package/test_readme.py tests/package/test_docs.py tests/package/test_wheel.py
git commit -m "docs: publish overall signing benchmark"
```

### Task 3: Render the concise brand and accessible language switch

**Files:**
- Modify: `tests/package/test_docs.py`
- Modify: `docs/conf.py`
- Create: `docs/_templates/sidebar/language-switcher.html`
- Create: `docs/_static/language-switcher.css`

**Interfaces:**
- Consumes: Sphinx `pagename`, final `app.config.language`, and `READTHEDOCS_VERSION`.
- Produces: page context keys `documentation_language` (`en` or `zh-cn`) and `documentation_version` (`latest` fallback), plus two ordinary hosted-language anchors.

- [ ] **Step 1: Make the real docs builds simulate Read the Docs language metadata**

Update `_build_docs` in `tests/package/test_docs.py` so the subprocess receives
`READTHEDOCS_VERSION=latest` and `READTHEDOCS_LANGUAGE=en` or `zh-cn`. Remove the
test helper's `-D language=...` arguments so the Chinese test proves the hosted
`zh-cn` value is normalized by `docs/conf.py`:

```python
hosted_language = "zh-cn" if language == "zh_CN" else "en"
environment = {
    **os.environ,
    "READTHEDOCS_LANGUAGE": hosted_language,
    "READTHEDOCS_VERSION": "latest",
}
result = subprocess.run(
    [
        "uv", "run", "--frozen", "--group", "docs", "python", "-c",
        OFFLINE_SPHINX_SCRIPT, "-E", "-a", "-W", "--keep-going",
        "-b", "html", "docs", str(output_dir),
    ],
    cwd=ROOT,
    env=environment,
    capture_output=True,
    text=True,
    check=False,
)
```

- [ ] **Step 2: Add failing rendered-artifact assertions**

Rename the existing rendered-index variables to `english_index_html` and
`chinese_index_html`. For both indexes, require the exact brand fragment, both
language destinations, and the correct active link. For the nested orders page,
require destinations ending in `howto/orders.html`:

```python
brand = '<span class="sidebar-brand-text">async-hyperliquid</span>'
english_index = "https://async-hyperliquid.readthedocs.io/en/latest/index.html"
chinese_index = "https://async-hyperliquid.readthedocs.io/zh-cn/latest/index.html"

assert brand in english_index_html
assert brand in chinese_index_html
assert "async-hyperliquid 1.0.0 documentation" not in english_index_html
assert "async-hyperliquid 1.0.0 documentation" not in chinese_index_html
assert english_index in english_index_html
assert chinese_index in english_index_html
assert english_index in chinese_index_html
assert chinese_index in chinese_index_html
assert 'lang="en" aria-current="page"' in english_index_html
assert 'lang="zh-CN" aria-current="page"' in chinese_index_html
assert "https://async-hyperliquid.readthedocs.io/en/latest/howto/orders.html" in orders_html
assert "https://async-hyperliquid.readthedocs.io/zh-cn/latest/howto/orders.html" in orders_html
```

Keep the existing translation, API-name, autodoc-English, license, author, and
email-privacy assertions unchanged.

The production mutations these checks catch are removal of `html_title`, wrong
locale normalization, a root-only switch, or an incorrect active language.

- [ ] **Step 3: Run RED docs tests**

Run:

```bash
UV_CACHE_DIR=/private/tmp/async-hyperliquid-docs-nav-uv-cache \
uv run --frozen pytest -q \
  tests/package/test_docs.py::test_english_docs_build_with_warnings_as_errors \
  tests/package/test_docs.py::test_simplified_chinese_docs_translate_narrative_and_preserve_api_names
```

Expected: rendered-title/language-link assertions fail because no custom title,
locale mapping, or language fragment exists.

- [ ] **Step 4: Implement the Sphinx context and sidebar composition**

In `docs/conf.py`, import `os`, normalize the hosted locale, and inject context
after command-line configuration is final:

```python
import os


_HOSTED_TO_SPHINX_LANGUAGE = {"en": "en", "zh-cn": "zh_CN"}
_SPHINX_TO_HOSTED_LANGUAGE = {value: key for key, value in _HOSTED_TO_SPHINX_LANGUAGE.items()}

rtd_language = os.environ.get("READTHEDOCS_LANGUAGE")
if rtd_language is not None:
    try:
        language = _HOSTED_TO_SPHINX_LANGUAGE[rtd_language]
    except KeyError as exc:
        raise RuntimeError(f"unsupported Read the Docs language: {rtd_language}") from exc

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
    context["documentation_version"] = os.environ.get(
        "READTHEDOCS_VERSION", "latest"
    )


def setup(app):
    app.connect("html-page-context", _add_documentation_context)
```

Keep this configuration hook unannotated: `conf.py` is executed by Sphinx and
is not a public package API, so no new runtime typing dependency is introduced.

- [ ] **Step 5: Create the semantic language template**

Create `docs/_templates/sidebar/language-switcher.html`:

```jinja
<nav class="sidebar-language-switch" aria-label="Documentation language">
  <a href="https://async-hyperliquid.readthedocs.io/en/{{ documentation_version }}/{{ pagename }}.html"
     lang="en"{% if documentation_language == "en" %} aria-current="page"{% endif %}>English</a>
  <span aria-hidden="true">|</span>
  <a href="https://async-hyperliquid.readthedocs.io/zh-cn/{{ documentation_version }}/{{ pagename }}.html"
     lang="zh-CN"{% if documentation_language == "zh-cn" %} aria-current="page"{% endif %}>简体中文</a>
</nav>
```

Create `docs/_static/language-switcher.css` with only layout and active-state
rules:

```css
.sidebar-language-switch {
  align-items: center;
  display: flex;
  font-size: 0.875rem;
  gap: 0.5rem;
  justify-content: center;
  margin: -0.5rem 0 0.75rem;
}

.sidebar-language-switch a[aria-current="page"] {
  color: var(--color-foreground-primary);
  font-weight: 600;
  text-decoration: none;
}
```

- [ ] **Step 6: Run GREEN docs tests**

Run the same two docs tests with the isolated `UV_CACHE_DIR`. Expected:
`2 passed`, with both strict builds producing no warnings.

- [ ] **Step 7: Mutation-check the locale bridge**

Temporarily change the `zh-cn` mapping to `zh-cn`, run only the Chinese docs
test, and confirm it fails because translated narrative text is missing. Restore
`zh_CN` and rerun to green.

- [ ] **Step 8: Commit Task 3**

```bash
git add docs/conf.py docs/_templates/sidebar/language-switcher.html \
  docs/_static/language-switcher.css tests/package/test_docs.py
git commit -m "docs: add documentation language switch"
```

### Task 4: Make the external publishing runbook exact

**Files:**
- Modify: `dev-docs/readthedocs-localization.md`

**Interfaces:**
- Consumes: English project `async-hyperliquid`, Chinese project slug `async-hyperliquid-zh-cn`, repository `owlyfi/async-hyperliquid`, and the `latest` URLs produced by Task 3.
- Produces: an operator checklist for project creation, translation linking, build monitoring, validation, and rollback.

- [ ] **Step 1: Replace generic account-level instructions with exact values**

Document these steps explicitly:

```markdown
1. Import `https://github.com/owlyfi/async-hyperliquid.git` as
   `async-hyperliquid-zh-cn`.
2. Set its language to Simplified Chinese, default branch to `main`, and default
   version to `latest`. Leave the Build configuration file/path field at its
   default so the root `.readthedocs.yaml` is auto-discovered, or enter
   `.readthedocs.yaml` without a leading slash.
3. Add `async-hyperliquid-zh-cn` under the parent project's Translations page.
4. Require successful `latest` builds for both projects.
5. Verify `/en/latest/` and `/zh-cn/latest/` root and nested pages, then click
   both sidebar language links.
6. For a custom sidebar/layout regression, remove or hide the custom language
   fragment, publish and verify English without the custom anchor, and retain
   the Translation relationship for Read the Docs' native language UI. Unlink
   only if Chinese hosting is being retired or remains unusable, and only after
   the custom anchor is absent; never change `v1.0.0`.
```

- [ ] **Step 2: Review the runbook as human operational prose**

Confirm it contains no credentials, email address, placeholder, ambiguous
project slug, or instruction to mutate `v1.0.0`. No source-text test is added;
this runbook is for human operators and its real validation occurs in Task 6.

- [ ] **Step 3: Commit Task 4**

```bash
git add dev-docs/readthedocs-localization.md
git commit -m "docs: document Read the Docs translation publishing"
```

### Task 5: Run repository verification and local browser acceptance

**Files:**
- Verify only; no intended source changes.

**Interfaces:**
- Consumes: Tasks 1-3.
- Produces: local evidence that links, builds, titles, language state, layout, and privacy requirements are satisfied.

- [ ] **Step 1: Run formatting, lint, and typing**

```bash
UV_CACHE_DIR=/private/tmp/async-hyperliquid-docs-nav-uv-cache uv run ruff format
UV_CACHE_DIR=/private/tmp/async-hyperliquid-docs-nav-uv-cache uv run ruff check
UV_CACHE_DIR=/private/tmp/async-hyperliquid-docs-nav-uv-cache uv run ty check
git diff --check
```

Expected: every command exits zero and Ruff reports no remaining formatting or
lint changes.

- [ ] **Step 2: Build a fresh 1.0.0 artifact and run package tests**

Build into a new task-specific temporary directory, then run:

```bash
docs_nav_artifacts="$(mktemp -d /private/tmp/async-hyperliquid-docs-nav.XXXXXX)"
UV_CACHE_DIR=/private/tmp/async-hyperliquid-docs-nav-uv-cache \
uv build --no-sources --clear --out-dir "$docs_nav_artifacts"
UV_CACHE_DIR=/private/tmp/async-hyperliquid-docs-nav-uv-cache \
ASYNC_HYPERLIQUID_WHEEL_DIR="$docs_nav_artifacts" \
uv run --frozen pytest -q tests/package
```

Expected: all package tests pass with no stale `dist/` artifact selected.

- [ ] **Step 3: Build both local sites**

```bash
UV_CACHE_DIR=/private/tmp/async-hyperliquid-docs-nav-uv-cache \
READTHEDOCS_VERSION=latest READTHEDOCS_LANGUAGE=en \
uv run --frozen --group docs sphinx-build -E -a -W --keep-going \
  -b html docs docs/_build/html/en

UV_CACHE_DIR=/private/tmp/async-hyperliquid-docs-nav-uv-cache \
READTHEDOCS_VERSION=latest READTHEDOCS_LANGUAGE=zh-cn \
uv run --frozen --group docs sphinx-build -E -a -W --keep-going \
  -b html docs docs/_build/html/zh_CN
```

Expected: both builds exit zero without warnings.

- [ ] **Step 4: Serve and inspect the actual HTML in the in-app browser**

Serve `docs/_build/html` on `127.0.0.1:8000`. Inspect:

```bash
uv run python -m http.server 8000 --bind 127.0.0.1 \
  --directory docs/_build/html
```

- `/en/` and `/zh_CN/` at desktop width;
- `/en/howto/orders.html` and `/zh_CN/howto/orders.html`;
- the root pages at a mobile viewport.

Require the concise brand, readable switch immediately beneath it, correct
active language, correct current-page targets, unchanged search/navigation,
and no horizontal overflow. Use the browser's semantic snapshot for text/links
and screenshots only for layout validation.

### Task 6: Publish main and configure Read the Docs translation

**Files:**
- External state only after all local gates pass.

**Interfaces:**
- Consumes: the validated commits and exact runbook.
- Produces: synchronized `origin/main`, English and Chinese `latest` builds, a native Translation relationship, and publicly working cross-language links.

- [ ] **Step 1: Recheck the push boundary**

```bash
git fetch --no-tags origin refs/heads/main:refs/remotes/origin/main
git status --short --branch
git rev-parse HEAD origin/main
```

Require no uncommitted source changes and no unexpected remote commits. If
origin advanced, merge it before push and rerun Task 5.

- [ ] **Step 2: Push the reviewed commits**

```bash
git push origin main
```

- [ ] **Step 3: Monitor GitHub CI and the English Read the Docs latest build**

Require GitHub CI success and a successful English build whose commit equals
the pushed `HEAD`. Do not create the Chinese project while the English build is
red.

- [ ] **Step 4: Create and link the Chinese project**

Using the authorized Read the Docs account, create
`async-hyperliquid-zh-cn` with the exact Task 4 settings, then add it as a
Translation of `async-hyperliquid`. Do not create API tokens or expose account
credentials.

- [ ] **Step 5: Verify public channels**

Require HTTP 200 and correct rendered content for:

```text
https://async-hyperliquid.readthedocs.io/en/latest/
https://async-hyperliquid.readthedocs.io/zh-cn/latest/
https://async-hyperliquid.readthedocs.io/en/latest/howto/orders.html
https://async-hyperliquid.readthedocs.io/zh-cn/latest/howto/orders.html
```

Verify the Read the Docs Translations API returns the Chinese project, then use
the browser to click English → 简体中文 and 简体中文 → English on the same nested
page. Confirm the GitHub README badge source renders `v1.0.0` and every docs
link resolves without a 404.

- [ ] **Step 6: Archive task and review state**

Create terminal records under `.agent/state_archive/` and
`.agent/review_archive/`, compact `.agent/state.md` and
`.agent/review_notes.md`, and remove `.agent/task.md`. These ignored ledger
files are not added to Git.
