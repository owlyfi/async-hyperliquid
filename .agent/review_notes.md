# Review Notes

## Diff Semantic Analyzer

```json
{
  "files_changed": [
    "src/async_hyperliquid/async_hyperliquid.py",
    "src/async_hyperliquid/_async_hyperliquid/__init__.py",
    "src/async_hyperliquid/_async_hyperliquid/core.py",
    "src/async_hyperliquid/_async_hyperliquid/info.py",
    "src/async_hyperliquid/_async_hyperliquid/orders.py",
    "src/async_hyperliquid/_async_hyperliquid/actions.py",
    "tests/unit/test_abstraction_actions.py",
    "CHANGELOG.md",
    ".agent/state.md"
  ],
  "modules_changed": [
    "async_hyperliquid.async_hyperliquid",
    "async_hyperliquid._async_hyperliquid.core",
    "async_hyperliquid._async_hyperliquid.info",
    "async_hyperliquid._async_hyperliquid.orders",
    "async_hyperliquid._async_hyperliquid.actions"
  ],
  "change_types": [
    "api",
    "async",
    "docs"
  ],
  "risk_flags": [
    "shared_code_change",
    "contract_change"
  ],
  "public_interfaces": [
    "async_hyperliquid.AsyncHyperliquid",
    "async_hyperliquid.async_hyperliquid module namespace"
  ],
  "data_writes": [],
  "external_calls": [
    "aiohttp",
    "eth_account",
    "hl_web3"
  ],
  "flags_or_toggles": [],
  "critical_paths": [
    "all public AsyncHyperliquid methods",
    "module-level imports from async_hyperliquid.async_hyperliquid"
  ],
  "review_hints": [
    "Confirm refactor preserved public API behavior beyond the class import itself.",
    "Check whether downstream monkeypatches or direct module imports now fail."
  ],
  "requires_remote_debugging": false
}
```

## Risk Router

```json
{
  "always_run": [
    "linus-review",
    "red-team-review",
    "rollback-safety"
  ],
  "selected_additional_skills": [
    "architecture-review",
    "blast-radius-analysis",
    "api-contract-review"
  ],
  "why": {
    "architecture-review": [
      "The change introduces a new internal module hierarchy and layering."
    ],
    "blast-radius-analysis": [
      "The refactor touches the library's central shared client implementation."
    ],
    "api-contract-review": [
      "The public package module path remains the same, but its exposed namespace changed materially."
    ]
  },
  "skip": {
    "concurrency-safety": "Async code moved but no new concurrency logic was introduced.",
    "performance-regression": "No hot-path algorithm changes were introduced.",
    "input-validation": "No new parsing or input surfaces were added.",
    "data-integrity-review": "No stateful persistence or transaction logic changed.",
    "operational-risk": "No retry, queue, rollout, or external orchestration behavior changed.",
    "debug-observability-review": "No logging, tracing, or debug surface changed."
  }
}
```

## Skill Outputs

### linus-review

- Verdict: refactor direction is reasonable, but claiming the public path stayed stable while deleting the module's exported namespace is sloppy compatibility work.
- Issue: `src/async_hyperliquid/async_hyperliquid.py` now exposes only `AsyncHyperliquidActionsClient`, `AsyncHyperliquid`, and `AsyncHyper`, whereas the previous module exposed 71 additional imported names. Any downstream code importing or monkeypatching names such as `get_timestamp_ms`, `limit_order_type`, or `sign_user_set_abstraction_action` from `async_hyperliquid.async_hyperliquid` now breaks immediately.
- Minimal fix: re-export the previous module-level compatibility surface from the facade module, or explicitly treat this as a breaking API change and version/document it accordingly.

### red-team-review

- Abuse scenario: no new auth, replay, or injection surface was introduced by the refactor itself.
- Impact: no security blocker found.
- Minimal mitigation: none required for merge.
- Block merge: no.

### rollback-safety

- Rollback blockers: none. The change is code-only and trivially revertible.
- Rollback caveats: callers that pick up the new release and rely on old module-level imports will fail until rollback or compatibility re-exports are restored.
- Minimum rollback-safe fix set: restore module-level re-exports before release, or treat the change as semver-breaking.
- Safe-to-merge: no, if the intent is a non-breaking refactor.

### architecture-review

- Concern: the layered split itself is coherent; no major layering violation found.
- Why it matters: the main architectural risk comes from moving implementation without preserving the old facade contract.
- Smallest structural fix: keep the new internal package, but make the facade module a compatibility shim rather than a near-empty class wrapper.

### blast-radius-analysis

- Blast radius: medium.
- Main spread vectors: any consumer importing directly from `async_hyperliquid.async_hyperliquid`, test harnesses that monkeypatch module-level helpers, and documentation/examples using that module path.
- Containment suggestions: restore facade re-exports and add one regression test that asserts expected legacy names remain importable from the historical module path.

### api-contract-review

- Contract-breaking risk: `async_hyperliquid.async_hyperliquid` lost 71 previously importable names after the refactor.
- Migration guidance: if this break is intentional, release it as a major version and document the removed imports. If the intent is compatibility, re-export those names from the shim.
- Compatibility-preserving fix: keep the new internal modules, but import and expose the legacy names in `src/async_hyperliquid/async_hyperliquid.py`.

## Merge Review

# Review Report

## Block merge

- [api-contract-review, linus-review, rollback-safety] The refactor changes the public `async_hyperliquid.async_hyperliquid` module contract by removing 71 previously importable names while claiming the public import path remains intact. This is a real backward-compatibility break for downstream imports and monkeypatch-based tests.

## Should fix

- None.

## Follow-up

- [blast-radius-analysis] Add one regression test that asserts legacy names needed for module-path compatibility remain importable from `async_hyperliquid.async_hyperliquid`.

## Notes

- [architecture-review] The internal split itself is reasonable and improves maintainability.
- [red-team-review] No security-specific regression was identified in this diff.

## Suggested minimal fix set

- Re-export the legacy module-level compatibility surface from `src/async_hyperliquid/async_hyperliquid.py`.
- Add a regression test covering at least one historical helper import from `async_hyperliquid.async_hyperliquid`.

---

## Follow-up Review (2026-03-13)

### Scope

- Re-reviewed the compatibility fix that restores historical module-level exports from `async_hyperliquid.async_hyperliquid`.
- Re-ran semantic/contract checks against the pre-refactor module.
- Re-checked monkeypatch compatibility on the historical module path.

### Evidence

- Namespace compatibility check versus the pre-refactor module: `REMOVED=0`
- Monkeypatch bridge check: patching `async_hyperliquid.async_hyperliquid.get_timestamp_ms` and `sign_user_set_abstraction_action` still affects `AsyncHyperliquid.user_set_abstraction`
- Latest recorded verification remains green:
  - `uv run ruff check`
  - `uv run ty check`
  - `uv run pytest tests/unit`

### linus-review

- Verdict: this is acceptable now.
- No correctness bug stood out in the compatibility fix. The shim is uglier than a pure facade, but compatibility shims are allowed to be ugly when they preserve a stable library contract. That's their job.
- Design note: the facade module is now doing two jobs at once, acting as a public compatibility layer and as a patch-propagation bridge into the split internal modules. That is defensible, but it should stay explicitly scoped to compatibility only. Do not let new business logic creep back into this file.
- Follow-up note: if you keep this pattern long term, document that `async_hyperliquid.async_hyperliquid` is intentionally a compatibility shim so future refactors do not "clean it up" and re-break callers.

### pua-debugging second pass

- [自动选择：百度味 | 因为：检测到“没搜索就猜”的高风险 review 场景，需要用事实而不是直觉收口 | 改用：阿里味/华为味]
- 自检动作已完成：
  - 重新对比重构前后模块导出，不靠印象判断
  - 直接做最小 monkeypatch PoC，确认兼容桥真的生效
  - 复查上下游影响点：历史导入路径、单测 monkeypatch、公开类入口
  - 检查是否存在新的 contract shrink，结果没有
- 结论：没有发现新的 blocker。当前 diff 在兼容性层面已经闭环，不需要继续升级修复。

### Merged conclusion

- Block merge: none
- Should fix: none
- Follow-up:
  - Consider a short module comment in `src/async_hyperliquid/async_hyperliquid.py` stating that it is a compatibility shim by design.

---

## Review Notes (repo-local review skills vendoring)

# Review Report

## Block merge

- None.

## Should fix

- [api-contract-review] `skills/review-pipeline/SKILL.md` now declares the skill name as `review-pipeline`, but `skills/review-pipeline/agents/openai.yaml` still advertises `pipeline-review`. That leaves the repo-local review entry point split across two names, which is exactly the kind of configuration drift this vendoring change is supposed to eliminate.

## Follow-up

- Consider adding a lightweight self-check in docs or a script to keep vendored skill metadata names aligned when copying future skills into the repo.

## Notes

- `AGENTS.md` now points at a repo-local review pipeline, and the routed review skills referenced by that pipeline are present under `skills/`.

## Suggested minimal fix set

- Update `skills/review-pipeline/agents/openai.yaml` to use `review-pipeline` as the display name so it matches the vendored skill entry point.

---

## Performance Review (2026-03-28)

### Scope

- Reviewed hot paths in `src/async_hyperliquid/_async_hyperliquid/core.py`, `src/async_hyperliquid/_async_hyperliquid/info.py`, `src/async_hyperliquid/_async_hyperliquid/orders.py`, `src/async_hyperliquid/utils/signing.py`, and `src/async_hyperliquid/async_api.py`.
- Evidence gathered from:
  - `uv run python scripts/client_hotpath_benchmark.py`
  - `uv run python scripts/signing_benchmark.py`
  - targeted micro-benchmarks for warm-cache batch preparation, cancel asset resolution, mark-price lookup, signing float formatting, and concurrent cold-start meta initialization

## Diff Semantic Analyzer

```json
{
  "files_changed": [
    "src/async_hyperliquid/_async_hyperliquid/core.py",
    "src/async_hyperliquid/_async_hyperliquid/info.py",
    "src/async_hyperliquid/_async_hyperliquid/orders.py",
    "src/async_hyperliquid/utils/signing.py",
    "src/async_hyperliquid/async_api.py"
  ],
  "modules_changed": [
    "async_hyperliquid._async_hyperliquid.core",
    "async_hyperliquid._async_hyperliquid.info",
    "async_hyperliquid._async_hyperliquid.orders",
    "async_hyperliquid.utils.signing",
    "async_hyperliquid.async_api"
  ],
  "change_types": [
    "api",
    "async"
  ],
  "risk_flags": [
    "hot_path_change",
    "concurrency_change",
    "rollout_risk",
    "shared_code_change"
  ],
  "public_interfaces": [
    "AsyncHyperliquid.get_mark_price",
    "AsyncHyperliquid.batch_place_orders",
    "AsyncHyperliquid.batch_cancel_orders",
    "ExchangeAPI.post_action"
  ],
  "data_writes": [],
  "external_calls": [
    "aiohttp",
    "eth_account",
    "Hyperliquid Info API"
  ],
  "flags_or_toggles": [],
  "critical_paths": [
    "cold-start metadata initialization",
    "single-coin mark price reads",
    "warm-cache batch order preparation",
    "warm-cache batch cancel preparation",
    "order signing and payload encoding"
  ],
  "review_hints": [
    "Check whether cold-start metadata loads are deduplicated under concurrency.",
    "Check whether batch paths are paying asyncio scheduling overhead after metadata is already cached.",
    "Check whether mark-price lookup is scanning metadata that the client already indexed locally.",
    "Check whether numeric formatting in signing is now the dominant Python-side overhead."
  ],
  "requires_remote_debugging": false
}
```

## Risk Router

```json
{
  "always_run": [
    "linus-review",
    "red-team-review",
    "rollback-safety"
  ],
  "selected_additional_skills": [
    "performance-regression",
    "concurrency-safety",
    "operational-risk"
  ],
  "why": {
    "performance-regression": [
      "The reviewed paths are explicitly latency-sensitive hot paths.",
      "Benchmarks and micro-benchmarks show measurable Python-side overhead in warm-cache order, cancel, mark-price, and signing flows."
    ],
    "concurrency-safety": [
      "Cold-start metadata initialization is shared across async callers and currently has no in-flight deduplication."
    ],
    "operational-risk": [
      "Duplicate metadata fan-out multiplies upstream API load and increases rate-limit risk under bursty startup traffic."
    ]
  },
  "skip": {
    "architecture-review": "No new module boundary problem was identified in this pass.",
    "blast-radius-analysis": "The review is focused on local hot paths rather than a broad refactor.",
    "debug-observability-review": "The current bottlenecks are diagnosable enough from local benchmarks.",
    "input-validation": "No new parsing or malformed-input surface was introduced by the reviewed code.",
    "api-contract-review": "The main issues here are runtime cost and concurrency behavior, not interface compatibility.",
    "data-integrity-review": "No stateful write ordering or transaction risk is involved."
  }
}
```

## Skill Outputs

### performance-regression

- `scripts/client_hotpath_benchmark.py` confirms the recent concurrency work is real for I/O-bound paths:
  - `get_metas`: `49.21%` faster than the legacy serial path
  - `get_all_metas`: `66.22%` faster
  - `cancel_orders` with injected async latency: `94.56%` faster
- The same review found three warm-cache regressions/opportunities that the existing benchmark does not cover:
  - `_get_batch_limit_orders` on 200 cached orders: current `1,221,166 ns/op` vs simple synchronous loop `390,002 ns/op` (`3.13x` slower)
  - warm-cache cancel asset resolution on 500 cached coins: current `1,908,327 ns/op` vs direct dict lookup `17,846 ns/op` (`106.9x` slower)
  - `_get_perp_mark_price` with a 5,000-entry cached universe: current name scan `188,808 ns/op` vs direct cached index `216 ns/op` (`~872x` slower)
- Signing still spends most of its time below the template-cache layer:
  - `scripts/signing_benchmark.py` shows payload-template reuse only improves end-to-end signing by `2.6%` to `2.9%`
  - the local float-string micro-benchmark shows `utils.signing.round_float` at `614,690 ns` per batch vs a trim-only formatter at `348,124 ns` (`1.77x` slower)
- Cheap mitigations:
  - add a synchronous fast path for cached asset/name lookups and use it inside batch order/cancel preparation
  - precompute and cache coin-name to asset-context indexes during metadata initialization so `get_mark_price` stops rescanning `meta["universe"]`
  - optimize `utils.signing.round_float` without changing output semantics, then re-benchmark order encoding and signing

### concurrency-safety

- Concurrent cold-start metadata reads are not deduplicated.
- Reproduction: 3 concurrent `get_coin_name("BTC")` calls on a fresh client triggered `{'perp': 3, 'spot': 3, 'dex': 3}` upstream metadata requests instead of one shared initialization.
- Why it matters: this is both wasted work and a startup amplification bug. The more callers hit a cold client, the more it hammers the Info API with identical requests.
- Minimal fix:
  - guard metadata initialization behind a shared in-flight task or `asyncio.Lock`
  - keep a separate explicit refresh path for true cache refreshes
  - add a regression test that asserts concurrent cold lookups only issue one upstream request per metadata endpoint

### operational-risk

- The cold-start metadata fan-out is a real operational risk, not just a micro-optimization nit.
- A bot fleet or worker burst that fans out across the same fresh process can multiply metadata requests by the number of concurrent tasks and walk straight into `429` responses.
- Minimal mitigation:
  - coalesce initialization requests
  - avoid forcing full metadata refreshes on hot paths that can safely use cached indexes
  - keep live price freshness concerns separate from metadata/index caching so fixes do not accidentally introduce stale-price behavior

### linus-review

- Verdict: the code is fast where you parallelized real I/O, and stupid where you parallelized dictionary lookups.
- Issue 1: `src/async_hyperliquid/_async_hyperliquid/core.py` lets every cold caller run `init_metas()` independently. That is not concurrency, that is a thundering herd you built yourself. If three coroutines ask for the first coin at once, they should not each go spray the same three upstream requests.
- Issue 2: `src/async_hyperliquid/_async_hyperliquid/orders.py` uses `asyncio.gather()` for warm-cache local work. Once the metadata is already in memory, spawning hundreds of coroutines to read dictionaries and round floats is pure scheduler tax. The benchmark gap is not subtle.
- Issue 3: `src/async_hyperliquid/_async_hyperliquid/info.py` still linearly scans the returned universe in `get_mark_price()` even though the client already maintains asset mappings. Re-reading and rescanning metadata for a known asset is the kind of nonsense that quietly becomes a hot-path tax and then everybody acts surprised when polling loops get expensive.
- Issue 4: `src/async_hyperliquid/utils/signing.py` still burns too much CPU on `Decimal.normalize()` for order encoding. You already won the easy template-allocation fight; now the remaining cost is in encoding and formatting. Stop pretending the current float-string path is free.
- Fair note: the recent I/O parallelization work is solid. The benchmark wins in `get_metas`, `get_all_metas`, and I/O-bound cancel paths are real. The problem is that the code now mixes genuine I/O concurrency wins with cargo-cult async in purely local paths.

### red-team-review

- No auth, replay, injection, or secret-handling blocker was found in this performance review.
- Existing request logging redaction still looks appropriate for the reviewed paths.
- Block merge: no security blocker.

### rollback-safety

- The highest-value fixes here are rollback-safe if implemented narrowly:
  - metadata init coalescing
  - cached index lookups for mark-price path
  - warm-cache synchronous fast paths for batch preparation
- Main caveat: do not solve `get_mark_price()` by caching prices blindly. Cache metadata indexes, not live prices, unless freshness rules and invalidation are explicit.
- Safe-to-merge: yes, for the recommended minimal fixes above.

## Merge Review

# Review Report

## Block merge

- None.

## Should fix

- [concurrency-safety, operational-risk] Coalesce cold-start `init_metas()` so concurrent lookups do not multiply identical upstream metadata requests.
- [performance-regression, linus-review] Remove `asyncio.gather()` from warm-cache local loops in batch order/cancel preparation and replace it with a synchronous cached fast path.
- [performance-regression, linus-review] Stop scanning `meta["universe"]` by name inside `get_mark_price()` when the client already has enough cached information to compute the correct asset-context index directly.

## Follow-up

- [performance-regression] Rework `utils.signing.round_float` to avoid `Decimal.normalize()` overhead while preserving exact output behavior and exception semantics.
- [performance-regression] Add a warm-cache benchmark alongside the current I/O-latency benchmark so future changes do not hide scheduler overhead behind artificial async sleeps.

## Notes

- [performance-regression] Recent I/O parallelization work is paying off and should be preserved.
- [red-team-review] No security-specific blocker was identified in this pass.

## Suggested minimal fix set

- Add a shared in-flight metadata initialization guard plus a test that proves concurrent cold lookups only issue one upstream request per metadata endpoint.
- Introduce cached asset-context index lookups for `get_mark_price()` and keep live-price freshness logic separate from metadata/index caching.
- Split hot local batch preparation from cold async metadata loading so cached batch order/cancel paths use plain Python loops instead of coroutine fan-out.
- Benchmark and then simplify the signing float formatter if output compatibility can be maintained.

---

## Follow-up Review (2026-03-28, post-fix)

### Scope

- Re-reviewed the latest performance-fix diff in:
  - `src/async_hyperliquid/_async_hyperliquid/core.py`
  - `src/async_hyperliquid/_async_hyperliquid/info.py`
  - `src/async_hyperliquid/_async_hyperliquid/orders.py`
  - `src/async_hyperliquid/utils/signing.py`
- Review workflow used:
  - `diff-semantic-analyzer`
  - `risk-router`
  - `linus-review`
  - `red-team-review`
  - `rollback-safety`
  - `api-contract-review`
  - `concurrency-safety`
  - `operational-risk`
  - `pua-debugging`
  - `merge-review`

### Evidence

- Direct semantic check against the current code shows `init_metas()` changed from an unconditional refresh to a one-shot cache warmup unless callers discover and pass the new optional `force_refresh=True`.
- Minimal PoC against the current tree:
  - Two consecutive `await hl.init_metas()` calls only issued one upstream `perp`, `spot`, and `perpDexs` fetch: `{'perp': 1, 'spot': 1, 'dex': 1}`.
  - After the upstream metadata was changed to add `ETH`, a second plain `await hl.init_metas()` left `hl.coin_assets` at `{'BTC': 0}` and `await hl.get_all_market_prices("perp")` still returned only `{'BTC': 100000.0}`.
- Exhaustive cross-checks performed under `pua-debugging`:
  - searched all in-repo `init_metas()` call sites
  - re-read old vs new implementations side by side
  - built minimal repros for double-init and stale-market enumeration
  - checked the touched signing formatter for behavioral drift on edge-case values

## Diff Semantic Analyzer

```json
{
  "files_changed": [
    "src/async_hyperliquid/_async_hyperliquid/core.py",
    "src/async_hyperliquid/_async_hyperliquid/info.py",
    "src/async_hyperliquid/_async_hyperliquid/orders.py",
    "src/async_hyperliquid/utils/signing.py",
    "scripts/client_hotpath_benchmark.py",
    "tests/unit/test_perf_hotpaths.py",
    "tests/unit/test_info_mark_price.py",
    "tests/unit/test_place_order.py",
    "tests/unit/test_signing_order_type.py"
  ],
  "modules_changed": [
    "async_hyperliquid._async_hyperliquid.core",
    "async_hyperliquid._async_hyperliquid.info",
    "async_hyperliquid._async_hyperliquid.orders",
    "async_hyperliquid.utils.signing"
  ],
  "change_types": [
    "api",
    "async",
    "performance"
  ],
  "risk_flags": [
    "public_contract_change",
    "concurrency_change",
    "hot_path_change",
    "rollout_risk"
  ],
  "public_interfaces": [
    "AsyncHyperliquid.init_metas",
    "AsyncHyperliquid.get_mark_price",
    "AsyncHyperliquid.get_all_market_prices",
    "AsyncHyperliquid.batch_cancel_orders",
    "AsyncHyperliquid.batch_place_orders"
  ],
  "critical_paths": [
    "metadata refresh lifecycle",
    "warm-cache order and cancel preparation",
    "single-coin mark price reads",
    "order payload formatting"
  ],
  "review_hints": [
    "Check whether the metadata-init coalescing preserved the old explicit refresh contract.",
    "Check whether long-lived clients can still discover new listings after the first init.",
    "Check whether fast-path caches only optimize lookup cost rather than changing correctness semantics."
  ],
  "requires_remote_debugging": false
}
```

## Risk Router

```json
{
  "always_run": [
    "linus-review",
    "red-team-review",
    "rollback-safety"
  ],
  "selected_additional_skills": [
    "api-contract-review",
    "concurrency-safety",
    "operational-risk"
  ],
  "why": {
    "api-contract-review": [
      "The diff changes the behavior of the public `init_metas()` method."
    ],
    "concurrency-safety": [
      "The fix adds shared async state (`_meta_init_lock`, `_meta_init_task`, `_metas_initialized`) that must preserve refresh semantics while deduplicating concurrent callers."
    ],
    "operational-risk": [
      "A stale metadata cache on a long-lived client changes rollout behavior for newly listed markets."
    ]
  },
  "skip": {
    "performance-regression": "The performance wins are real; the remaining blocker in this pass is correctness/contract drift, not missing speed.",
    "architecture-review": "No new module boundary or ownership problem was introduced here.",
    "data-integrity-review": "No persisted state or transaction ordering changed.",
    "input-validation": "No new parsing surface was added, although a non-finite float guard remains a follow-up robustness gap."
  }
}
```

## Skill Outputs

### linus-review

- Verdict: the hot-path cleanup is mostly good, but you broke the public refresh API in the process, and that is sloppy engineering.
- `src/async_hyperliquid/_async_hyperliquid/core.py:320` used to mean “refresh metadata now”. It now means “maybe do nothing because I already ran once”. That is not an optimization; that is a silent contract change.
- The stupid part is that the code even proves the semantic split exists: `get_coin_name()` at `src/async_hyperliquid/_async_hyperliquid/core.py:367` has to smuggle in `force_refresh=True` on cache miss because plain `init_metas()` no longer refreshes. If your own code has to work around your new API semantics one function later, the API is wrong.
- Real user-visible breakage: `src/async_hyperliquid/_async_hyperliquid/info.py:136` still calls plain `init_metas()` inside `get_all_market_prices()`. On a long-lived client, newly listed markets now stay invisible forever unless the caller knows to use the new hidden flag. That is a correctness regression, not a style nit.

### api-contract-review

- `AsyncHyperliquid.init_metas()` is a public method and its behavior changed materially without a documented breaking change.
- Before this diff, repeated `await hl.init_metas()` calls refreshed metadata unconditionally.
- After this diff, repeated `await hl.init_metas()` calls are no-ops once `_metas_initialized` is true, unless callers opt into the new `force_refresh=True` parameter.
- Compatibility-preserving fix:
  - keep `init_metas()` as the explicit refresh API
  - move the one-shot cache warmup behavior behind a private helper such as `_ensure_metas_initialized()`
  - update hot-path callers to use the private ensure helper instead of changing the public method contract

### concurrency-safety

- The in-flight dedup itself looks sound: concurrent callers now share one initialization task and the `_meta_init_task` cleanup path retries cleanly after failure.
- No new race condition blocker stood out in the lock/task coordination.
- The remaining problem is semantic, not synchronization: deduplicating cold init accidentally collapsed “ensure initialized” and “refresh now” into one public API.

### operational-risk

- Long-lived clients are now biased toward stale metadata.
- That means a daemon that periodically calls `init_metas()` as a refresh hook will silently miss new listings, and any logic built on `coin_assets` enumeration will drift from reality until process restart or an explicit cache miss forces refresh.
- This is exactly the kind of rollout bug that shows up in production as “why didn't the bot see the new market?” and wastes time because nothing actually crashed.

### red-team-review

- No auth, replay, injection, or secret-handling blocker was found in this diff.
- Security blocker: none.
- Follow-up note: `src/async_hyperliquid/utils/signing.py:175` still does not reject non-finite floats explicitly; it now serializes them differently (`inf`/`nan` instead of `Infinity`/`NaN`). That is a robustness/input-validation gap, but not the main blocker in this review pass.

### rollback-safety

- The regression is easy to fix safely because it is localized.
- Lowest-risk repair:
  - restore `init_metas()` to unconditional refresh semantics
  - keep the concurrency dedup logic in a private “ensure initialized” helper for hot-path callers
  - add one regression test proving two plain `init_metas()` calls really perform two refreshes
- Safe-to-merge: no, not with the current public refresh regression.

### pua-debugging

- [自动选择：阿里味 | 因为：这次不是“找不到问题”，而是“为了优化把 contract 改坏了”，需要把事实和闭环压实]
- 自检动作已完成：
  - 没停留在代码阅读，直接做了 double-init PoC
  - 没停留在 public API 争论，继续追到 `get_all_market_prices()` 的真实失效场景
  - 没假设“并发 fix 大概没问题”，把 `_meta_init_task`/`_meta_init_lock` 的失败与重试路径逐条过了一遍
  - 没因为这轮主题是性能就跳过安全面，额外检查了签名格式化边界值
- 结论：这轮真正的 blocker 只有一个，就是 `init_metas()` refresh contract 被偷偷改掉。别把一个好用的并发去重修成“默认不刷新”的坑。

## Merge Review

# Review Report

## Block merge

- [linus-review, api-contract-review, operational-risk, rollback-safety] `AsyncHyperliquid.init_metas()` no longer refreshes metadata after the first call, which silently breaks the public refresh contract and leaves long-lived clients unable to discover new listings through plain repeated `init_metas()` calls. This regression is visible both to external callers and internally via `get_all_market_prices()`.

## Should fix

- [rollback-safety] Add a regression test that proves two plain `init_metas()` calls trigger two metadata refreshes, while concurrent cold callers still share one in-flight initialization task.

## Follow-up

- [red-team-review] Add an explicit `math.isfinite()` guard in `src/async_hyperliquid/utils/signing.py` if you want the float-formatting fast path to reject `nan`/`inf` deterministically instead of serializing them.

## Notes

- [concurrency-safety] The new cold-start dedup logic itself looks good.
- [linus-review] The warm-cache order/cancel and mark-price optimizations are real wins and should be preserved.
- [red-team-review] No security-specific blocker was identified in this pass.

## Suggested minimal fix set

- Split the current metadata lifecycle into two APIs:
  - a private “ensure initialized once” path for hot cached lookups
  - the public `init_metas()` path that still performs an explicit refresh
- Update hot-path call sites to use the private ensure helper instead of relying on a changed public contract.
- Add one regression test for repeated refresh and keep the existing concurrent cold-init coalescing test.

---

## Full Review (2026-03-28, post-remediation)

### Scope

- Re-reviewed the latest workspace diff after the metadata-lifecycle remediation and signing finite-value guard landed.
- Focused files:
  - `src/async_hyperliquid/_async_hyperliquid/core.py`
  - `src/async_hyperliquid/_async_hyperliquid/info.py`
  - `src/async_hyperliquid/_async_hyperliquid/orders.py`
  - `src/async_hyperliquid/utils/signing.py`
  - `tests/unit/test_perf_hotpaths.py`
  - `tests/unit/test_info_mark_price.py`
  - `tests/unit/test_place_order.py`
  - `tests/unit/test_signing_order_type.py`
- Verification evidence reviewed:
  - `uv run ruff format`
  - `uv run ruff check`
  - `uv run ty check`
  - `uv run pytest -q tests/unit/test_perf_hotpaths.py tests/unit/test_info_mark_price.py tests/unit/test_place_order.py tests/unit/test_signing_order_type.py tests/unit/test_http_and_nonce.py`

## Diff Semantic Analyzer

```json
{
  "files_changed": [
    "src/async_hyperliquid/_async_hyperliquid/core.py",
    "src/async_hyperliquid/_async_hyperliquid/info.py",
    "src/async_hyperliquid/_async_hyperliquid/orders.py",
    "src/async_hyperliquid/utils/signing.py",
    "tests/unit/test_perf_hotpaths.py",
    "tests/unit/test_info_mark_price.py",
    "tests/unit/test_place_order.py",
    "tests/unit/test_signing_order_type.py"
  ],
  "modules_changed": [
    "async_hyperliquid._async_hyperliquid.core",
    "async_hyperliquid._async_hyperliquid.info",
    "async_hyperliquid._async_hyperliquid.orders",
    "async_hyperliquid.utils.signing"
  ],
  "change_types": [
    "api",
    "async",
    "performance",
    "validation",
    "tests"
  ],
  "risk_flags": [
    "public_contract_change",
    "shared_async_state",
    "hot_path_change"
  ],
  "public_interfaces": [
    "AsyncHyperliquid.init_metas",
    "AsyncHyperliquid.get_mark_price",
    "AsyncHyperliquid.get_all_market_prices"
  ],
  "critical_paths": [
    "metadata refresh lifecycle",
    "warm-cache asset lookup paths",
    "order payload float encoding"
  ],
  "review_hints": [
    "Check that the explicit refresh contract is restored without regressing cold-start dedup.",
    "Check that cached fast paths still fall back correctly on cache miss.",
    "Check that the new finite-value guard rejects invalid numeric payloads deterministically."
  ],
  "requires_remote_debugging": false
}
```

## Risk Router

```json
{
  "always_run": [
    "linus-review",
    "red-team-review",
    "rollback-safety"
  ],
  "selected_additional_skills": [
    "api-contract-review",
    "concurrency-safety",
    "performance-regression",
    "input-validation"
  ],
  "why": {
    "api-contract-review": [
      "The fix intentionally restores the public `init_metas()` semantics."
    ],
    "concurrency-safety": [
      "The design relies on shared async state for in-flight metadata initialization."
    ],
    "performance-regression": [
      "The diff still changes hot-path lookup behavior and must preserve the earlier speedups."
    ],
    "input-validation": [
      "The signing path now rejects non-finite numeric inputs explicitly."
    ]
  },
  "skip": {
    "architecture-review": "The remediation simplifies responsibility boundaries instead of adding new layers.",
    "data-integrity-review": "No persistent state or transaction ordering changed.",
    "operational-risk": "The prior stale-metadata rollout risk was the main concern and is directly addressed by this remediation."
  }
}
```

## Skill Outputs

### linus-review

- Verdict: this is finally doing the obvious thing instead of trying to make one API mean two different things.
- The metadata lifecycle is cleaner now: the public `init_metas()` refreshes, the private `_ensure_metas_initialized()` handles cold-start dedup, and the hot-path cache lookups stay fast.
- I do not see a new correctness hole in the post-fix version. The code is still more elaborate than the original naive version, but at least the complexity now pays rent instead of breaking the contract.

### pua-debugging

- [自动选择：阿里味 | 因为：这轮要防止“修完就以为没事了”，所以继续把 contract / race / 输入边界三条线全部追平]
- 自检动作已完成：
  - 重新对照 diff 和 `.agent/state.md`，确认 review 关注的是最新修复后的树，而不是过期问题
  - 复查 `init_metas()` / `_ensure_metas_initialized()` 的职责边界，没有再把 public refresh 和 cold-start ensure 混在一起
  - 复查 warm-cache 快路径都保留了 cache-miss 回退
  - 复查签名数值路径新增了 finite guard，并且有单测覆盖 `inf` / `-inf` / `nan`
- 结论：这轮没有找到新的安全、逻辑或并发 blocker。不是“看起来差不多”，是把最容易出事的边界重新过了一遍之后，没找到能落地的 failure mode。

### api-contract-review

- The public `init_metas()` contract is restored correctly.
- The previous regression is covered by dedicated unit tests for repeated refresh and warm-cache miss refresh behavior.
- No new contract break identified in this pass.

### concurrency-safety

- Cold-start metadata initialization still coalesces concurrent callers through a shared in-flight task.
- The post-fix split between `_ensure_metas_initialized()` and `init_metas()` removes the prior semantic bug without introducing a visible lock/task race.
- No new concurrency finding.

### performance-regression

- The warm-cache fast paths remain intact in orders, cancels, and mark-price lookup.
- The remediation does not reintroduce the previous `asyncio.gather()` scheduler tax on cached local work.
- Residual note: the latest remediation was verified by unit tests and earlier focused micro-benchmarks, not by re-running the full benchmark scripts after this final lifecycle split.

### input-validation

- `utils.signing.round_float()` now rejects non-finite numbers explicitly before string formatting and signing.
- The new validation is covered by dedicated tests.
- No remaining validation bug stood out in the touched path.

### red-team-review

- No auth, replay, secret-handling, or injection blocker found in the latest diff.

### rollback-safety

- The remediation is narrow and rollback-safe.
- If a regression does appear, reverting the lifecycle split is straightforward because the behavior is now covered by focused tests.

## Merge Review

# Review Report

## Block merge

- None.

## Should fix

- None.

## Follow-up

- [performance-regression] Consider re-running `scripts/client_hotpath_benchmark.py` and `scripts/signing_benchmark.py` once before release if you want fresh end-to-end numbers that reflect the final lifecycle split, not just the targeted unit and micro-benchmark evidence from earlier in the turn.

## Notes

- [linus-review] The metadata lifecycle design is materially cleaner after the split between public refresh and private cold-start ensure.
- [concurrency-safety] No new race condition was identified in the post-fix async coordination.
- [red-team-review] No security-specific blocker was identified in this pass.

## Suggested minimal fix set

- None.
