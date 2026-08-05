# PyPI Trusted Publishing and GitHub Release Design

**Date:** 2026-08-05  
**Status:** Ready for final review  
**Repository:** `owlyfi/async-hyperliquid`

## Goal

Publishing a Git tag named `v<PEP 440 version>` automatically validates,
tests, and builds the package once, publishes those exact distributions to
PyPI through Trusted Publishing/OIDC, and attaches the same distributions to
an immutable GitHub Release.

For example, `v1.0.0rc1` is valid only when `pyproject.toml` declares
`version = "1.0.0rc1"`. A release tag must resolve to a commit in the history
of `origin/main`.

## Scope

The implementation changes:

- `.github/workflows/release.yml`: new tag-triggered release workflow;
- `.github/workflows/ci.yml`: stop ordinary CI from also running on tags;
- `docs/releasing.md`: operator setup, release, verification, and recovery
  instructions;
- `pyproject.toml`: replace stale `traderfiapp` project URLs with the actual
  `owlyfi` repository URLs before publishing the next version.

The implementation does not add TestPyPI, automatic version bumping,
changelog generation, an API token fallback, or a manual release trigger.

## Release State Machine

The top-level workflow is deliberately non-reusable because PyPI Trusted
Publishing must bind to the exact workflow filename. It runs these jobs in
order:

1. `validate-release`
2. `test-and-build`
3. `create-draft-release`
4. `publish-pypi`
5. `publish-github-release`
6. `verify-release`

Workflow-level concurrency is keyed by the tag and does not cancel an active
release. All jobs use GitHub-hosted Ubuntu runners and explicit timeouts.

### Validate the release identity

`validate-release` checks out full history with persisted checkout credentials
disabled and confirms all of the following before a privileged job can run:

- the repository identity is exactly `owlyfi/async-hyperliquid`;
- the event is a tag push selected by `v*`;
- `uv version --short` equals the tag after removing its leading `v`;
- the peeled tag commit is an ancestor of `origin/main`;
- the version is classified as a prerelease when its canonical spelling
  contains an alpha, beta, release-candidate, or development segment.

The job exposes the validated tag, package version, and prerelease flag as
outputs. A mismatch fails closed.

### Test and build once

`test-and-build` repeats the repository's deterministic release gates at the
tag commit instead of trusting a separate workflow run:

- `uv sync --locked --dev`;
- Ruff formatting and lint checks;
- package, test, and benchmark type checks currently enforced by CI;
- deterministic unit, public API, contract, and package tests;
- `uv build --no-sources --clear`;
- wheel typing-marker inspection;
- clean-environment installation and public API import smoke tests for both
  the wheel and sdist;
- distribution metadata/version and expected-file-count validation.

The job produces exactly one wheel and one sdist. It writes `SHA256SUMS`
outside `dist/` so the checksum file cannot be uploaded to PyPI as a Python
distribution. The Actions artifact preserves this layout:

```text
release-bundle/
├── dist/
│   ├── async_hyperliquid-<version>-py3-none-any.whl
│   └── async_hyperliquid-<version>.tar.gz
└── SHA256SUMS
```

The artifact name includes the immutable commit SHA. The upload uses a pinned
`actions/upload-artifact` commit and a bounded retention period; GitHub Release
is the durable secondary distribution channel.

### Stage the GitHub Release

`create-draft-release` downloads the build artifact, verifies
`SHA256SUMS`, and creates a draft GitHub Release with generated notes. It
uploads the wheel, sdist, and checksum file before anything is published to
PyPI. Prerelease versions are marked as prereleases.

This job has `contents: write` but no `id-token` permission. It fails if a
release already exists instead of silently replacing assets. Operators recover
with **Re-run failed jobs**, not by rerunning the entire workflow.

### Publish to PyPI with OIDC

`publish-pypi` depends on the completed draft. It is the only job associated
with the `pypi` GitHub Environment and the only job granted
`id-token: write`. It has no checkout or build step. It downloads the same
artifact, verifies checksums, and passes only `release-bundle/dist/` to
`pypa/gh-action-pypi-publish` pinned to the commit behind version `v1.13.0`.

The action uses Trusted Publishing with attestations enabled. The workflow
does not pass a username or password and does not enable `skip-existing`.
Duplicate or partial-release attempts fail loudly.

### Publish the immutable GitHub Release

Only after PyPI accepts the distributions does `publish-github-release`
convert the fully populated draft into a public release. Repository release
immutability then locks the assets and tag and causes GitHub to produce a
release attestation.

This ordering gives bounded partial-failure behavior:

- an asset-upload failure publishes nowhere;
- a PyPI failure leaves only a private draft;
- a GitHub finalization failure after successful PyPI publication is recovered
  by rerunning failed jobs, which skips the already successful PyPI job.

### Verify public distribution

`verify-release` polls the version-specific PyPI API for bounded eventual
consistency, compares the public filenames and SHA-256 digests with the
release bundle, installs the exact version from PyPI in a clean environment,
and repeats the public API import smoke test. It also verifies that the GitHub
Release is public and contains the wheel, sdist, and `SHA256SUMS`.

Verification failure marks the run failed and gives operators evidence; it
never attempts to overwrite immutable files.

## Permissions

The workflow default is:

```yaml
permissions:
  contents: read
```

Only these jobs elevate permissions:

| Job | Additional permission | Purpose |
| --- | --- | --- |
| `create-draft-release` | `contents: write` | Create draft and upload assets |
| `publish-pypi` | `id-token: write` | Exchange GitHub OIDC identity for a short-lived PyPI token |
| `publish-github-release` | `contents: write` | Publish the completed draft |

No repository, organization, or Environment secret named `PYPI_API_TOKEN` is
used. The `pypi` Environment permits only `v*` tags and has no required
reviewer because the accepted requirement is automatic publication after a
tag push.

The PyPI Trusted Publisher identity is:

| Field | Value |
| --- | --- |
| Owner | `owlyfi` |
| Repository | `async-hyperliquid` |
| Workflow | `release.yml` |
| Environment | `pypi` |

## Supply-Chain Controls

- Third-party actions are pinned to full commit SHAs with version comments.
- Build/test jobs cannot mint OIDC tokens.
- Publish jobs execute no repository code.
- A protected `v*` tag must point into `main` history.
- A draft is populated before immutable publication.
- PyPI receives its PEP 740 attestations from the trusted-publishing action.
- GitHub generates a release attestation when the immutable release is
  published.
- `SHA256SUMS` enables verification outside both hosting services.

The initial implementation pins these reviewed action versions:

| Action | Version comment | Commit SHA |
| --- | --- | --- |
| `actions/checkout` | `v6.0.2` | `de0fac2e4500dabe0009e67214ff5f5447ce83dd` |
| `astral-sh/setup-uv` | `v8.1.0` | `08807647e7069bb48b6ef5acd8ec9567f424441b` |
| `actions/upload-artifact` | `v4.6.2` | `ea165f8d65b6e75b540449e92b4886f43607fa02` |
| `actions/download-artifact` | `v4.3.0` | `d3f86a106a0bac45b974a628896c90dbdf5c8093` |
| `pypa/gh-action-pypi-publish` | `v1.13.0` | `ed0c53931b1dc9bd32cbe73a98c7f6766f8a527e` |

Repository administrators configure an active `v*` tag ruleset that restricts
creation, update, and deletion to the release-maintainer bypass list. They also
enable release immutability before the first automated release.

## CI Trigger Adjustment

The existing CI workflow continues to run on pull requests and branch pushes,
but no longer runs on tag pushes. The release workflow contains the complete
release gate, so this avoids duplicate tag CI without reducing release
validation.

## Operator Documentation

`docs/releasing.md` will document:

1. one-time GitHub Environment, Trusted Publisher, tag ruleset, immutable
   release, and secret-removal setup;
2. the exact version-update and pull-request prerequisites;
3. commands to confirm a clean, synchronized `main`, create an annotated
   `v<version>` tag, and push only that tag;
4. links and checks for the workflow, PyPI version, attestations, release
   assets, and checksums;
5. failure recovery for validation failure, draft creation failure, PyPI
   rejection, GitHub finalization failure, and post-publication verification;
6. the rule to use **Re-run failed jobs** after any partial publication and
   never move or reuse a release tag/version.

## Rollback and Recovery

PyPI files and immutable GitHub Release assets cannot be replaced. A bad
release is therefore corrected by publishing a new version. If appropriate,
the bad PyPI version may be yanked and the GitHub release notes may explain
the superseding release, but the original artifacts remain available for
audit.

Before GitHub Release publication, an abandoned draft can be inspected and
removed manually only after confirming that PyPI did not accept the version.
Once PyPI succeeds, operators must preserve the tag and finalize the matching
GitHub draft.

## Validation of the Workflow Change

Before merging the implementation:

- parse every changed workflow as YAML;
- run the repository's existing CI-equivalent checks locally;
- build and inspect a local release bundle;
- assert that workflow permissions are job-scoped as designed;
- scan the changed files for token/password inputs and unpinned actions;
- inspect the diff for any trigger that could publish from a branch, pull
  request, fork, or manual dispatch;
- do not create or push a real release tag as part of implementation testing.

## References

- [PyPI: Adding a trusted publisher](https://docs.pypi.org/trusted-publishers/adding-a-publisher/)
- [PyPA: Publishing package distribution releases using GitHub Actions](https://packaging.python.org/en/latest/guides/publishing-package-distribution-releases-using-github-actions-ci-cd-workflows/)
- [PyPA: `gh-action-pypi-publish`](https://github.com/pypa/gh-action-pypi-publish)
- [GitHub: Managing environments](https://docs.github.com/en/actions/how-tos/deploy/configure-and-manage-deployments/manage-environments)
- [GitHub: Immutable releases](https://docs.github.com/en/code-security/concepts/supply-chain-security/immutable-releases)
- [GitHub: Creating rulesets](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/creating-rulesets-for-a-repository)
