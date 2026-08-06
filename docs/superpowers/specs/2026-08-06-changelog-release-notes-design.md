# Changelog-Backed GitHub Release Notes Design

**Date:** 2026-08-06

**Status:** Ready for review

**Repository:** `owlyfi/async-hyperliquid`

## Goal

Every future GitHub Release must use the matching version section from
`CHANGELOG.md` as its complete description. GitHub-generated commit and pull
request notes must not be appended. The existing mutable `v1.0.0rc1` Release
must also be updated once from the same source.

## Scope

The implementation changes:

- `scripts/extract_release_notes.py`: deterministic changelog section
  extraction;
- `.github/workflows/release.yml`: generate and consume release notes from the
  tagged changelog;
- `tests/`: parser behavior and workflow wiring coverage;
- `docs/releasing.md`: document the changelog requirement and recovery rules;
- the public `v1.0.0rc1` GitHub Release body: one controlled update after the
  local implementation is validated.

The implementation does not generate or rewrite `CHANGELOG.md`, include GitHub
auto-generated notes, change PyPI artifacts, move a tag, republish a PyPI
version, or expose `RELEASE_NOTES.md` as a downloadable Release asset.

## Selected Approach

A repository-owned Python script extracts release notes before publication.
This is preferred over inline workflow Python because the parser can be tested
directly with controlled changelog inputs. It is preferred over a third-party
changelog action because it adds no release-time supply-chain dependency.

The script uses only the Python standard library and has this interface:

```text
python scripts/extract_release_notes.py \
  --changelog CHANGELOG.md \
  --version 1.0.0rc1 \
  --output RELEASE_NOTES.md
```

## Extraction Contract

The selected section begins at an exact level-two version heading:

```markdown
## [1.0.0rc1] - 2026-08-04
```

The date suffix is optional, but the bracketed version must exactly equal the
validated package version. The section ends immediately before the next
level-two Markdown heading or at end of file.

The generated body excludes the version heading because the GitHub Release
already has `v<version>` as its title. It preserves the section's Markdown
content and internal spacing, while removing only leading and trailing blank
lines and ensuring one final newline.

Extraction fails closed when:

- no matching version heading exists;
- more than one matching version heading exists;
- the matching section is empty after trimming;
- the output path cannot be written.

Version text is compared literally rather than interpolated into an unescaped
regular expression, so dots and prerelease spellings cannot broaden the
match.

## Workflow Data Flow

`test_and_build` already receives the validated version and checks out the
tagged revision. Before uploading the internal release bundle, it runs the
extractor against that revision's `CHANGELOG.md` and creates
`RELEASE_NOTES.md`.

The internal Actions artifact becomes:

```text
release-bundle/
├── dist/
│   ├── async_hyperliquid-<version>-py3-none-any.whl
│   └── async_hyperliquid-<version>.tar.gz
├── RELEASE_NOTES.md
└── SHA256SUMS
```

`RELEASE_NOTES.md` travels through the same immutable Actions artifact as the
distributions. It is not added to `SHA256SUMS`, because the checksum file is a
public asset intended to verify only the wheel and sdist downloaded from the
GitHub Release.

`create_draft_release` removes `--generate-notes` and passes:

```text
--notes-file release-bundle/RELEASE_NOTES.md
```

Only `dist/*` and `SHA256SUMS` remain public Release assets. The existing
prerelease flag, title, tag verification, draft staging, PyPI publication, and
immutable publication ordering are unchanged.

## Existing `v1.0.0rc1` Update

The repository immutability setting is enabled now, but `v1.0.0rc1` was
published before enablement and remains mutable. After validating the parser
and workflow changes locally:

1. verify that the remote tag still peels to the expected release commit;
2. extract version `1.0.0rc1` from that commit's `CHANGELOG.md`;
3. save the current public Release body to a temporary rollback file;
4. run `gh release edit v1.0.0rc1 --notes-file <generated-file>`;
5. fetch the public Release body and compare it byte-for-byte with the
   generated notes.

This operation changes only GitHub Release metadata. It must not delete or
replace the tag, assets, checksums, attestations, or PyPI files.

## Error Handling and Recovery

Missing or malformed changelog content fails during `test_and_build`, before
the draft Release and before PyPI Trusted Publishing. The maintainer corrects
`CHANGELOG.md`, increments the package version as appropriate, and creates a
new tag after CI passes.

Once a future immutable Release is published, its notes cannot be edited. The
workflow therefore treats changelog extraction as a release gate rather than
falling back to generated or empty notes.

The workflow code can be rolled back normally before the next tag. For the
existing mutable `v1.0.0rc1`, the captured old body is the rollback source if
the metadata edit or verification exposes an unexpected formatting problem.

## Testing and Validation

Parser tests use temporary changelog files and execute the real extraction
logic. They cover:

- a successful prerelease section with `Added`, `Changed`, and `Fixed`
  subsections;
- stopping before the next version heading;
- exact matching of dotted and prerelease version strings;
- missing, duplicate, and empty sections;
- normalized outer blank lines and final newline.

Workflow tests verify that:

- `--generate-notes` is absent;
- `--notes-file release-bundle/RELEASE_NOTES.md` is present;
- the extractor receives the validated package version;
- `RELEASE_NOTES.md` is included in the internal artifact but not uploaded as
  a public asset;
- all external actions remain pinned to reviewed full commit SHAs.

Before handoff, run the repository's Ruff checks, all configured sequential
`ty` shards, deterministic tests, workflow security lint, and a local
extraction of `1.0.0rc1`. The real Release edit occurs only after those checks
pass and is then verified through GitHub.

## Success Criteria

- A future tag cannot publish when its version section is absent, duplicated,
  or empty.
- A future GitHub Release body equals the corresponding changelog section and
  contains no GitHub-generated notes.
- Public downloadable assets and PyPI distributions are unchanged.
- The existing `v1.0.0rc1` Release body equals its changelog section after the
  one-time metadata edit.
