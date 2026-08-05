# PyPI Trusted Publishing Release Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a tag-triggered, tokenless release pipeline that builds one verified wheel/sdist bundle and publishes it to both PyPI and an immutable GitHub Release.

**Architecture:** A top-level `release.yml` validates the tag identity and `main` ancestry, runs the existing deterministic CI gates, builds once, stages a GitHub draft, publishes to PyPI from a separate OIDC-only job, finalizes the GitHub Release, and verifies both public channels. Contract tests inspect the workflow's security-critical structure so later edits cannot silently broaden triggers or permissions.

**Tech Stack:** GitHub Actions, `uv 0.11.32`, `uv_build`, PyPI Trusted Publishing/OIDC, `pypa/gh-action-pypi-publish`, GitHub CLI, pytest.

## Global Constraints

- Release tags are exactly `v<PEP 440 project version>`; `v1.0.0rc1` must match `version = "1.0.0rc1"`.
- The peeled tag commit must be an ancestor of `origin/main`.
- Build wheel and sdist exactly once and reuse the same Actions artifact for PyPI and GitHub Release.
- Never configure or consume a PyPI username, password, or API token.
- Only the `publish_pypi` job receives `id-token: write` and the `pypi` Environment.
- Build/test jobs have `contents: read` and cannot mint OIDC tokens.
- Create and populate a draft GitHub Release before publishing PyPI; publish the draft only after PyPI succeeds.
- All third-party actions use full commit SHAs with version comments.
- Do not add `workflow_dispatch`, TestPyPI, automatic version bumping, `skip-existing`, or a real test release tag.
- Keep existing deterministic CI commands and `uv.lock` unchanged.

---

## File Structure

| Path | Responsibility |
| --- | --- |
| `.github/workflows/release.yml` | Entire tag validation, build, staged publication, and public verification state machine |
| `.github/workflows/ci.yml` | PR and branch-push CI only; excludes tag pushes |
| `tests/package/test_release_workflow.py` | Regression contract for triggers, permissions, job ordering, fixed action SHAs, CI scope, runbook, and repository URLs |
| `docs/releasing.md` | One-time setup, repeatable release commands, verification, and partial-failure recovery |
| `pyproject.toml` | Published project links point to `owlyfi/async-hyperliquid` |

### Task 1: Add the release workflow contract and implementation

**Files:**
- Create: `tests/package/test_release_workflow.py`
- Create: `.github/workflows/release.yml`

**Interfaces:**
- Consumes: `pyproject.toml` project version, current CI commands, tag push event, GitHub `pypi` Environment.
- Produces: artifact `release-bundle-${{ github.sha }}` containing `dist/` plus `SHA256SUMS`; validated `tag`, `version`, and `prerelease` job outputs.

- [ ] **Step 1: Write the failing workflow contract tests**

Create `tests/package/test_release_workflow.py` with repository-relative readers and assertions for:

```python
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RELEASE = ROOT / ".github" / "workflows" / "release.yml"


def _release_text() -> str:
    return RELEASE.read_text(encoding="utf-8")


def test_release_workflow_is_tag_only_and_fail_closed() -> None:
    workflow = _release_text()
    assert 'tags: ["v*"]' in workflow
    assert "workflow_dispatch" not in workflow
    assert "github.repository != 'owlyfi/async-hyperliquid'" in workflow
    assert '[[ "$tag" == "v$version" ]]' in workflow
    assert 'git merge-base --is-ancestor "$release_commit" origin/main' in workflow


def test_release_workflow_scopes_publish_permissions() -> None:
    workflow = _release_text()
    assert workflow.count("id-token: write") == 1
    assert workflow.count("contents: write") == 2
    assert "environment:\n      name: pypi" in workflow
    assert "PYPI_API_TOKEN" not in workflow
    assert "password:" not in workflow
    assert "skip-existing" not in workflow


def test_release_workflow_builds_and_shares_one_bundle() -> None:
    workflow = _release_text()
    assert workflow.count("uv build --no-sources --clear") == 1
    assert "sha256sum dist/* > SHA256SUMS" in workflow
    assert "release-bundle-${{ github.sha }}" in workflow
    assert "packages-dir: release-bundle/dist" in workflow
    assert "needs: create_draft_release" in workflow
    assert "needs: publish_pypi" in workflow


def test_release_workflow_pins_every_external_action() -> None:
    workflow = _release_text()
    expected = {
        "actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd",
        "astral-sh/setup-uv@08807647e7069bb48b6ef5acd8ec9567f424441b",
        "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02",
        "actions/download-artifact@d3f86a106a0bac45b974a628896c90dbdf5c8093",
        "pypa/gh-action-pypi-publish@ed0c53931b1dc9bd32cbe73a98c7f6766f8a527e",
    }
    for action in expected:
        assert action in workflow
    for line in workflow.splitlines():
        if "uses:" in line and not line.strip().startswith("#"):
            ref = line.split("uses:", 1)[1].strip().split("#", 1)[0].strip()
            assert "@" in ref
            assert len(ref.rsplit("@", 1)[1]) == 40
```

- [ ] **Step 2: Run the focused tests and confirm the missing-file failure**

Run:

```bash
uv run pytest -q tests/package/test_release_workflow.py
```

Expected: FAIL because `.github/workflows/release.yml` does not exist.

- [ ] **Step 3: Implement the tag-only workflow shell**

Create `.github/workflows/release.yml` with:

```yaml
name: Release

on:
  push:
    tags: ["v*"]

permissions:
  contents: read

concurrency:
  group: release-${{ github.ref }}
  cancel-in-progress: false
```

Add `validate_release` on `ubuntu-24.04` with full checkout, pinned `setup-uv`, `version: "0.11.32"`, repository identity rejection, exact tag/version comparison, peeled commit resolution, explicit `origin/main` fetch, ancestry verification, prerelease classification, and `$GITHUB_OUTPUT` values named `tag`, `version`, and `prerelease`.

The validation script must contain these fail-closed operations:

```bash
if [[ "${{ github.repository }}" != "owlyfi/async-hyperliquid" ]]; then
  echo "Release workflow is restricted to owlyfi/async-hyperliquid" >&2
  exit 1
fi
tag="${GITHUB_REF_NAME}"
version="$(uv version --short)"
[[ "$tag" == "v$version" ]]
git fetch --no-tags origin refs/heads/main:refs/remotes/origin/main
release_commit="$(git rev-parse "${GITHUB_REF}^{commit}")"
git merge-base --is-ancestor "$release_commit" origin/main
```

- [ ] **Step 4: Implement deterministic testing, one build, and bundle upload**

Add `test_and_build` with `needs: validate_release`, read-only permissions, and the existing CI sequence:

```bash
uv sync --locked --dev
uv run ruff format --check
uv run ruff check src tests benchmarks
uv run ty check src/async_hyperliquid
uv run ty check tests/contracts
uv run ty check tests/integration
uv run ty check tests/oracle
uv run ty check tests/package
uv run ty check tests/public_api
uv run ty check tests/typing
uv run ty check tests/unit
uv run ty check benchmarks
uv run pytest -q tests/unit tests/public_api tests/contracts tests/package
uv build --no-sources --clear
ASYNC_HYPERLIQUID_WHEEL_DIR=dist uv run pytest -q tests/package
```

Create isolated wheel and sdist virtual environments, install each local file,
and import `AsyncHyperliquid`, `HyperliquidError`, `InfoClient`, `LimitOrder`, and
`Network`. Validate that exactly one wheel and one sdist exist and that wheel
`METADATA` contains name `async-hyperliquid` and the validated version. Then run:

```bash
sha256sum dist/* > SHA256SUMS
```

Upload `dist` and `SHA256SUMS` as `release-bundle-${{ github.sha }}` with pinned
`actions/upload-artifact`, `if-no-files-found: error`, `retention-days: 14`, and
`compression-level: 0`.

- [ ] **Step 5: Implement staged GitHub and OIDC PyPI publication**

Add these privilege-separated jobs:

- `create_draft_release`: needs `test_and_build`, grants only
  `contents: write`, downloads and verifies the bundle, rejects an existing
  release, then uses `gh release create "$tag" --draft --verify-tag
  --generate-notes --title "$tag"` with wheel, sdist, and checksum assets;
- `publish_pypi`: needs `create_draft_release`, grants `contents: read` and
  `id-token: write`, declares Environment `pypi`, downloads/verifies the
  bundle, and invokes pinned `pypa/gh-action-pypi-publish` with
  `packages-dir: release-bundle/dist`, `attestations: true`, and
  `print-hash: true`;
- `publish_github_release`: needs `publish_pypi`, grants only
  `contents: write`, and runs `gh release edit "$tag" --draft=false`.

Add `--prerelease` to draft creation when the validated prerelease output is
`true`. Every `gh` step receives only `GH_TOKEN: ${{ github.token }}`.

- [ ] **Step 6: Implement public-channel verification**

Add `verify_release` after `publish_github_release`. Download and verify the
same bundle. A stdlib Python script must poll
`https://pypi.org/pypi/async-hyperliquid/<version>/json` for at most 60 seconds,
then compare the exact two distribution filenames and their SHA-256 digests
with local `dist/`. Install `async-hyperliquid==<version>` from PyPI into a new
uv venv and repeat the public API import.

Query the GitHub Release with:

```bash
gh release view "$TAG" \
  --json assets,isDraft,isImmutable,isPrerelease,tagName > release.json
```

Assert it is not a draft, is immutable, has the expected prerelease flag, and
contains exactly the wheel, sdist, and `SHA256SUMS` assets.

- [ ] **Step 7: Run the focused workflow contract**

Run:

```bash
uv run pytest -q tests/package/test_release_workflow.py
git diff --check
```

Expected: all workflow contract tests PASS and no whitespace errors.

- [ ] **Step 8: Commit the workflow and contract**

```bash
git add .github/workflows/release.yml tests/package/test_release_workflow.py
git commit -m "ci: publish tagged releases with PyPI OIDC"
```

### Task 2: Exclude tags from ordinary CI and correct package URLs

**Files:**
- Modify: `.github/workflows/ci.yml`
- Modify: `pyproject.toml`
- Modify: `tests/package/test_release_workflow.py`

**Interfaces:**
- Consumes: existing PR and branch-push CI behavior.
- Produces: ordinary CI never races release CI; published project links resolve to the current GitHub repository.

- [ ] **Step 1: Add failing CI and metadata contract tests**

Append:

```python
import tomllib


def test_ci_runs_for_pull_requests_and_branch_pushes_only() -> None:
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text()
    assert "pull_request:" in workflow
    assert 'branches: ["**"]' in workflow
    assert "tags:" not in workflow


def test_published_project_urls_use_current_repository() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    urls = project["urls"]
    assert all("github.com/owlyfi/async-hyperliquid" in url for url in urls.values())
```

- [ ] **Step 2: Run the two tests and confirm failures**

Run:

```bash
uv run pytest -q \
  tests/package/test_release_workflow.py::test_ci_runs_for_pull_requests_and_branch_pushes_only \
  tests/package/test_release_workflow.py::test_published_project_urls_use_current_repository
```

Expected: FAIL because CI has an unfiltered `push` event and project URLs use
`traderfiapp`.

- [ ] **Step 3: Restrict CI to branch pushes**

Change the event block to:

```yaml
on:
  pull_request:
  push:
    branches: ["**"]
```

- [ ] **Step 4: Correct every published project URL**

Replace the five `traderfiapp/async-hyperliquid` URLs under `[project.urls]`
with `owlyfi/async-hyperliquid`, retaining the existing path suffixes and
`CHANGELOG.md` link.

- [ ] **Step 5: Run focused and package tests**

```bash
uv run pytest -q tests/package/test_release_workflow.py tests/package
```

Expected: PASS.

- [ ] **Step 6: Commit CI scope and metadata**

```bash
git add .github/workflows/ci.yml pyproject.toml tests/package/test_release_workflow.py
git commit -m "ci: separate branch and release validation"
```

### Task 3: Add the release operator runbook

**Files:**
- Create: `docs/releasing.md`
- Modify: `tests/package/test_release_workflow.py`

**Interfaces:**
- Consumes: implemented tag workflow and configured PyPI/GitHub settings.
- Produces: one operator-facing procedure for setup, publication, verification, and recovery.

- [ ] **Step 1: Add a failing runbook coverage test**

Append:

```python
def test_release_runbook_covers_setup_and_recovery() -> None:
    runbook = (ROOT / "docs" / "releasing.md").read_text()
    required = {
        "Trusted Publishing",
        "owlyfi",
        "release.yml",
        "Environment `pypi`",
        "Enable release immutability",
        "git tag -a",
        "git push origin",
        "Re-run failed jobs",
        "SHA256SUMS",
        "yank",
    }
    for phrase in required:
        assert phrase in runbook
```

- [ ] **Step 2: Run the test and confirm the missing-file failure**

```bash
uv run pytest -q tests/package/test_release_workflow.py::test_release_runbook_covers_setup_and_recovery
```

Expected: FAIL because `docs/releasing.md` does not exist.

- [ ] **Step 3: Write one-time setup instructions**

Document exact PyPI publisher values (`owlyfi`, `async-hyperliquid`,
`release.yml`, `pypi`), GitHub Environment tag pattern `v*`, empty Environment
secrets, tag ruleset protections, immutable release setting, and removal of
repository/Environment token access. State that required reviewers remain off
to preserve automatic tag publication.

- [ ] **Step 4: Write the repeatable release procedure**

Include concrete commands using an example variable that is not a system
variable:

```bash
release_version="1.0.0rc1"
uv version --short
git status --short --branch
git fetch origin main
git merge-base --is-ancestor HEAD origin/main
git tag -a "v${release_version}" -m "Release ${release_version}"
git push origin "v${release_version}"
```

Explain that `uv version --short` must equal `release_version`, the working
tree must be clean, and the release commit must already be on `main`.

- [ ] **Step 5: Write verification and recovery procedures**

Link the Actions run, PyPI version and attestations, and GitHub Release assets.
Show `sha256sum -c SHA256SUMS`. Document stage-specific recovery, using
**Re-run failed jobs** after partial progress, never moving/reusing a tag or
PyPI version, finalizing the draft after successful PyPI publication, and
publishing a new corrective version (optionally yanking the bad PyPI release)
after immutable publication.

- [ ] **Step 6: Run the runbook contract and formatting checks**

```bash
uv run pytest -q tests/package/test_release_workflow.py
uv run ruff format --check tests/package/test_release_workflow.py
uv run ruff check tests/package/test_release_workflow.py
git diff --check
```

Expected: PASS.

- [ ] **Step 7: Commit the runbook**

```bash
git add docs/releasing.md tests/package/test_release_workflow.py
git commit -m "docs: add trusted release runbook"
```

### Task 4: Validate and review the complete release change

**Files:**
- Verify: `.github/workflows/release.yml`
- Verify: `.github/workflows/ci.yml`
- Verify: `tests/package/test_release_workflow.py`
- Verify: `docs/releasing.md`
- Verify: `pyproject.toml`

**Interfaces:**
- Consumes: Tasks 1–3.
- Produces: CI-equivalent local evidence and a security-reviewed handoff without publishing a release.

- [ ] **Step 1: Parse both workflow files as YAML**

Use Ruby's standard YAML parser with aliases disabled and confirm both files
load without syntax errors:

```bash
ruby -e 'require "yaml"; ARGV.each { |path| YAML.safe_load_file(path, aliases: false); puts path }' \
  .github/workflows/ci.yml .github/workflows/release.yml
```

- [ ] **Step 2: Run CI-equivalent static checks**

```bash
uv sync --locked --dev
uv run ruff format --check
uv run ruff check src tests benchmarks
uv run ty check src/async_hyperliquid
uv run ty check tests/contracts
uv run ty check tests/integration
uv run ty check tests/oracle
uv run ty check tests/package
uv run ty check tests/public_api
uv run ty check tests/typing
uv run ty check tests/unit
uv run ty check benchmarks
```

- [ ] **Step 3: Run deterministic tests and build verification**

```bash
uv run pytest -q tests/unit tests/public_api tests/contracts tests/package
uv build --no-sources --clear
ASYNC_HYPERLIQUID_WHEEL_DIR=dist uv run pytest -q tests/package
```

Install the resulting wheel and sdist in separate temporary venvs and execute
the same public API import used by the workflow. Do not publish or push a tag.

- [ ] **Step 4: Audit release-specific security properties**

```bash
rg -n "PYPI_API_TOKEN|password:|skip-existing|workflow_dispatch|pull_request_target" \
  .github/workflows docs/releasing.md
rg -n "id-token: write|contents: write|environment:|uses:" \
  .github/workflows/release.yml
git diff --check
git status --short
```

Expected: no credential inputs or broadened release trigger; exactly one OIDC
grant, two contents-write grants, and only pinned external action references.

- [ ] **Step 5: Perform routed review and resolve findings**

Run the repository-mandated semantic analysis and risk routing, then the
required `linus-review`, `red-team-review`, and `rollback-safety` reviews.
Because this workflow changes release credentials, immutable state, external
publication, and recovery, also run `operational-risk`,
`debug-observability-review`, `blast-radius-analysis`, and any additional
skills selected by the router. Merge findings, resolve all correctness or
security issues, and rerun the affected validation.

- [ ] **Step 6: Record final evidence and commit review fixes if needed**

If review changes files, commit only the reviewed fixes:

```bash
git add .github/workflows/release.yml .github/workflows/ci.yml \
  tests/package/test_release_workflow.py docs/releasing.md pyproject.toml
git commit -m "fix: harden tagged release workflow"
```

The terminal handoff lists commits, exact validation commands and results,
remaining external prerequisite risks, and the first real tag command. It does
not claim the OIDC exchange was tested locally.
