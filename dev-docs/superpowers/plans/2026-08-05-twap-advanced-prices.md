# TWAP Advanced Prices Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add independently optional `trigger_px` and `stop_px` arguments to `AsyncHyperliquid.place_twap` and emit Hyperliquid's exact action-level `details` wire shape.

**Architecture:** The root client resolves market precision and mark price, then builds a typed encoded details object. The info-independent exchange client conditionally attaches that object beside `twap`, preserving the historical action when both arguments are absent.

**Tech Stack:** Python 3.12, asyncio, `TypedDict`, msgpack/EIP-712 signing, pytest/pytest-asyncio, uv, Ruff, ty.

## Global Constraints

- Public argument names are exactly `trigger_px` and `stop_px`, both keyword-only `float | None` values defaulting to `None`.
- When both arguments are `None`, omit `details` entirely so legacy payload bytes and signatures do not change.
- Within an emitted `details`, a missing stop price is `"s": null` and a missing trigger price is `"t": null`.
- Preserve the official MessagePack insertion order: `details` is `t, s`, and a non-null trigger is `p, a`; key sorting is disabled and changing either order changes the recovered signer.
- Compute trigger `a` from the final encoded trigger price: `float(encoded_trigger_px) > mark_price`; equality is `false`.
- Reject invalid prices and mark-price failures before nonce consumption, signing, or transport.
- Use the existing order-price precision and outcome-market rules; add no dependencies and perform no unrelated refactor.

---

## File Structure

- `src/async_hyperliquid/types/exchange.py`: exact nullable advanced-TWAP wire types and optional action member.
- `src/async_hyperliquid/exchange.py`: conditional assembly of the signed `twapOrder` action.
- `src/async_hyperliquid/client.py`: public arguments, market-aware price normalization, and mark-price comparison.
- `tests/unit/test_actions.py`: resolved action construction boundary.
- `tests/unit/test_exchange.py`: intent-level combinations, comparison boundary, validation, and no-side-effect failures.
- `tests/public_api/test_surface.py`: stable public signature contract.
- `tests/typing/test_types.py`: static typing use of both new arguments.
- `README.md` and `CHANGELOG.md`: user-facing behavior and release note.

### Task 1: Encode Optional Details at the Exchange Boundary

**Files:**
- Modify: `tests/unit/test_actions.py`
- Modify: `src/async_hyperliquid/types/exchange.py`
- Modify: `src/async_hyperliquid/exchange.py`

**Interfaces:**
- Consumes: existing `EncodedTwapOrder` and `ExchangeClient._submit_action`.
- Produces: `EncodedTwapTrigger`, `EncodedTwapDetails`, and `_submit_twap(twap, *, details: EncodedTwapDetails | None = None, expires_after: int | None = None)`.

- [ ] **Step 1: Write the failing action-payload test**

Import `EncodedTwapDetails`, then add a literal test proving the optional object is a sibling of `twap`:

```python
async def test_twap_action_attaches_advanced_details(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = OutcomeTransport(
        {
            "status": "ok",
            "response": {
                "type": "twapOrder",
                "data": {"status": {"running": {"twapId": 1}}},
            },
        }
    )
    client = build_exchange(transport)
    monkeypatch.setattr(exchange_module, "time_ns", lambda: NONCE * 1_000_000)
    details = EncodedTwapDetails(
        s="65000",
        t={"a": False, "p": "63000"},
    )

    await client._submit_twap(TWAP, details=details)

    assert transport.requests[0]["action"] == {
        "type": "twapOrder",
        "twap": TWAP,
        "details": {"s": "65000", "t": {"a": False, "p": "63000"}},
    }
```

- [ ] **Step 2: Run the test and verify the red state**

Run:

```bash
uv run pytest -q tests/unit/test_actions.py::test_twap_action_attaches_advanced_details
```

Expected: collection or call failure because `EncodedTwapDetails` and the `details` parameter do not exist.

- [ ] **Step 3: Add exact wire types and conditional action assembly**

In `types/exchange.py`, add:

```python
class EncodedTwapTrigger(TypedDict):
    a: bool
    p: str


class EncodedTwapDetails(TypedDict):
    s: str | None
    t: EncodedTwapTrigger | None


class TwapOrderAction(TypedDict):
    type: Literal["twapOrder"]
    twap: EncodedTwapOrder
    details: NotRequired[EncodedTwapDetails]
```

Import `EncodedTwapDetails` in `exchange.py` and change `_submit_twap` to:

```python
async def _submit_twap(
    self,
    twap: EncodedTwapOrder,
    *,
    details: EncodedTwapDetails | None = None,
    expires_after: int | None = None,
) -> PlaceTwapResponse:
    action = TwapOrderAction(type="twapOrder", twap=twap)
    if details is not None:
        action["details"] = details
    return await self._submit_action(
        action, "twapOrder", expires_after=expires_after
    )
```

- [ ] **Step 4: Verify the action boundary is green**

Run:

```bash
uv run pytest -q tests/unit/test_actions.py
uv run ruff format src/async_hyperliquid/types/exchange.py src/async_hyperliquid/exchange.py tests/unit/test_actions.py
uv run ruff check src/async_hyperliquid/types/exchange.py src/async_hyperliquid/exchange.py tests/unit/test_actions.py
uv run ty check src/async_hyperliquid
uv run ty check tests/unit
```

Expected: all commands exit zero.

- [ ] **Step 5: Commit the exchange-boundary slice**

```bash
git add src/async_hyperliquid/types/exchange.py src/async_hyperliquid/exchange.py tests/unit/test_actions.py
git commit -m "feat: encode advanced TWAP details"
```

### Task 2: Add Public Advanced-Price Behavior

**Files:**
- Modify: `tests/unit/test_exchange.py`
- Modify: `tests/public_api/test_surface.py`
- Modify: `src/async_hyperliquid/client.py`

**Interfaces:**
- Consumes: `EncodedTwapDetails`, `_normalize_price`, `_wire_float`, `_MarketInfo`, and `InfoClient.mark_price(coin)`.
- Produces: `place_twap(..., *, reduce_only=False, randomize=False, trigger_px: float | None = None, stop_px: float | None = None, expires_after=None)`.

- [ ] **Step 1: Write failing combination and compatibility tests**

Extend `StubInfo` with literal mark-price state:

```python
self.mark_prices = {"BTC": 100_000.0, "ETH": 2_000.0}
self.mark_price_calls: list[str] = []

async def mark_price(self, coin: str) -> float:
    self.mark_price_calls.append(coin)
    return self.mark_prices[coin]
```

Add a parametrized test whose expected payloads are hand-derived:

```python
@pytest.mark.parametrize(
    ("trigger_px", "stop_px", "expected_details", "expected_mark_calls"),
    [
        (
            63_000.0,
            65_000.0,
            {"s": "65000", "t": {"a": False, "p": "63000"}},
            ["BTC"],
        ),
        (
            101_000.0,
            None,
            {"s": None, "t": {"a": True, "p": "101000"}},
            ["BTC"],
        ),
        (
            100_000.0,
            None,
            {"s": None, "t": {"a": False, "p": "100000"}},
            ["BTC"],
        ),
        (None, 99_000.0, {"s": "99000", "t": None}, []),
    ],
)
async def test_twap_advanced_prices_encode_exact_details(
    monkeypatch: pytest.MonkeyPatch,
    trigger_px: float | None,
    stop_px: float | None,
    expected_details: JsonObject,
    expected_mark_calls: list[str],
) -> None:
    transport = RecordingTransport(load_exchange_response("twap_order_running"))
    client = build_client(transport)
    monkeypatch.setattr(exchange_module, "time_ns", lambda: NONCE * 1_000_000)

    await client.place_twap(
        "BTC",
        True,
        0.01,
        5,
        trigger_px=trigger_px,
        stop_px=stop_px,
    )

    action = cast(JsonObject, transport.requests[0][1]["action"])
    assert action == {
        "type": "twapOrder",
        "twap": {"a": 0, "b": True, "s": "0.01", "r": False, "m": 5, "t": False},
        "details": expected_details,
    }
    assert cast(StubInfo, client._info).mark_price_calls == expected_mark_calls
```

In the existing no-options TWAP test, add these literal compatibility checks:

```python
action = cast(JsonObject, transport.requests[0][1]["action"])
assert "details" not in action
assert cast(StubInfo, client._info).mark_price_calls == []
```

In `tests/public_api/test_surface.py`, add a signature test proving the parameter order, keyword-only kind, names, and `None` defaults.

```python
def test_place_twap_exposes_optional_advanced_prices() -> None:
    parameters = signature(AsyncHyperliquid.place_twap).parameters

    assert tuple(parameters) == (
        "self",
        "coin",
        "is_buy",
        "size",
        "minutes",
        "reduce_only",
        "randomize",
        "trigger_px",
        "stop_px",
        "expires_after",
    )
    assert parameters["trigger_px"].kind is Parameter.KEYWORD_ONLY
    assert parameters["trigger_px"].default is None
    assert parameters["stop_px"].kind is Parameter.KEYWORD_ONLY
    assert parameters["stop_px"].default is None
```

- [ ] **Step 2: Run the behavioral tests and verify the red state**

Run:

```bash
uv run pytest -q tests/unit/test_exchange.py -k 'twap'
uv run pytest -q tests/public_api/test_surface.py -k 'twap'
```

Expected: failures because `place_twap` does not accept `trigger_px` or `stop_px` and exposes no encoded details.

- [ ] **Step 3: Write failing validation and mark-failure tests**

Add price-validation coverage that passes explicit typed values and asserts no external side effects:

```python
@pytest.mark.parametrize(
    ("trigger_px", "stop_px"),
    [
        (float("nan"), None),
        (-1.0, None),
        (0.01, None),
        (None, float("inf")),
        (None, -1.0),
        (None, 0.01),
    ],
)
async def test_twap_invalid_advanced_price_fails_before_signing(
    trigger_px: float | None,
    stop_px: float | None,
) -> None:
    transport = RecordingTransport(load_exchange_response("twap_order_running"))
    client = build_client(transport)

    with pytest.raises(ValueError):
        await client.place_twap(
            "BTC",
            True,
            0.01,
            5,
            trigger_px=trigger_px,
            stop_px=stop_px,
        )

    assert client.exchange._last_nonce == 0
    assert cast(StubInfo, client._info).mark_price_calls == []
    assert transport.requests == []
```

Add a mark lookup failure test:

```python
async def test_twap_mark_price_failure_prevents_signing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = RecordingTransport(load_exchange_response("twap_order_running"))
    client = build_client(transport)

    async def fail_mark_price(_coin: str) -> float:
        raise ProtocolError("mark unavailable")

    monkeypatch.setattr(client._info, "mark_price", fail_mark_price)

    with pytest.raises(ProtocolError, match="mark unavailable"):
        await client.place_twap("BTC", True, 0.01, 5, trigger_px=100_000.0)

    assert client.exchange._last_nonce == 0
    assert transport.requests == []
```

- [ ] **Step 4: Implement market-aware encoding and mark comparison**

Import `_normalize_price` and `EncodedTwapDetails`, then add the focused helper:

```python
def _encode_twap_price(value: float, market: _MarketInfo) -> str:
    max_decimals = (8 if market.is_spot else 6) - market.size_decimals
    normalized = _normalize_price(
        value,
        max_decimals=max_decimals,
        is_outcome=market.coin.startswith("#"),
    )
    return _wire_float(normalized)
```

Extend the public method signature after `randomize`:

```python
trigger_px: float | None = None,
stop_px: float | None = None,
```

After resolving `market` and validating size, build details before calling the exchange client:

```python
details: EncodedTwapDetails | None = None
if trigger_px is not None or stop_px is not None:
    encoded_trigger_px = (
        None if trigger_px is None else _encode_twap_price(trigger_px, market)
    )
    encoded_stop_px = None if stop_px is None else _encode_twap_price(stop_px, market)
    trigger = None
    if encoded_trigger_px is not None:
        mark_px = await self._info.mark_price(coin)
        trigger = {
            "a": float(encoded_trigger_px) > mark_px,
            "p": encoded_trigger_px,
        }
    details = EncodedTwapDetails(s=encoded_stop_px, t=trigger)
```

Pass `details=details` to `_submit_twap`. Preserve the existing `twap` object unchanged.

- [ ] **Step 5: Verify the public behavior is green**

Run:

```bash
uv run pytest -q tests/unit/test_exchange.py -k 'twap'
uv run pytest -q tests/public_api/test_surface.py -k 'twap'
uv run ruff format src/async_hyperliquid/client.py tests/unit/test_exchange.py tests/public_api/test_surface.py
uv run ruff check src/async_hyperliquid/client.py tests/unit/test_exchange.py tests/public_api/test_surface.py
uv run ty check src/async_hyperliquid
uv run ty check tests/public_api
uv run ty check tests/unit
```

Expected: all commands exit zero and the combination test shows explicit `null` members.

- [ ] **Step 6: Commit the intent-level slice**

```bash
git add src/async_hyperliquid/client.py tests/unit/test_exchange.py tests/public_api/test_surface.py
git commit -m "feat: add TWAP trigger and stop prices"
```

### Task 3: Document, Type-Check, and Run Complete Gates

**Files:**
- Modify: `tests/typing/test_types.py`
- Modify: `README.md`
- Modify: `CHANGELOG.md`
- Include: `docs/superpowers/plans/2026-08-05-twap-advanced-prices.md`

**Interfaces:**
- Consumes: the final `AsyncHyperliquid.place_twap` public signature.
- Produces: discoverable user documentation, release history, and complete CI-equivalent evidence.

- [ ] **Step 1: Add static API usage and user documentation**

In `tests/typing/test_types.py`, add:

```python
assert_type(
    await client.place_twap(
        "BTC",
        True,
        0.01,
        5,
        trigger_px=105_000.0,
        stop_px=95_000.0,
    ),
    PlaceTwapResponse,
)
```

Add this README subsection under root trading workflows:

````markdown
### TWAP advanced prices

`trigger_px` delays a TWAP until the market reaches its trigger; `stop_px`
stops it at the configured price. Either keyword may be supplied independently:

```python
result = await client.place_twap(
    "BTC",
    True,
    0.01,
    30,
    trigger_px=105_000.0,
    stop_px=95_000.0,
)
```

The client derives the protocol's trigger-direction flag from the current mark
price. Callers supply the price, not the wire-level flag.
````

Add this `Added` changelog bullet:

```markdown
- Add independently optional `trigger_px` and `stop_px` arguments to
  `place_twap`, with exact action-level `details` encoding and automatic
  trigger direction from the current mark price.
```

- [ ] **Step 2: Run focused tests and formatting**

```bash
uv run pytest -q tests/unit/test_actions.py tests/unit/test_exchange.py tests/public_api/test_surface.py
uv run ruff format src tests benchmarks
uv run ruff check src tests benchmarks
```

Expected: all tests pass; formatter and linter exit zero.

- [ ] **Step 3: Run every repository type-check shard sequentially**

```bash
uv run ty check src/async_hyperliquid
uv run ty check tests/contracts
uv run ty check tests/integration
uv run ty check tests/oracle
uv run ty check tests/package
uv run ty check tests/public_api
uv run ty check tests/typing
uv run ty check tests/unit
uv run ty check benchmarks
```

Expected: each separate process exits zero; no shard is skipped.

- [ ] **Step 4: Run the complete deterministic suite**

```bash
uv run pytest -q tests/unit tests/contracts tests/oracle tests/public_api tests/package
```

Expected: zero failures. Do not run credentialed `tests/integration/exchange`; the feature is covered at the literal signed-action boundary and the live suite can strand financial orders if interrupted.

- [ ] **Step 5: Inspect the final patch and commit documentation**

```bash
git diff --check
git status --short
git diff HEAD^ -- src/async_hyperliquid tests README.md CHANGELOG.md docs/superpowers/plans/2026-08-05-twap-advanced-prices.md
git add README.md CHANGELOG.md tests/typing/test_types.py docs/superpowers/plans/2026-08-05-twap-advanced-prices.md
git commit -m "docs: explain advanced TWAP prices"
```

Expected: the diff contains only TWAP advanced-price support, its tests, and its documentation.
