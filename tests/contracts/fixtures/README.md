# Hyperliquid wire fixtures

These files freeze the raw JSON shapes used by the 0.5.1 client before the v1
type migration. They are intentionally JSON, not model instances.

The core order, cancel, mids, open-orders, fills, rate-limit, L2-book, candle,
metadata, account-state, funding, spot and staking examples come from the
official Hyperliquid Info and Exchange endpoint documentation as captured on
2026-07-29. Less common response fields are completed from the existing 0.5.1
wire `TypedDict` contracts. Empty collections and nullable values are retained
when the endpoint legitimately permits them.

- https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint
- https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint/perpetuals
- https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint/spot
- https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/exchange-endpoint

Fixtures are contract examples, not live test credentials or replayable signed
requests.
