---
name: pipeline-review
description: Orchestrate routed code review: analyze diff, route skills, run mandatory and selected review skills, merge findings, and optionally run consensus. Use this as the default entry point for non-trivial code review.
---
# Review Pipeline

Workflow:
1. Run `$diff-semantic-analyzer`.
2. Run `$risk-router` on the analyzer output.
3. Run the always-on review skills:
   - `$linus-review`
   - `$red-team-review`
   - `$rollback-safety`
4. Run only the additional skills selected by `$risk-router`.
5. Run `$merge-review`.
6. If reports conflict materially, run `$consensus-review`.
7. Return the final report.

Rules:
- downstream skills should prefer analyzer output over rereading the entire diff when possible
- if a skill needs direct code context, read only the relevant file subset
- do not run every review skill by default
- keep final output concise and actionable
