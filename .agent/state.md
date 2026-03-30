# State

- Date: 2026-03-30
- Branch: `main`
- Task: Add optional `builder` forwarding to the close-position APIs so the single-coin, selected-coin, all-position, and per-DEX close helpers can attach builder fees just like `batch_place_orders`.
- Progress: Extended `AsyncHyperliquidOrdersClient.close_all_positions()`, `close_dex_positions()`, `close_positions()`, and `close_position()` with optional keyword-only `builder: OrderBuilder | None = None` arguments, then threaded that value through the existing batched market-order path without changing any close-order selection logic. Added unit coverage proving the all-position path, per-DEX wrapper, selected-coin batch path, and single-coin convenience wrapper all pass the builder payload through unchanged, recorded the user-visible API change in `CHANGELOG.md`, and bumped the package version to `0.4.7` so this API expansion does not get mixed into the already documented `0.4.6` release.
- Verification: `uv run ruff format`, `uv run ruff check`, `uv run ty check`, and `uv run pytest -q tests/unit/test_place_order.py` all passed on 2026-03-30 after the full close-helper builder expansion. `uv run ty check src/async_hyperliquid/_async_hyperliquid/orders.py` also passed, so no `# type: ignore` was required.
