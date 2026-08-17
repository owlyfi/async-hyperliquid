# Project About and License Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add public author and MIT license pages without exposing the author's email address.

**Architecture:** Keep public presentation in two focused RST pages under `docs/project/`. Treat `pyproject.toml` and `LICENSE` as canonical inputs, with a package test enforcing content, navigation, and privacy boundaries.

**Tech Stack:** Sphinx, reStructuredText, pytest, uv

## Global Constraints

- Display the author name exactly as `Yuki`.
- Do not publish `yuqi.lyle@gmail.com` or another author email address.
- Display the canonical MIT license text from `LICENSE`.
- Keep internal planning material under `dev-docs/`.

---

### Task 1: Add and validate public project information

**Files:**
- Create: `docs/project/about.rst`
- Create: `docs/project/license.rst`
- Modify: `docs/project/index.rst`
- Test: `tests/package/test_docs.py`

**Interfaces:**
- Consumes: project author/license metadata from `pyproject.toml` and legal text from `LICENSE`
- Produces: Sphinx pages `project/about.html` and `project/license.html`

- [ ] **Step 1: Write the failing content/privacy test**

Extend the real Sphinx build test to require generated About and License HTML,
assert `Yuki` and `MIT License` in those artifacts, and assert the author email
is absent from every generated HTML page.

- [ ] **Step 2: Run the focused test to verify RED**

Run: `uv run pytest -q tests/package/test_docs.py`

Expected: FAIL because `docs/project/about.rst` and
`docs/project/license.rst` do not exist.

- [ ] **Step 3: Add the minimal RST pages and navigation**

Create an About page with `Yuki`, repository, and issue-tracker links. Create a
License page with the MIT identifier, canonical repository link, and a Sphinx
`literalinclude` of `../../LICENSE`. Add both pages to
`docs/project/index.rst`.

- [ ] **Step 4: Run focused and documentation verification**

Run: `uv run pytest -q tests/package/test_docs.py`

Run: `uv run --frozen --group docs sphinx-build -E -a -W --keep-going -b html docs docs/_build/html`

Expected: all package docs tests pass and Sphinx exits zero without warnings.

- [ ] **Step 5: Run repository quality checks**

Run: `uv run ruff format --check tests/package/test_docs.py`

Run: `uv run ruff check tests/package/test_docs.py`

Run: `uv run ty check tests/package/test_docs.py`

Run: `git diff --check`

Expected: every command exits zero. Leave changes uncommitted for the user's
existing local `main` worktree.
