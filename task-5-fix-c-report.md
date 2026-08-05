# Task 5 Fix C Report

- Base: `c9ffa08d8878f901ccd400afcefad365148923da`
- Commit: `feat: record safe live benchmark failures` (handoff SHA reported after commit)
- Scope: schema-v2 failure context, runner failure capture, `run_live` persistence, publication null enforcement, operator docs, and deterministic tests.
- Excluded: fix-B publication transaction mechanics, report-size bounds, round caps, live/network/publication execution, and production transport changes.

## Result

- Every report has `failure_context`: `null` when valid and an exact allowlisted mapping for invalid runtime reports.
- Concurrent failures retain the first failed operation/slot, aggregate counts, logical/measured round, and targeted recovery outcome after all tasks are inspected.
- Placement, provider-suite, recovery, client-close, preflight, setup, artifact, and combined failures use fixed reasons and bounded safe context.
- Classification walks at most 32 exception nodes and four link levels using non-executing typed state. It recognizes typed 429 status, timeout, protocol, unsuccessful response, indeterminate action, placement, recovery, close, preflight, and internal failure; it never renders exception text.
- Existing `IndeterminateActionError` remains `indeterminate_action` when no HTTP status survives the client abstraction. Production transport was not modified.
- Valid publication requires `failure_context=null` and the exact updated top-level schema.

## Security and operations

- Hostile exception messages containing credentials, addresses, OIDs, CLOIDs, nonces, signatures, bodies, and response text are absent from invalid report JSON.
- `rate_limited` instructs operators not to rerun immediately.
- `cleanup_ok=false` or `recovery_ok=false` requires manual testnet-subaccount inspection.

## Verification

- RED/GREEN focused runner, CLI, results, reporting, and documentation tests.
- Final focused gate: 195 passed.
- Ruff format check: 79 files already formatted.
- Ruff check: passed.
- Nine sequential `ty` shards passed: `src/async_hyperliquid`, `tests/contracts`, `tests/integration`, `tests/oracle`, `tests/package`, `tests/public_api`, `tests/typing`, `tests/unit`, and `benchmarks`.
- `git diff --check c9ffa08d -- benchmarks tests`: passed.
- No live benchmark, network call, report publication, or results generation was run.

## Review

- Mandatory semantic/risk routing selected Linus, red team, rollback, concurrency, debug/observability, operational risk, input validation, API contract, and data integrity reviews.
- Five review-fix findings were fixed with regressions: combined close context preservation, non-executing status access, persisted recovery-failure coverage, non-executing cause/group traversal, and construction-failure round context.
- Final merged recommendation: accept; no open or deferred findings.
