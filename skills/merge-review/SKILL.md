---
name: merge-review
description: Merge outputs from multiple review skills into one deduplicated, severity-ranked report. Use this after selected review skills have finished.
---
# Review Merge

Input:
- reports from selected review skills
- optional analyzer and router outputs

Tasks:
1. Deduplicate overlapping issues.
2. Group findings by theme and severity.
3. Preserve attribution to the originating skill.
4. Separate:
   - block merge
   - should fix before merge
   - follow-up after merge
   - notes
5. Prefer concrete issues over stylistic noise.

Output format:
```md
# Review Report

## Block merge
- [skill] issue

## Should fix
- [skill] issue

## Follow-up
- [skill] issue

## Notes
- [skill] issue

## Suggested minimal fix set
- item
```
