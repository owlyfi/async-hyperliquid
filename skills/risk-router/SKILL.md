---
name: risk-router
description: Route a reviewed change to the minimal set of relevant review skills based on diff-semantic-analyzer output. Use this skill after semantic diff analysis to reduce token usage and avoid unnecessary review passes.
---
# Risk Router

Input:
- output from `$diff-semantic-analyzer`
- optional `.agent/state.md`

Always include:
- `linus-review`
- `red-team-review`
- `rollback-safety`

Add conditional skills only when justified.

Routing rules:
- add `architecture-review` if new modules, ownership changes, or layering violations are likely
- add `blast-radius-analysis` if shared code, config, migrations, or multi-service impact appears
- add `debug-observability-review` if the change is hard to debug locally, adds instrumentation, or affects state tracing
- add `performance-regression` for hot paths, loops, caches, DB query paths, serialization, or memory-heavy logic
- add `concurrency-safety` for async, workers, queues, retries, locks, shared mutable state, streaming, or fan-out
- add `input-validation` for parsing, request payloads, forms, handlers, uploaders, or webhook consumers
- add `api-contract-review` for public endpoints, schemas, exported models, generated clients, or compatibility boundaries
- add `data-integrity-review` for transactions, migrations, writes, deduplication, ordering, or idempotency concerns
- add `operational-risk` for retries, queues, rate limits, timeouts, dependencies, rollout risk, or job orchestration

Output format:
```json
{
  "always_run": ["linus-review", "red-team-review", "rollback-safety"],
  "selected_additional_skills": [],
  "why": {
    "skill-name": ["reason 1", "reason 2"]
  },
  "skip": {
    "skill-name": "brief reason"
  }
}
```

Keep routing conservative but not exhaustive. Prefer fewer relevant skills over every possible skill.
