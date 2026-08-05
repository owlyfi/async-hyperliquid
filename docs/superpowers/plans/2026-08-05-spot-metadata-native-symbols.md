# Spot Metadata-Native Symbols Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove SDK-owned spot UI aliases and rely exclusively on `spotMeta` names while documenting the source of spot lot-size precision.

**Architecture:** Keep the existing immutable metadata snapshot and spot token-index resolution. Delete only the presentation-specific alias table and branch; retain canonical wire names and metadata-derived `BASE/QUOTE` aliases.

**Tech Stack:** Python 3.12, pytest, Ruff, ty, uv

## Global Constraints

- Do not infer or scrape Hyperliquid frontend display aliases.
- Do not add local minimum-notional rejection; the Exchange owns that rule.
- Preserve canonical wire-name routing and metadata snapshot behavior.

---

### Task 1: Remove frontend aliases

**Files:**
- Modify: `tests/unit/test_metadata.py`
- Modify: `src/async_hyperliquid/_internal/metadata.py`
- Modify: `docs/coin-name-mapping.md`

**Interfaces:**
- Consumes: `spotMeta.tokens[].name`, `spotMeta.universe[].name`, and token indexes.
- Produces: unchanged `InfoClient.coin_name`, `coin_symbol`, `token_id`, and `spot_token_metadata` methods with metadata-only resolution.

- [ ] **Step 1: Write the failing regression test**

Replace the UI-alias parameterization and collision-precedence test with:

```python
async def test_spot_aliases_are_derived_only_from_metadata() -> None:
    transport = MetadataTransport()
    base = cast(JsonObject, cast(list[JsonValue], transport.spot_meta["tokens"])[1])
    base["name"] = "UBTC"
    pair = cast(JsonObject, cast(list[JsonValue], transport.spot_meta["universe"])[0])
    pair["name"] = "@142"
    info = build_info(transport)

    assert await info.coin_name("UBTC/USDC") == "@142"
    with pytest.raises(ValueError, match="unknown coin"):
        await info.coin_name("BTC/USDC")
```

- [ ] **Step 2: Run the focused test and verify RED**

Run: `uv run pytest -q tests/unit/test_metadata.py::test_spot_aliases_are_derived_only_from_metadata`

Expected: FAIL because the old `_SPOT_SYMBOL_ALIASES` still resolves `BTC/USDC`.

- [ ] **Step 3: Implement the minimal behavior change**

Delete `_SPOT_SYMBOL_ALIASES` and the conditional alias insertion in
`_index_spot_metadata`. Leave the metadata-derived `display_name` insertion
unchanged.

- [ ] **Step 4: Update documentation**

Delete the frontend alias table and collision-precedence text from
`docs/coin-name-mapping.md`, and state that display aliases come only from
token names in `spotMeta`.

- [ ] **Step 5: Verify focused and complete checks**

Run the focused metadata suite, full non-live tests, `ruff format`,
`ruff check`, and sequential `ty check` shards covering `src`, each top-level
test group, and benchmarks.

- [ ] **Step 6: Commit**

```bash
git add src/async_hyperliquid/_internal/metadata.py tests/unit/test_metadata.py docs/coin-name-mapping.md docs/superpowers/specs/2026-08-05-spot-metadata-native-symbols-design.md docs/superpowers/plans/2026-08-05-spot-metadata-native-symbols.md
git commit -m "fix: derive spot symbols from metadata"
```
