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
4. Update `.agent/state.md`.
5. Request review.

## Reviewer Workflow
1. Review the latest diff and `.agent/state.md`.
2. Run `$review-pipeline`.
3. Write findings into `.agent/review_notes.md`.
4. Request a minimal fix set from Builder if needed.
