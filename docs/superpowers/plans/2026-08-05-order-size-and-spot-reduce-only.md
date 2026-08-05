# Order Size and Spot Reduce-Only Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Centralize size normalization and reject spot reduce-only orders locally without duplicating Exchange minimum-notional policy.

**Architecture:** `_internal/encoding.py` owns deterministic wire-number normalization and venue-validity checks available at encoding time. `AsyncHyperliquid.place_twap` reuses size normalization and performs its own spot reduce-only check because TWAP has a separate action encoder.

**Tech Stack:** Python 3.12, pytest, Ruff, ty, uv

## Global Constraints

- `_round_size` remains a pure rounding primitive.
- Spot and outcome requests with `ro=True` fail before signing or submission.
- No production code calculates or gates minimum notional with `px * sz`.
- Perpetual reduce-only requests below 10 USDC continue to encode.

---

### Task 1: Normalize sizes in one helper

**Files:**
- Modify: `tests/unit/test_encoding.py`
- Modify: `tests/unit/test_exchange.py`
- Modify: `src/async_hyperliquid/_internal/encoding.py`
- Modify: `src/async_hyperliquid/client.py`

**Interfaces:**
- Produces: `_normalize_size(value: float, size_decimals: int) -> float | int`.
- Consumes: `_round_size` and market `size_decimals`.

- [x] **Step 1: Write failing consumer-visible tests**

Split the combined below-precision encoding test so the size case requires
`order size is below market precision`. Add non-finite size cases requiring
`size must be finite and greater than zero`. Tighten the existing TWAP
below-precision assertion to require the same order-size error.

- [x] **Step 2: Verify RED**

Run the named encoding and TWAP tests. The size-message expectations must fail
against the current scattered checks.

- [x] **Step 3: Implement `_normalize_size`**

Add the helper, use it from `encode_order`, import it in `client.py`, and use it
from `place_twap`. Remove the duplicated post-round checks.

- [x] **Step 4: Verify GREEN**

Run `tests/unit/test_encoding.py` and the focused TWAP tests.

### Task 2: Reject spot reduce-only requests

**Files:**
- Modify: `tests/unit/test_encoding.py`
- Modify: `tests/unit/test_orders.py`
- Modify: `tests/unit/test_exchange.py`
- Modify: `src/async_hyperliquid/_internal/encoding.py`
- Modify: `src/async_hyperliquid/client.py`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: `encode_order(..., is_spot=...)`, `PlaceOrderRequest.ro`, and
  `place_twap(..., reduce_only=...)`.
- Produces: `ValueError("spot orders cannot be reduce-only")` before signing.

- [x] **Step 1: Write failing spot tests and notional characterizations**

Add tests proving spot reduce-only fails through `encode_order`, `place_orders`,
`modify_order`, and `place_twap` without submission. Add passing
characterizations proving sub-10 notional perpetual reduce-only and spot
non-reduce-only requests still encode.

- [x] **Step 2: Verify RED**

Run the new spot reduce-only tests and confirm current code submits or encodes
the invalid requests.

- [x] **Step 3: Implement minimal venue gates**

In `encode_order`, reject `is_spot and order.get("ro", False)`. In
`place_twap`, reject `market.is_spot and reduce_only` before trigger price work
or submission. Add one changelog bullet.

- [x] **Step 4: Verify GREEN and complete checks**

Run focused suites, Ruff, sequential CI `ty` shards, and
`pytest -q tests/unit tests/public_api tests/contracts tests/package`.

- [x] **Step 5: Commit**

```bash
git add src/async_hyperliquid/_internal/encoding.py src/async_hyperliquid/client.py tests/unit/test_encoding.py tests/unit/test_orders.py tests/unit/test_exchange.py CHANGELOG.md docs/superpowers/specs/2026-08-05-order-size-and-spot-reduce-only-design.md docs/superpowers/plans/2026-08-05-order-size-and-spot-reduce-only.md
git commit -m "fix: validate spot order boundaries"
```
