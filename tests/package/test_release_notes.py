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
        "### Added\n\n- First release candidate.\n\n### Fixed\n\n- Correct aliases.\n"
    )


def test_matches_version_literally() -> None:
    changelog = "## [1x0x0rc1] - 2026-08-04\n\n- Wrong.\n"
    with pytest.raises(ReleaseNotesError, match="not found"):
        extract_release_notes(changelog, "1.0.0rc1")


@pytest.mark.parametrize(
    "heading",
    (
        "## [1.0.0rc1] - 2026-8-04",
        "## [1.0.0rc1] - 2026-02-30",
        "## [1.0.0rc1] - 2026-08-04 draft",
        "## [1.0.0rc1] - release candidate",
    ),
)
def test_rejects_invalid_version_heading_suffixes(heading: str) -> None:
    with pytest.raises(ReleaseNotesError, match="not found"):
        extract_release_notes(f"{heading}\n\n- Wrong.\n", "1.0.0rc1")


@pytest.mark.parametrize("heading", ("## [1.0.0rc1]", "## [1.0.0rc1] - 2026-08-04"))
def test_accepts_version_heading_with_optional_iso_date(heading: str) -> None:
    assert extract_release_notes(f"{heading}\n\n- Exact.\n", "1.0.0rc1") == "- Exact.\n"


@pytest.mark.parametrize(
    ("changelog", "message"),
    (
        ("# Changelog\n", "not found"),
        (
            "## [1.0.0rc1]\n\n- First.\n\n## [1.0.0rc1] - 2026-08-04\n\n- Second.\n",
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


def test_cli_reports_malformed_utf8_changelog(tmp_path: Path) -> None:
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_bytes(b"## [1.0.0rc1]\n\n\xff\n")
    output = tmp_path / "RELEASE_NOTES.md"
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
    assert result.returncode == 1
    assert "could not extract release notes" in result.stderr
    assert "Traceback" not in result.stderr
    assert not output.exists()
