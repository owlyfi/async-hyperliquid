# Changelog-Backed GitHub Release Notes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish each GitHub Release with exactly the matching `CHANGELOG.md` section and update the existing mutable `v1.0.0rc1` Release body from that source.

**Architecture:** A standard-library Python tool extracts one bracketed version section into `RELEASE_NOTES.md`. The workflow transfers that private file in the existing Actions artifact and passes it to `gh release create --notes-file`; only wheel, sdist, and `SHA256SUMS` remain public assets. The existing Release edit uses the same tested tool and verifies that tag and assets remain unchanged.

**Tech Stack:** Python 3.12 standard library, pytest, uv, Ruff, ty, GitHub Actions YAML, GitHub CLI.

## Global Constraints

- Use only the matching changelog body; never append GitHub-generated notes.
- Match `## [<version>]` literally, with an optional ISO date suffix.
- Fail closed for missing, duplicate, or empty sections.
- Add no third-party changelog action or runtime dependency.
- Keep `RELEASE_NOTES.md` private to the Actions artifact.
- Preserve full-SHA action pins, including the pending Node 24 v8.0.1 pin.
- Do not move/delete `v1.0.0rc1`, replace assets, or touch PyPI files.
- Reconfirm mutability immediately before editing the existing Release.

## File Structure

- Create `scripts/__init__.py`: importable release-tooling package.
- Create `scripts/extract_release_notes.py`: extraction API and CLI.
- Create `tests/package/test_release_notes.py`: parser and CLI tests.
- Modify `.github/workflows/release.yml`: generation, transfer, and publication.
- Modify `.github/workflows/ci.yml`: lint/type-check release tooling.
- Modify `tests/package/test_release_workflow.py`: workflow policy tests.
- Modify `docs/releasing.md`: preparation, verification, and recovery guidance.

---

### Task 1: Checkpoint the pending Node 24 action upgrade

**Files:**
- Modify: `.github/workflows/release.yml:203,249,276,338`
- Modify: `tests/package/test_release_workflow.py:65-84`

**Interfaces:**
- Consumes: `actions/download-artifact` v8.0.1 SHA `3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c`.
- Produces: a separate baseline commit with no Node 20 artifact downloads.

- [ ] **Step 1: Confirm the pending diff**

```bash
git diff -- .github/workflows/release.yml tests/package/test_release_workflow.py
```

Expected: four action references and one expected test pin change only.

- [ ] **Step 2: Validate the checkpoint**

```bash
uv run pytest -q tests/package/test_release_workflow.py::test_release_workflow_pins_every_external_action
uvx zizmor .github/workflows/release.yml
```

Expected: PASS and no default-severity zizmor findings.

- [ ] **Step 3: Commit the checkpoint**

```bash
git add .github/workflows/release.yml tests/package/test_release_workflow.py
git commit -m "ci: run artifact downloads on Node 24"
```

### Task 2: Build the deterministic changelog extractor

**Files:**
- Create: `scripts/__init__.py`
- Create: `scripts/extract_release_notes.py`
- Create: `tests/package/test_release_notes.py`

**Interfaces:**
- Produces: `extract_release_notes(changelog: str, version: str) -> str`.
- Produces: `ReleaseNotesError(ValueError)` for invalid sections.
- Produces: CLI `--changelog PATH --version VERSION --output PATH`, returning `0` on success and `1` on extraction/I/O failure.

- [ ] **Step 1: Write failing parser tests**

Create `tests/package/test_release_notes.py`:

```python
from pathlib import Path
import subprocess
import sys

import pytest

from scripts.extract_release_notes import ReleaseNotesError, extract_release_notes


ROOT = Path(__file__).parents[2]
SCRIPT = ROOT / "scripts" / "extract_release_notes.py"


def test_extracts_body_and_stops_at_next_version() -> None:
    changelog = """# Changelog

## [1.0.0rc1] - 2026-08-04

### Added

- First release candidate.

### Fixed

- Correct aliases.

## [0.5.0] - 2026-04-20

- Older feature.
"""
    assert extract_release_notes(changelog, "1.0.0rc1") == (
        "### Added\n\n- First release candidate.\n\n"
        "### Fixed\n\n- Correct aliases.\n"
    )


def test_matches_version_literally() -> None:
    changelog = "## [1x0x0rc1] - 2026-08-04\n\n- Wrong.\n"
    with pytest.raises(ReleaseNotesError, match="not found"):
        extract_release_notes(changelog, "1.0.0rc1")


@pytest.mark.parametrize(
    ("changelog", "message"),
    (
        ("# Changelog\n", "not found"),
        (
            "## [1.0.0rc1]\n\n- First.\n\n"
            "## [1.0.0rc1] - 2026-08-04\n\n- Second.\n",
            "more than once",
        ),
        ("## [1.0.0rc1]\n\n## [0.5.0]\n\n- Older.\n", "is empty"),
    ),
)
def test_rejects_invalid_sections(changelog: str, message: str) -> None:
    with pytest.raises(ReleaseNotesError, match=message):
        extract_release_notes(changelog, "1.0.0rc1")


def test_cli_writes_notes(tmp_path: Path) -> None:
    changelog = tmp_path / "CHANGELOG.md"
    output = tmp_path / "RELEASE_NOTES.md"
    changelog.write_text("## [1.0.0rc1]\n\n### Changed\n\n- Exact.\n")
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--changelog",
            str(changelog),
            "--version",
            "1.0.0rc1",
            "--output",
            str(output),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert output.read_text() == "### Changed\n\n- Exact.\n"


def test_cli_reports_output_failure(tmp_path: Path) -> None:
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text("## [1.0.0rc1]\n\n- Exact.\n")
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--changelog",
            str(changelog),
            "--version",
            "1.0.0rc1",
            "--output",
            str(tmp_path),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    assert "could not write release notes" in result.stderr
```

- [ ] **Step 2: Verify RED**

```bash
uv run pytest -q tests/package/test_release_notes.py
```

Expected: collection error because `scripts.extract_release_notes` is absent.

- [ ] **Step 3: Implement the extractor**

Create empty `scripts/__init__.py` and `scripts/extract_release_notes.py`:

```python
import argparse
from collections.abc import Sequence
from datetime import date
from pathlib import Path
import sys


class ReleaseNotesError(ValueError):
    """Raised when a changelog cannot produce one release-note section."""


def _matches_version_heading(line: str, version: str) -> bool:
    prefix = f"## [{version}]"
    if line == prefix:
        return True
    if not line.startswith(f"{prefix} - "):
        return False
    date_text = line.removeprefix(f"{prefix} - ")
    if len(date_text) != 10:
        return False
    try:
        date.fromisoformat(date_text)
    except ValueError:
        return False
    return True


def extract_release_notes(changelog: str, version: str) -> str:
    lines = changelog.splitlines()
    matches = [
        index
        for index, line in enumerate(lines)
        if _matches_version_heading(line, version)
    ]
    if not matches:
        raise ReleaseNotesError(f"changelog section [{version}] was not found")
    if len(matches) > 1:
        raise ReleaseNotesError(f"changelog section [{version}] appears more than once")
    start = matches[0] + 1
    end = next(
        (index for index in range(start, len(lines)) if lines[index].startswith("## ")),
        len(lines),
    )
    section = lines[start:end]
    while section and not section[0].strip():
        section.pop(0)
    while section and not section[-1].strip():
        section.pop()
    if not section:
        raise ReleaseNotesError(f"changelog section [{version}] is empty")
    return "\n".join(section) + "\n"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Extract one changelog section")
    parser.add_argument("--changelog", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        notes = extract_release_notes(
            args.changelog.read_text(encoding="utf-8"), args.version
        )
    except (OSError, ReleaseNotesError) as exc:
        print(f"could not extract release notes: {exc}", file=sys.stderr)
        return 1
    try:
        args.output.write_text(notes, encoding="utf-8")
    except OSError as exc:
        print(f"could not write release notes: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Verify GREEN and the real rc1 section**

```bash
uv run pytest -q tests/package/test_release_notes.py
uv run ruff format scripts tests/package/test_release_notes.py
uv run ruff check scripts tests/package/test_release_notes.py
uv run ty check scripts
uv run ty check tests/package/test_release_notes.py
release_notes_dir="$(mktemp -d)"
uv run python scripts/extract_release_notes.py \
  --changelog CHANGELOG.md \
  --version 1.0.0rc1 \
  --output "$release_notes_dir/RELEASE_NOTES.md"
test -s "$release_notes_dir/RELEASE_NOTES.md"
rg -n '^### (Added|Changed|Removed|Fixed)$' "$release_notes_dir/RELEASE_NOTES.md"
```

Expected: all checks pass and the real output contains four subsection headings without its version heading.

- [ ] **Step 5: Commit the extractor**

```bash
git add scripts/__init__.py scripts/extract_release_notes.py tests/package/test_release_notes.py
git commit -m "feat: extract release notes from changelog"
```

### Task 3: Wire notes into CI and the release workflow

**Files:**
- Modify: `.github/workflows/release.yml:90-231`
- Modify: `.github/workflows/ci.yml:30-65`
- Modify: `tests/package/test_release_workflow.py`

**Interfaces:**
- Consumes: Task 2 CLI.
- Produces: private `RELEASE_NOTES.md` artifact file and `--notes-file` input.

- [ ] **Step 1: Add failing wiring tests**

Append to `tests/package/test_release_workflow.py`:

```python
def test_release_workflow_uses_only_changelog_release_notes() -> None:
    workflow = _release_text()
    build_job = workflow.split("  test_and_build:", 1)[1].split(
        "  create_draft_release:", 1
    )[0]
    draft_job = workflow.split("  create_draft_release:", 1)[1].split(
        "  publish_pypi:", 1
    )[0]
    assert "--generate-notes" not in workflow
    assert "scripts/extract_release_notes.py" in build_job
    assert '--version "$VERSION"' in build_job
    assert '--output RELEASE_NOTES.md' in build_job
    assert "\n            RELEASE_NOTES.md" in build_job
    assert "--notes-file release-bundle/RELEASE_NOTES.md" in draft_job
    assert "release-bundle/RELEASE_NOTES.md \\" not in draft_job


def test_ci_and_release_static_check_release_tooling() -> None:
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text()
    release = _release_text()
    for workflow in (ci, release):
        assert "uv run ruff check src tests benchmarks scripts" in workflow
        assert "uv run ty check scripts" in workflow
```

- [ ] **Step 2: Verify RED**

```bash
uv run pytest -q tests/package/test_release_workflow.py
```

Expected: failures identify generated notes, missing extraction, and missing script checks.

- [ ] **Step 3: Generate and transfer notes**

After dependency installation in `test_and_build`, add:

```yaml
      - name: Generate release notes
        env:
          VERSION: ${{ needs.validate_release.outputs.version }}
        run: |
          uv run python scripts/extract_release_notes.py \
            --changelog CHANGELOG.md \
            --version "$VERSION" \
            --output RELEASE_NOTES.md
```

Add the private file to the internal artifact:

```yaml
          path: |
            dist
            RELEASE_NOTES.md
            SHA256SUMS
```

- [ ] **Step 4: Replace generated notes**

Use these flags while leaving the positional public assets unchanged:

```bash
flags=(
  --draft
  --verify-tag
  --title "$TAG"
  --notes-file release-bundle/RELEASE_NOTES.md
)
```

```bash
gh release create "$TAG" \
  release-bundle/dist/* \
  release-bundle/SHA256SUMS \
  "${flags[@]}"
```

- [ ] **Step 5: Add release tooling to static checks**

In both CI and Release workflows use:

```yaml
      - name: Lint
        run: uv run ruff check src tests benchmarks scripts

      - name: Type-check release tooling
        run: uv run ty check scripts
```

- [ ] **Step 6: Verify and commit workflow wiring**

```bash
uv run pytest -q tests/package/test_release_workflow.py tests/package/test_release_notes.py
uv run ruff format --check scripts tests/package
uv run ruff check src tests benchmarks scripts
uv run ty check scripts
uv run ty check tests/package
uvx zizmor .github/workflows/ci.yml .github/workflows/release.yml
git add .github/workflows/ci.yml .github/workflows/release.yml tests/package/test_release_workflow.py
git commit -m "ci: publish release notes from changelog"
```

Expected: checks pass and the commit contains only workflow wiring and policy tests.

### Task 4: Document changelog-backed releases

**Files:**
- Modify: `docs/releasing.md`

**Interfaces:**
- Consumes: Tasks 2-3 behavior.
- Produces: operator preparation, verification, and recovery rules.

- [ ] **Step 1: Add the contract under `Prepare a release`**

```markdown
### Prepare release notes

`CHANGELOG.md` is the only source for the GitHub Release description. Before
tagging, add exactly one `## [<version>] - YYYY-MM-DD` section with non-empty
Markdown content. The workflow publishes the section body without its version
heading and does not append GitHub-generated notes.

The release fails before draft creation and PyPI publication when the matching
section is missing, duplicated, or empty. Because immutable Release notes
cannot be corrected after publication, verify the changelog section in the
same pull request that changes `project.version`.
```

- [ ] **Step 2: Extend verification and recovery**

Add this verification bullet and failure section:

```markdown
- The GitHub Release description matches the corresponding `CHANGELOG.md`
  section and contains no generated commit or contributor list.

### Release-note extraction failed

No draft or PyPI upload has occurred. Correct the matching changelog section on
`main`, run CI, increment the package version if the old tag has already been
pushed, and create the next release tag. Never fall back to empty or generated
notes.
```

- [ ] **Step 3: Verify and commit documentation**

```bash
uv run pytest -q tests/package/test_readme.py tests/package/test_release_workflow.py
git diff --check -- docs/releasing.md
git add docs/releasing.md
git commit -m "docs: document changelog-backed releases"
```

Expected: tests pass and the documentation has no whitespace errors.

### Task 5: Run complete release-equivalent verification

**Files:**
- Verify only.

**Interfaces:**
- Consumes: all implementation commits.
- Produces: fresh evidence for push and public metadata edit.

- [ ] **Step 1: Run Ruff and every ty shard sequentially**

```bash
uv run ruff format --check
uv run ruff check src tests benchmarks scripts
uv run ty check src/async_hyperliquid
uv run ty check scripts
uv run ty check tests/contracts
uv run ty check tests/integration
uv run ty check tests/oracle
uv run ty check tests/package
uv run ty check tests/public_api
uv run ty check tests/typing
uv run ty check tests/unit
uv run ty check benchmarks
```

Expected: every command exits zero.

- [ ] **Step 2: Run tests and inspect distributions**

```bash
uv run pytest -q tests/unit tests/public_api tests/contracts tests/package
uv build --no-sources --clear
ASYNC_HYPERLIQUID_WHEEL_DIR=dist uv run pytest -q tests/package
```

Expected: all tests pass and exactly one rc1 wheel and sdist are inspected.

- [ ] **Step 3: Audit workflows and repository state**

```bash
uvx zizmor .github/workflows/ci.yml .github/workflows/release.yml
git diff --check
git status --short --branch
git log --oneline origin/main..HEAD
```

Expected: no default-severity findings, no whitespace errors, a clean worktree, and only reviewed commits ahead of `origin/main`.

### Task 6: Push automation and verify branch CI

**Files:**
- External state: `origin/main` and branch `CI` run.

**Interfaces:**
- Consumes: clean verified `main`.
- Produces: future tags containing the changelog-backed workflow.

- [ ] **Step 1: Reconcile and push without force**

```bash
git fetch origin main
git rev-list --left-right --count origin/main...main
git push origin main
```

Expected: remote-only count is `0`; stop before pushing if it is nonzero. Push succeeds without force.

- [ ] **Step 2: Wait for the pushed HEAD's CI run**

```bash
pushed_head="$(git rev-parse HEAD)"
ci_run_id="$(gh run list --workflow CI --branch main --limit 10 \
  --json databaseId,headSha \
  --jq ".[] | select(.headSha == \"$pushed_head\") | .databaseId" | head -n 1)"
test -n "$ci_run_id"
gh run watch "$ci_run_id" --exit-status
```

Expected: CI for `pushed_head` finishes successfully.

### Task 7: Update existing `v1.0.0rc1` Release body

**Files:**
- External state: GitHub Release `v1.0.0rc1` body only.
- Temporary input and rollback files under a `mktemp -d` directory.

**Interfaces:**
- Consumes: tested extractor, authenticated `gh`, mutable Release, unchanged tag/changelog.
- Produces: body equal to the rc1 changelog section.

- [ ] **Step 1: Reconfirm identity and mutability**

```bash
git fetch origin refs/tags/v1.0.0rc1:refs/tags/v1.0.0rc1
test "$(git rev-parse 'v1.0.0rc1^{}')" = "b211276abdb2067d48871176433d6de7a729bad2"
git diff --exit-code v1.0.0rc1 -- CHANGELOG.md
gh release view v1.0.0rc1 --repo owlyfi/async-hyperliquid \
  --json tagName,isDraft,isImmutable,isPrerelease,url
```

Expected: correct tag, draft false, prerelease true, immutable false. Stop without editing on any mismatch.

- [ ] **Step 2: Generate notes and capture rollback state**

```bash
release_edit_dir="$(mktemp -d)"
uv run python scripts/extract_release_notes.py \
  --changelog CHANGELOG.md \
  --version 1.0.0rc1 \
  --output "$release_edit_dir/RELEASE_NOTES.md"
gh release view v1.0.0rc1 --repo owlyfi/async-hyperliquid \
  --json body --jq .body > "$release_edit_dir/original-body.md"
before_metadata="$(gh release view v1.0.0rc1 \
  --repo owlyfi/async-hyperliquid \
  --json assets,tagName,isDraft,isPrerelease)"
test -s "$release_edit_dir/RELEASE_NOTES.md"
test -s "$release_edit_dir/original-body.md"
```

- [ ] **Step 3: Edit only the body**

```bash
gh release edit v1.0.0rc1 \
  --repo owlyfi/async-hyperliquid \
  --notes-file "$release_edit_dir/RELEASE_NOTES.md"
```

- [ ] **Step 4: Verify exact body and unchanged metadata**

```bash
gh release view v1.0.0rc1 --repo owlyfi/async-hyperliquid \
  --json body --jq .body | diff -u "$release_edit_dir/RELEASE_NOTES.md" -
after_metadata="$(gh release view v1.0.0rc1 \
  --repo owlyfi/async-hyperliquid \
  --json assets,tagName,isDraft,isPrerelease)"
test "$before_metadata" = "$after_metadata"
git ls-remote --tags origin refs/tags/v1.0.0rc1 'refs/tags/v1.0.0rc1^{}'
```

Expected: no body diff, identical metadata, and the tag still peels to `b211276abdb2067d48871176433d6de7a729bad2`.

- [ ] **Step 5: Roll back only on verification failure**

```bash
gh release edit v1.0.0rc1 \
  --repo owlyfi/async-hyperliquid \
  --notes-file "$release_edit_dir/original-body.md"
```

Run Step 5 only if Step 4 fails, then stop and report the mismatched field. Never delete the Release, tag, or assets.
