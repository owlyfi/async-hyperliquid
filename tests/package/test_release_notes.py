import os
from pathlib import Path
import subprocess
import sys

import pytest

from scripts.extract_release_notes import ReleaseNotesError, extract_release_notes


ROOT = Path(__file__).parents[2]
SCRIPT = ROOT / "scripts" / "extract_release_notes.py"


def _synthetic_git_environment(tmp_path: Path) -> dict[str, str]:
    environment = {
        name: value for name, value in os.environ.items() if not name.startswith("GIT_")
    }

    empty_template = tmp_path / "empty-git-template"
    empty_template.mkdir()
    environment.update(
        {
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_SYSTEM": os.devnull,
            "GIT_TEMPLATE_DIR": str(empty_template),
        }
    )
    return environment


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


@pytest.mark.parametrize(
    "fenced_body",
    (
        "```bash\n## shell commentary\necho exact\n```",
        "   ~~~ text\n## sample heading\nexact text\n   ~~~",
    ),
)
def test_preserves_column_zero_h2_text_inside_fenced_code(fenced_body: str) -> None:
    changelog = (
        "## [1.0.0rc1]\n\n"
        f"{fenced_body}\n\n"
        "- Still in this release.\n\n"
        "## [0.5.0]\n\n"
        "- Older.\n"
    )

    assert extract_release_notes(changelog, "1.0.0rc1") == (
        f"{fenced_body}\n\n- Still in this release.\n"
    )


def test_ignores_version_heading_inside_fence_before_real_section() -> None:
    changelog = """# Changelog

```markdown
## [1.0.0rc1]

- Example only.
```

## [1.0.0rc1] - 2026-08-04

- Real release.
"""

    assert extract_release_notes(changelog, "1.0.0rc1") == "- Real release.\n"


def test_only_long_enough_matching_fence_closes_code_block() -> None:
    changelog = """## [1.0.0rc1]

````python
```
## still fenced
`````

- Still in this release.

## Maintenance

- Not in this release.
"""

    assert extract_release_notes(changelog, "1.0.0rc1") == (
        "````python\n```\n## still fenced\n`````\n\n- Still in this release.\n"
    )


@pytest.mark.parametrize(
    "fenced_body",
    ("```text\n## still fenced\n   ````\t", "~~~~text\n## still fenced\n  ~~~~\t\t"),
)
def test_fence_closer_accepts_trailing_tabs_and_preserves_bytes(
    fenced_body: str,
) -> None:
    changelog = (
        "## [1.0.0rc1]\n\n"
        f"{fenced_body}\n\n"
        "- Still in this release.\n\n"
        "## [0.5.0]\n\n"
        "- Older.\n"
    )

    assert extract_release_notes(changelog, "1.0.0rc1") == (
        f"{fenced_body}\n\n- Still in this release.\n"
    )


@pytest.mark.parametrize(
    ("opener", "invalid_closer", "valid_closer"),
    (
        ("````text", "~~~~", "````"),
        ("````text", "```", "````"),
        ("````text", "    ````", "````"),
        ("````text", "````\tinfo", "````"),
    ),
)
def test_fence_closer_rejects_wrong_marker_length_indent_or_trailing_text(
    opener: str, invalid_closer: str, valid_closer: str
) -> None:
    changelog = (
        "## [1.0.0rc1]\n\n"
        f"{opener}\n{invalid_closer}\n## still fenced\n{valid_closer}\n\n"
        "- Still in this release.\n\n"
        "## Maintenance\n\n"
        "- Not in this release.\n"
    )

    assert extract_release_notes(changelog, "1.0.0rc1") == (
        f"{opener}\n{invalid_closer}\n## still fenced\n{valid_closer}\n\n"
        "- Still in this release.\n"
    )


def test_unclosed_fence_hides_later_version_heading() -> None:
    changelog = """# Changelog

~~~markdown
## [1.0.0rc1]

- Example only.
"""

    with pytest.raises(ReleaseNotesError, match="not found"):
        extract_release_notes(changelog, "1.0.0rc1")


def test_unclosed_fence_keeps_later_h2_text_in_release_body() -> None:
    changelog = """## [1.0.0rc1]

```text
## not a terminator
body remains fenced
"""

    assert extract_release_notes(changelog, "1.0.0rc1") == (
        "```text\n## not a terminator\nbody remains fenced\n"
    )


HTML_BLOCK_CASES = (
    pytest.param(
        "   <ScRiPt type=text/javascript>\n{candidate}\n</TEXTAREA>",
        "\n",
        id="type-1-raw-tag",
    ),
    pytest.param("<!--\n{candidate}\n-->", "\n", id="type-2-comment"),
    pytest.param(
        " <?release\n{candidate}\n?>", "\n", id="type-3-processing-instruction"
    ),
    pytest.param("  <!DOCTYPE\n{candidate}\n>", "\n", id="type-4-declaration"),
    pytest.param("   <![CDATA[\n{candidate}\n]]>", "\n", id="type-5-cdata"),
    pytest.param(
        "<DiV class=release> trailing text\n</DIV>\n{candidate}",
        "\n\n",
        id="type-6-block-tag",
    ),
    pytest.param(
        '<Widget data-x="a > b" enabled>\n</Widget>\n{candidate}',
        "\n\n",
        id="type-7-complete-tag",
    ),
)

CONTAINER_LEAF_BLOCK_CASES = (
    pytest.param("  <script>\n  unterminated", id="type-1-raw-tag"),
    pytest.param("  <!--\n  unterminated", id="type-2-comment"),
    pytest.param("  <?release\n  unterminated", id="type-3-processing-instruction"),
    pytest.param("  <!DOCTYPE release\n  unterminated", id="type-4-declaration"),
    pytest.param("  <![CDATA[\n  unterminated", id="type-5-cdata"),
    pytest.param("  <div>\n  unterminated", id="type-6-block-tag"),
    pytest.param("  <Widget>\n  unterminated", id="type-7-complete-tag"),
    pytest.param("  ```text\n  unterminated", id="fenced-code"),
)


@pytest.mark.parametrize(("block_template", "end_separator"), HTML_BLOCK_CASES)
def test_ignores_version_heading_inside_commonmark_html_block(
    block_template: str, end_separator: str
) -> None:
    block = block_template.format(candidate="## [1.0.0rc1]")
    changelog = (
        f"# Changelog\n\n{block}{end_separator}"
        "## [1.0.0rc1] - 2026-08-04\n\n"
        "- Real release.\n"
    )

    assert extract_release_notes(changelog, "1.0.0rc1") == "- Real release.\n"


@pytest.mark.parametrize(("block_template", "end_separator"), HTML_BLOCK_CASES)
def test_preserves_h2_text_inside_commonmark_html_block(
    block_template: str, end_separator: str
) -> None:
    block = block_template.format(candidate="## not a heading")
    changelog = (
        "## [1.0.0rc1]\n\n"
        f"{block}{end_separator}"
        "- Still in this release.\n\n"
        "## [0.5.0]\n\n"
        "- Older.\n"
    )

    assert extract_release_notes(changelog, "1.0.0rc1") == (
        f"{block}{end_separator}- Still in this release.\n"
    )


@pytest.mark.parametrize("leaf_block", CONTAINER_LEAF_BLOCK_CASES)
def test_container_end_closes_unterminated_leaf_block_before_top_level_h2(
    leaf_block: str,
) -> None:
    changelog = (
        "## [1.0.0rc1]\n\n"
        "- List item.\n\n"
        f"{leaf_block}\n"
        "## Maintenance\n\n"
        "- Not in this release.\n"
    )

    assert extract_release_notes(changelog, "1.0.0rc1") == (
        f"- List item.\n\n{leaf_block}\n"
    )


def test_type_seven_html_does_not_interrupt_list_item_paragraph() -> None:
    changelog = """## [1.0.0rc1]

- List item.
  <Widget>
## Maintenance

- Not in this release.
"""

    assert extract_release_notes(changelog, "1.0.0rc1") == (
        "- List item.\n  <Widget>\n"
    )


def test_nested_level_two_heading_is_not_a_release_boundary() -> None:
    changelog = """## [1.0.0rc1]

- List item.

  ## Nested heading

  Nested content.

## Maintenance

- Not in this release.
"""

    assert extract_release_notes(changelog, "1.0.0rc1") == (
        "- List item.\n\n  ## Nested heading\n\n  Nested content.\n"
    )


@pytest.mark.parametrize("indent", range(4))
def test_html_block_start_accepts_up_to_three_spaces(indent: int) -> None:
    block = f"{' ' * indent}<!--\n## not a heading\n-->"
    changelog = f"## [1.0.0rc1]\n\n{block}\n- Still in this release.\n\n## [0.5.0]\n"

    assert extract_release_notes(changelog, "1.0.0rc1") == (
        f"{block}\n- Still in this release.\n"
    )


@pytest.mark.parametrize("tag", ("pre", "SCRIPT", "Style", "TeXtArEa"))
def test_type_one_html_tag_names_and_end_tags_are_case_insensitive(tag: str) -> None:
    block = f"<{tag}>\n## not a heading\n</{tag.swapcase()}>"
    changelog = f"## [1.0.0rc1]\n\n{block}\n- Still in this release.\n\n## [0.5.0]\n"

    assert extract_release_notes(changelog, "1.0.0rc1") == (
        f"{block}\n- Still in this release.\n"
    )


def test_four_space_indented_html_does_not_hide_following_heading() -> None:
    changelog = """## [1.0.0rc1]

    <!--
## Maintenance
-->
"""

    assert extract_release_notes(changelog, "1.0.0rc1") == "    <!--\n"


@pytest.mark.parametrize(
    "ordinary_html",
    (
        "Text with <span>inline HTML</span>",
        "<custom> trailing text",
        "A paragraph\n<custom>",
    ),
)
def test_ordinary_inline_html_does_not_hide_following_heading(
    ordinary_html: str,
) -> None:
    changelog = (
        f"## [1.0.0rc1]\n\n{ordinary_html}\n## Maintenance\n\n- Not in this release.\n"
    )

    assert extract_release_notes(changelog, "1.0.0rc1") == f"{ordinary_html}\n"


@pytest.mark.parametrize("complete_tag", ("<Widget>", "</Widget >"))
def test_complete_type_seven_tag_hides_headings_until_blank_line(
    complete_tag: str,
) -> None:
    changelog = (
        f"## [1.0.0rc1]\n\n{complete_tag}\n"
        "## not a heading\n\n"
        "- After the block.\n\n"
        "## [0.5.0]\n"
    )

    assert extract_release_notes(changelog, "1.0.0rc1") == (
        f"{complete_tag}\n## not a heading\n\n- After the block.\n"
    )


def test_type_seven_block_can_follow_thematic_break_without_blank_line() -> None:
    preceding_block = "***"
    changelog = (
        f"## [1.0.0rc1]\n\n{preceding_block}\n<Widget>\n"
        "## not a heading\n\n"
        "- After the block.\n\n"
        "## [0.5.0]\n"
    )

    assert extract_release_notes(changelog, "1.0.0rc1") == (
        f"{preceding_block}\n<Widget>\n## not a heading\n\n- After the block.\n"
    )


@pytest.mark.parametrize("container_paragraph", ("> Quoted.", "- Listed."))
def test_type_seven_html_does_not_interrupt_lazy_container_paragraph(
    container_paragraph: str,
) -> None:
    changelog = (
        f"## [1.0.0rc1]\n\n{container_paragraph}\n<Widget>\n"
        "## Maintenance\n\n"
        "- Not in this release.\n"
    )

    assert extract_release_notes(changelog, "1.0.0rc1") == (
        f"{container_paragraph}\n<Widget>\n"
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
        "## [1.0.0rc1] - 2026-W32-4",
        "## [1.0.0rc1] - 20260804",
        "## [1.0.0rc1] - 2026-08-04 draft",
        "## [1.0.0rc1] - 2026-08-04T00:00:00",
        "## [1.0.0rc1] - ２０２６-０８-０４",
        "## [1.0.0rc1] - release candidate",
    ),
)
def test_rejects_invalid_version_heading_suffixes(heading: str) -> None:
    with pytest.raises(ReleaseNotesError, match="not found"):
        extract_release_notes(f"{heading}\n\n- Wrong.\n", "1.0.0rc1")


@pytest.mark.parametrize(
    "heading",
    ("## [1.0.0rc1]", "## [1.0.0rc1] - 2026-08-04", "## [1.0.0rc1] - 2024-02-29"),
)
def test_accepts_version_heading_with_optional_iso_date(heading: str) -> None:
    assert extract_release_notes(f"{heading}\n\n- Exact.\n", "1.0.0rc1") == "- Exact.\n"


@pytest.mark.parametrize(
    "heading", (" ## [1.0.0rc1]", "##\t[1.0.0rc1]", "## [1.0.0rc1]\t")
)
def test_requires_repository_exact_version_heading(heading: str) -> None:
    with pytest.raises(ReleaseNotesError, match="not found"):
        extract_release_notes(f"{heading}\n\n- Wrong.\n", "1.0.0rc1")


@pytest.mark.parametrize(
    "boundary",
    (
        "##",
        "##\tMaintenance",
        " ## Maintenance",
        "  ## Maintenance",
        "   ## Maintenance",
    ),
)
def test_stops_at_commonmark_level_two_heading(boundary: str) -> None:
    changelog = f"## [1.0.0rc1]\n\nExact.\n\n{boundary}\n\n- Not in this release.\n"

    assert extract_release_notes(changelog, "1.0.0rc1") == "Exact.\n"


@pytest.mark.parametrize(
    "non_boundary", ("### Maintenance", "##not-heading", "    ## indented code")
)
def test_does_not_stop_at_non_level_two_heading(non_boundary: str) -> None:
    changelog = (
        "## [1.0.0rc1]\n\n"
        f"{non_boundary}\n"
        "- Still in this release.\n\n"
        "## Maintenance\n\n"
        "- Not in this release.\n"
    )

    assert extract_release_notes(changelog, "1.0.0rc1") == (
        f"{non_boundary}\n- Still in this release.\n"
    )


@pytest.mark.parametrize("separator", ("\u0085", "\v", "\f", "\u2028", "\u2029"))
def test_preserves_unicode_and_non_newline_separators(separator: str) -> None:
    body = f"- Before{separator}- After \U0001f989"
    changelog = f"## [1.0.0rc1]\n\n{body}\n"

    assert extract_release_notes(changelog, "1.0.0rc1") == f"{body}\n"


@pytest.mark.parametrize("separator", ("\u0085", "\v", "\f", "\u2028", "\u2029"))
def test_preserves_separator_only_lines_at_body_boundaries(separator: str) -> None:
    changelog = f"## [1.0.0rc1]\n\n{separator}\n- Middle\n{separator}\n\n"

    assert extract_release_notes(changelog, "1.0.0rc1") == (
        f"{separator}\n- Middle\n{separator}\n"
    )


@pytest.mark.parametrize("newline", ("\r\n", "\r"))
def test_normalizes_crlf_and_bare_cr_newlines(newline: str) -> None:
    changelog = newline.join(
        (
            "## [1.0.0rc1]",
            "",
            "### Changed",
            "",
            "- Exact.",
            "## [0.5.0]",
            "",
            "- Older.",
            "",
        )
    )

    assert extract_release_notes(changelog, "1.0.0rc1") == ("### Changed\n\n- Exact.\n")


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


def test_legacy_tag_changelog_uses_the_current_extractor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The rc1 runbook path must not depend on tooling absent from that tag."""
    runbook = (ROOT / "dev-docs" / "releasing.md").read_text(encoding="utf-8")
    assert (
        'git show "${release_tag}^{commit}:scripts/extract_release_notes.py"'
        not in runbook
    )
    assert "uv run --frozen python scripts/extract_release_notes.py" in runbook
    assert 'git show "${release_tag}^{commit}:CHANGELOG.md"' in runbook

    hostile_hooks = tmp_path / "hostile-hooks"
    hostile_hooks.mkdir()
    failing_hook = hostile_hooks / "pre-commit"
    failing_hook.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    failing_hook.chmod(0o755)
    hostile_global_config = tmp_path / "hostile-global.gitconfig"
    hostile_global_config.write_text(
        "[commit]\n\tgpgsign = true\n"
        "[tag]\n\tgpgsign = true\n"
        f"[core]\n\thooksPath = {hostile_hooks}\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(hostile_global_config))
    git_environment = _synthetic_git_environment(tmp_path)
    git_command = [
        "git",
        "-c",
        "commit.gpgsign=false",
        "-c",
        "tag.gpgsign=false",
        "-c",
        f"core.hooksPath={os.devnull}",
    ]

    legacy_repository = tmp_path / "legacy-repository"
    legacy_repository.mkdir()
    legacy_changelog = legacy_repository / "CHANGELOG.md"
    legacy_changelog.write_text(
        "# Changelog\n\n## [1.0.0rc1]\n\n### Added\n\n- Legacy release.\n",
        encoding="utf-8",
    )
    for command in (
        ["git", "init"],
        ["git", "config", "user.name", "Release test"],
        ["git", "config", "user.email", "release-test@example.invalid"],
        ["git", "add", "CHANGELOG.md"],
        ["git", "commit", "-m", "legacy release"],
        ["git", "tag", "-a", "v1.0.0rc1", "-m", "legacy release"],
    ):
        subprocess.run(
            [*git_command, *command[1:]],
            cwd=legacy_repository,
            env=git_environment,
            check=True,
        )

    missing_extractor = subprocess.run(
        [*git_command, "cat-file", "-e", "v1.0.0rc1:scripts/extract_release_notes.py"],
        cwd=legacy_repository,
        env=git_environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert missing_extractor.returncode != 0

    changelog = tmp_path / "CHANGELOG.md"
    output = tmp_path / "RELEASE_NOTES.md"
    tagged_changelog = subprocess.run(
        [*git_command, "show", "v1.0.0rc1^{commit}:CHANGELOG.md"],
        cwd=legacy_repository,
        env=git_environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert tagged_changelog.returncode == 0, tagged_changelog.stderr
    changelog.write_text(tagged_changelog.stdout, encoding="utf-8")

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
    assert output.read_text(encoding="utf-8") == "### Added\n\n- Legacy release.\n"


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
