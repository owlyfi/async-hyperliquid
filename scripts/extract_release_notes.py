import argparse
from collections.abc import Sequence
from datetime import date
from pathlib import Path
import re
import sys

from markdown_it import MarkdownIt


class ReleaseNotesError(ValueError):
    """Raised when a changelog cannot produce one release-note section."""


_COMMONMARK = MarkdownIt("commonmark")


def _matches_version_heading(line: str, version: str) -> bool:
    prefix = f"## [{version}]"
    if line == prefix:
        return True
    if not line.startswith(f"{prefix} - "):
        return False
    date_text = line.removeprefix(f"{prefix} - ")
    if re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", date_text) is None:
        return False
    try:
        date.fromisoformat(date_text)
    except ValueError:
        return False
    return True


def _level_two_heading_lines(markdown: str) -> list[int]:
    return [
        token.map[0]
        for token in _COMMONMARK.parse(markdown)
        if token.type == "heading_open"
        and token.tag == "h2"
        and token.level == 0
        and token.map is not None
    ]


def extract_release_notes(changelog: str, version: str) -> str:
    normalized = changelog.replace("\r\n", "\n").replace("\r", "\n")
    lines = normalized.split("\n")
    heading_lines = _level_two_heading_lines(normalized)
    matches = [
        index
        for index in heading_lines
        if _matches_version_heading(lines[index], version)
    ]
    if not matches:
        raise ReleaseNotesError(f"changelog section [{version}] was not found")
    if len(matches) > 1:
        raise ReleaseNotesError(f"changelog section [{version}] appears more than once")
    start = matches[0] + 1
    end = next((index for index in heading_lines if index >= start), len(lines))
    section = lines[start:end]
    while section and not section[0].strip(" \t"):
        section.pop(0)
    while section and not section[-1].strip(" \t"):
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
    except (OSError, UnicodeError, ReleaseNotesError) as exc:
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
