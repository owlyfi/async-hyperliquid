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
