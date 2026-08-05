# Release Runbook

This project publishes tagged releases through GitHub Actions. The workflow
builds one wheel and one source distribution, publishes those files to PyPI
with Trusted Publishing, and attaches the same files and `SHA256SUMS` to an
immutable GitHub Release.

The workflow never uses a PyPI API token. A pushed release tag is the
publication command, so check every prerequisite before pushing it.

## One-time setup

### GitHub Environment

In `owlyfi/async-hyperliquid`, open **Settings → Environments** and create
Environment `pypi` with these settings:

- Deployment branches and tags: **Selected branches and tags**.
- Add a **Tag** rule with pattern `v*`.
- Required reviewers: disabled, so publication remains automatic after a tag
  push.
- Wait timer: disabled.
- Environment secrets and variables: empty.

The workflow filename, Environment name, and PyPI publisher identity are a
single security boundary. Do not rename `release.yml` or the Environment
without updating the PyPI publisher first.

### PyPI Trusted Publisher

Sign in to PyPI with an Owner account for `async-hyperliquid`, then open
**Manage → Publishing → Add a new publisher → GitHub**. Enter these exact
values:

| Field | Value |
| --- | --- |
| PyPI project | `async-hyperliquid` |
| GitHub owner | `owlyfi` |
| Repository | `async-hyperliquid` |
| Workflow name | `release.yml` |
| Environment name | `pypi` |

`Workflow name` is the filename, not `.github/workflows/release.yml`.

Check repository, Environment, and organization Actions secrets. Remove any
repository or Environment `PYPI_API_TOKEN`; for an organization secret, remove
this repository from its access list rather than disrupting other projects.
After the first OIDC release succeeds, revoke any old PyPI token that existed
only for this project. Do not add a token fallback to the workflow.

### Protect release tags

Open **Settings → Rules → Rulesets → New tag ruleset** and configure:

```text
Name: protect-release-tags
Enforcement: Active
Target tags: v*
```

Enable **Restrict creations**, **Restrict updates**, and **Restrict
deletions**. Give bypass access only to the release maintainers who are
allowed to create version tags. The workflow separately proves that the tag
commit is already in `main` history.

### Enable immutable releases

Open the repository's **Settings**, scroll to **Releases**, and select
**Enable release immutability**. This setting affects future releases only.
The workflow creates a draft, uploads all assets, publishes PyPI, and only
then publishes the draft. Once published, GitHub locks the tag and assets and
generates a release attestation.

### GitHub Actions defaults

Under **Settings → Actions → General → Workflow permissions**, retain the
read-only default. `release.yml` grants `contents: write` only to the two
GitHub Release jobs and `id-token: write` only to the PyPI job.

## Prepare a release

1. Update `project.version` in `pyproject.toml` to the intended PEP 440
   version and update `CHANGELOG.md` in a pull request.
2. Merge the pull request into `main` and wait for the `CI` workflow to pass.
3. Work from a clean, current `main`. Do not tag an unmerged branch.
4. Use an annotated tag named `v<project version>`.

For example, to release `1.0.0rc1`:

```bash
git switch main
git pull --ff-only origin main

release_version="1.0.0rc1"
project_version="$(uv version --short)"
test "$project_version" = "$release_version"
test -z "$(git status --porcelain)"

git fetch origin main
git merge-base --is-ancestor HEAD origin/main

git tag -a "v${release_version}" -m "Release ${release_version}"
git push origin "v${release_version}"
```

If either `test` or `git merge-base` fails, stop. Do not create or push the
tag. The workflow repeats the version and ancestry checks on GitHub before
building anything.

Do not push multiple release tags together. A tag push matching `v*` starts
`.github/workflows/release.yml` automatically; there is no manual-dispatch or
token-based path.

## Follow the workflow

Open **Actions → Release** and follow these jobs in order:

1. **Validate release identity**
2. **Test and build distributions**
3. **Stage GitHub Release**
4. **Publish distributions to PyPI**
5. **Publish immutable GitHub Release**
6. **Verify public release channels**

The PyPI job is the only point at which GitHub requests a short-lived OIDC
token. PyPI also receives attestations for the wheel and sdist. The build job
cannot request an OIDC token, and the publish job does not check out or execute
repository code.

## Verify the result

Check all of the following:

- PyPI lists the exact version at
  `https://pypi.org/project/async-hyperliquid/<version>/`.
- The PyPI files page contains one wheel, one sdist, and their attestations.
- GitHub has a published Release for `v<version>`, marked **Immutable**.
- Prerelease versions such as `rc`, `a`, `b`, and `dev` are marked as
  prereleases, not latest stable releases.
- The GitHub Release contains the wheel, sdist, and `SHA256SUMS`.

To download and verify the GitHub assets on Linux:

```bash
release_tag="v1.0.0rc1"
release_verify_dir="$(mktemp -d)"
gh release download "$release_tag" \
  --repo owlyfi/async-hyperliquid \
  --dir "$release_verify_dir"
(cd "$release_verify_dir" && sha256sum -c SHA256SUMS)
```

On macOS, use `shasum -a 256 -c SHA256SUMS` for the last command. The workflow
also compares the PyPI filenames and SHA-256 digests with this same build
bundle, installs the exact version from PyPI in a clean environment, and
checks the public imports.

## Failure recovery

Never use **Re-run all jobs** after a draft or PyPI publication has occurred.
Use **Re-run failed jobs** so successful external side effects are not
repeated.

### Validation or test/build failed

No package or Release was published. Fix the problem on `main` and publish a
new version/tag. Do not move or reuse a release tag that has already been
pushed. A plainly mistyped, unpublished tag may be deleted by a release
maintainer, but its name should not be reused.

### Draft creation or asset upload failed

PyPI has not been touched. For a transient GitHub failure, choose **Re-run
failed jobs**. Before retrying, inspect the Releases page for a partial draft.
The workflow refuses to replace an existing Release or silently clobber an
asset.

If a partial draft prevents retry and PyPI does not contain the version,
inspect it and remove only that unpublished draft through the GitHub UI. Keep
the original tag for audit and prepare a new version instead of moving it.

### PyPI publication failed

The GitHub Release remains a private, populated draft.

- For a transient PyPI/OIDC error, use **Re-run failed jobs**.
- For an OIDC identity error, compare owner `owlyfi`, repository
  `async-hyperliquid`, workflow `release.yml`, and Environment `pypi` on both
  GitHub and PyPI. Confirm the Environment permits the current `v*` tag and
  the job has `id-token: write`.
- Do not add `PYPI_API_TOKEN` as a workaround.
- If PyPI reports that the version or filename already exists, inspect the
  public project before doing anything else. PyPI files cannot be replaced.

### PyPI succeeded but GitHub publication failed

This is the most important partial-success state. Do not delete the draft,
delete or move the tag, rerun PyPI, or create another Release. Use **Re-run
failed jobs**; GitHub will skip the successful PyPI job and retry draft
finalization and verification.

If an operator must finalize it after diagnosing GitHub Actions, verify that
the draft assets match `SHA256SUMS`, then run:

```bash
release_tag="v1.0.0rc1"
gh release edit "$release_tag" \
  --repo owlyfi/async-hyperliquid \
  --draft=false
```

### Final verification failed

Both publication channels may already be public and immutable. First identify
whether the failure is temporary PyPI propagation; if so, use **Re-run failed
jobs**. If the published package is genuinely bad, publish a new corrective
version. Never overwrite or reuse the old version.

When necessary, an Owner can **yank** the affected version from the PyPI
project's release management page. Yanking discourages new resolver choices
but preserves files and audit history. Keep the immutable GitHub Release and
explain the superseding version in its release notes and changelog.

## References

- [PyPI Trusted Publishers](https://docs.pypi.org/trusted-publishers/)
- [PyPA GitHub Actions publishing guide](https://packaging.python.org/en/latest/guides/publishing-package-distribution-releases-using-github-actions-ci-cd-workflows/)
- [GitHub Environments](https://docs.github.com/en/actions/how-tos/deploy/configure-and-manage-deployments/manage-environments)
- [GitHub immutable releases](https://docs.github.com/en/code-security/concepts/supply-chain-security/immutable-releases)
