# TWAP Advanced Prices Integration Test Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add one cleanup-safe parameterized test proving all three advanced TWAP payload combinations are sent by the real client and accepted by Hyperliquid testnet.

**Architecture:** Wrap the live client's transport for one test case, copy only outbound `twapOrder` actions, and forward every request to the original transport. Assert the captured non-secret `details` shape and the server's running TWAP id, then cancel the exact TWAP and close any BTC position.

**Tech Stack:** Python 3.12, pytest/pytest-asyncio, aiohttp transport, Hyperliquid testnet, uv, Ruff, ty.

## Global Constraints

- Cover trigger+stop, trigger-only, and stop-only as three parameter cases.
- Capture only the action; never retain or print signatures, envelopes, nonces, keys, addresses, or environment values.
- Forward captured calls to the real testnet transport; this is not a mocked HTTP test.
- Choose a rounded trigger approximately 5% below current BTC mark and a rounded stop approximately 5% above it.
- Parse `twapId` before payload assertions, cancel that exact id in `finally`, and always close the BTC position in an inner `finally`.
- Run signed tests only with the repository's `IS_MAINNET=false` guard.
- Modify no production code.

---

### Task 1: Add Live Advanced-TWAP Contract Coverage

**Files:**
- Modify: `tests/integration/exchange/test_orders.py`
- Include: `docs/superpowers/plans/2026-08-05-twap-advanced-prices-integration.md`

**Interfaces:**
- Consumes: `AsyncHyperliquid.place_twap(..., trigger_px=..., stop_px=...)`, `_HttpTransport.post_json`, `InfoClient.mark_price`, and the existing `_market_request` cleanup pattern.
- Produces: `test_place_twap_advanced_prices`, collected as three testnet cases with ids `trigger-and-stop`, `trigger-only`, and `stop-only`.

- [ ] **Step 1: Add the parameterized live test**

Add `deepcopy` and `JsonValue` imports, then place this test beside the existing TWAP integration cases:

```python
@pytest.mark.parametrize(
    ("with_trigger", "with_stop"),
    [(True, True), (True, False), (False, True)],
    ids=("trigger-and-stop", "trigger-only", "stop-only"),
)
async def test_place_twap_advanced_prices(
    sub_hl: AsyncHyperliquid,
    monkeypatch: pytest.MonkeyPatch,
    with_trigger: bool,
    with_stop: bool,
) -> None:
    mark_px = await sub_hl.info.mark_price("BTC")
    trigger_value = round(mark_px * 0.95) if with_trigger else None
    stop_value = round(mark_px * 1.05) if with_stop else None
    trigger_px = None if trigger_value is None else float(trigger_value)
    stop_px = None if stop_value is None else float(stop_value)
    captured_actions: list[JsonObject] = []
    original_post_json = sub_hl._transport.post_json

    async def capture_action(url: str, payload: JsonObject) -> JsonValue:
        action = payload.get("action")
        if isinstance(action, dict) and action.get("type") == "twapOrder":
            captured_actions.append(deepcopy(cast(JsonObject, action)))
        return await original_post_json(url, payload)

    monkeypatch.setattr(sub_hl._transport, "post_json", capture_action)
    order = await _market_request(sub_hl, "BTC", notional=120)
    twap_id: int | None = None
    try:
        response = await sub_hl.place_twap(
            "BTC",
            True,
            order["sz"],
            5,
            trigger_px=trigger_px,
            stop_px=stop_px,
        )
        assert response["status"] == "ok"
        status = cast(JsonObject, response["response"]["data"]["status"])
        running = cast(JsonObject, status["running"])
        value = running["twapId"]
        assert isinstance(value, int)
        twap_id = value

        assert len(captured_actions) == 1
        details = cast(JsonObject, captured_actions[0]["details"])
        assert details["s"] == (
            None if stop_value is None else str(stop_value)
        )
        if trigger_value is None:
            assert details["t"] is None
        else:
            assert details["t"] == {"a": False, "p": str(trigger_value)}
    finally:
        try:
            if twap_id is not None:
                await sub_hl.cancel_twap("BTC", twap_id)
        finally:
            await sub_hl.close_position("BTC")
```

This is a characterization/integration follow-up to already implemented
production behavior. No new production implementation follows the test; its
sensitivity to a missing `details` action is the captured-action assertion,
while server acceptance is the real `twapId` response.

- [ ] **Step 2: Verify collection and static quality before signing**

Run:

```bash
uv run pytest --collect-only -q tests/integration/exchange/test_orders.py::test_place_twap_advanced_prices
uv run ruff format tests/integration/exchange/test_orders.py
uv run ruff check src tests benchmarks
uv run ty check tests/integration
```

Expected: exactly three cases collect; Ruff and ty exit zero. Collection must not create clients or signed actions.

- [ ] **Step 3: Run the targeted testnet cases**

Run outside the restricted network sandbox:

```bash
IS_MAINNET=false uv run pytest -q tests/integration/exchange/test_orders.py::test_place_twap_advanced_prices
```

Expected: three cases pass. Every case returns a running integer `twapId`, captures one action, cancels the exact TWAP, and closes BTC. If credentials are unavailable, preserve the test and report the fixture's credential error without exposing values.

- [ ] **Step 4: Run complete repository gates sequentially**

```bash
uv run ruff format --check src tests benchmarks
uv run ruff check src tests benchmarks
uv run ty check src/async_hyperliquid
uv run ty check tests/contracts
uv run ty check tests/integration
uv run ty check tests/oracle
uv run ty check tests/package
uv run ty check tests/public_api
uv run ty check tests/typing
uv run ty check tests/unit
uv run ty check benchmarks
uv run pytest -q tests/unit tests/contracts tests/oracle tests/public_api tests/package
```

Expected: Ruff and every separate ty process exit zero; deterministic pytest has zero failures.

- [ ] **Step 5: Inspect and commit the follow-up**

```bash
git diff --check
git diff -- tests/integration/exchange/test_orders.py docs/superpowers/plans/2026-08-05-twap-advanced-prices-integration.md
git status --short
git add tests/integration/exchange/test_orders.py docs/superpowers/plans/2026-08-05-twap-advanced-prices-integration.md
git commit -m "test: cover advanced TWAP integration"
```

Expected: the commit contains only the integration test and its implementation plan.
