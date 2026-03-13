---
name: diff-semantic-analyzer
description: Analyze a code diff once and convert it into a structured semantic summary with change types, risk flags, affected boundaries, and review hints. Trigger this skill before non-trivial code review to avoid repeating full-diff analysis in every review skill.
---
# Diff Semantic Analyzer

Input:
- git diff, PR diff, or change summary
- optional `.agent/state.md`

Goal:
Convert raw changes into a compact structured summary that downstream review skills can consume.

Steps:
1. Read the diff once.
2. Identify:
   - files changed
   - modules changed
   - change types: api, db, config, async, logging, auth, retry, queue, validation, migration, build, docs
   - public interface changes
   - stateful writes
   - external dependency calls
   - feature flags or debug toggles
   - rollback concerns
3. Mark risk flags such as:
   - schema_change
   - contract_change
   - shared_code_change
   - concurrency_change
   - idempotency_risk
   - new_input_surface
   - secret_logging_risk
   - hot_path_change
   - rollout_risk
4. Produce a compact analysis object.

Output format:
```json
{
  "files_changed": [],
  "modules_changed": [],
  "change_types": [],
  "risk_flags": [],
  "public_interfaces": [],
  "data_writes": [],
  "external_calls": [],
  "flags_or_toggles": [],
  "critical_paths": [],
  "review_hints": [],
  "requires_remote_debugging": false
}
```

Keep the output compact and factual. Do not perform the full review here.
