# Repository Agent Instructions

Before doing work, read:
- `.agent/task.md`
- `.agent/state.md`
- `.agent/debug_plan.md`
- `.agent/incident-lessons.md`

This repository is optimized for Builder/Reviewer handoff.

## Builder Workflow
1. Understand the current task and risk constraints.
2. Implement the smallest safe change.
3. Improve observability where needed.
4. Update `CHANGELOG.md` for every Builder-authored commit-worthy change in this repository. Do this in the same change set; do not leave changelog updates for later.
5. For versioned releases, create an explicit git tag in the `vX.Y.Z` format after the release commit is created. Do not rely on commit messages as a substitute for tags.
6. Update `.agent/state.md`.
7. Request review.

## Builder Rules
- Every Builder change that would be included in a commit must add a matching entry to `CHANGELOG.md`.
- Keep changelog entries concise and user-visible; group them under the appropriate unreleased version section.
- If a change is intentionally excluded from `CHANGELOG.md`, state the reason explicitly in the handoff.
- Every release workflow must produce an explicit git tag matching the released version, for example `v0.4.2`.
- Create the release tag only after the release commit has been verified and committed, so the tag points at the exact released tree.

## Reviewer Workflow
1. Review the latest diff and `.agent/state.md`.
2. Run `$review-pipeline`.
3. Write findings into `.agent/review_notes.md`.
4. Request a minimal fix set from Builder if needed.
