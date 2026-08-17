# Spot Metadata-Native Symbols Design

## Goal

Remove SDK-owned Hyperliquid UI symbol aliases so spot market lookup and display
symbols are derived only from the runtime `spotMeta` response.

## Decision

`spotMeta.universe[].name` remains the canonical wire market name. The base and
quote token indexes resolve through `spotMeta.tokens`, and their `name` fields
form the only human-readable `BASE/QUOTE` alias. The SDK will not scrape or copy
the separate, curated display-name table embedded in the Hyperliquid frontend.

Consequently, metadata such as `UBTC` resolves as `UBTC/USDC`, not
`BTC/USDC`. Callers that need the frontend's curated label must maintain that
presentation concern outside protocol routing.

## Changes

- Delete `_SPOT_SYMBOL_ALIASES` and its lookup branch.
- Replace UI-alias tests with a regression proving an inferred alias such as
  `BTC/USDC` is rejected while `UBTC/USDC` resolves.
- Remove the UI-alias section from `docs/coin-name-mapping.md`.

## Validation

Run the focused metadata tests, the full non-live suite, Ruff formatting and
linting, and complete sequential `ty` shards for source and test roots.

## Related Finding: Spot Minimum Trade Size

Spot lot size is independently metadata-driven. A deployer fixes
`TokenSpec.szDecimals` during HIP-1 token registration. It is returned as
`spotMeta.tokens[].szDecimals` (and in the metadata half of
`spotMetaAndAssetCtxs`); the smallest positive size increment is
`10 ** -szDecimals` token units. This task records that result but does not add
a new public API or duplicate Exchange-side minimum-notional validation.
