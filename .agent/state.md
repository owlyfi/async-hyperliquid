# State

- Date: 2026-03-13
- Branch: `codex/refactor-async-hyperliquid`
- Task: Release the `AsyncHyperliquid` maintainability refactor as patch version `0.4.3`, preserving both the public `AsyncHyperliquid` API and the historical module-level compatibility surface.
- Progress: Added an internal `_async_hyperliquid` package with chained client classes for core setup, read APIs, order flows, and signed account actions. Restored legacy helper re-exports from `src/async_hyperliquid/async_hyperliquid.py`, added compatibility bridges so monkeypatching the historical module path still affects the new internal implementations, and bumped the package version/changelog to `0.4.3`.
- Verification: `uv run ruff format src/async_hyperliquid/async_hyperliquid.py tests/unit/test_abstraction_actions.py`, `uv run ruff check`, `uv run ty check`, and `uv run pytest tests/unit` all passed after the compatibility fix and release metadata update.
