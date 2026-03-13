# State

- Date: 2026-03-13
- Branch: `codex/refactor-async-hyperliquid`
- Task: Vendor the missing system-level review pipeline and routed review skills into the repository so `AGENTS.md` points to repo-local review workflow assets without diverging from the user-level skill names.
- Progress: Copied the review pipeline and routed review skills from the user-level skill store into `skills/`, aligned the repo-local pipeline name back to `$pipeline-review`, and documented the repository-local review-skill entry points in `AGENTS.md`.
- Verification: Confirmed the new repo-local review skill directories exist under `skills/` and that `skills/review-pipeline/SKILL.md` now matches the user-level `$pipeline-review` name referenced by `AGENTS.md`.
