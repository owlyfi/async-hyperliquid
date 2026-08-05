# Order Size and Spot Reduce-Only Validation Design

## Goal

Centralize order-size normalization, reject structurally invalid spot
reduce-only requests before signing, and keep minimum-notional policy owned by
the Hyperliquid Exchange.

## Size normalization

Add `_normalize_size(value, size_decimals)` beside `_normalize_price`. It must:

1. convert the input to `float`;
2. reject non-finite values and values less than or equal to zero;
3. round with `_round_size` using the market's `szDecimals`;
4. reject a rounded value less than or equal to zero with
   `order size is below market precision`;
5. return the normalized `float | int`.

`encode_order` and `place_twap` use this helper. `_round_size` remains a pure
rounding primitive.

## Spot reduce-only boundary

Reduce-only is a perpetual-position semantic and is invalid for spot and
outcome orders. `encode_order` rejects `is_spot=True` with `ro=True`, covering
limit, market-normalized, trigger, and modify requests. `place_twap` performs
the same venue-aware check because TWAP does not call `encode_order`.

The error is `spot orders cannot be reduce-only`. Validation happens after
metadata resolves the venue but before signing or HTTP submission.

## Minimum notional ownership

The SDK must not add a local `price * size >= 10` rule. Hyperliquid distinguishes
`MinTradeNtl` from quote-token-specific `MinTradeSpotNtl`, and permits perpetual
reduce-only orders below the normal minimum. These policy rules remain at the
Exchange boundary so server changes do not create SDK false rejections.

Tests pin that a sub-10-USDC perpetual reduce-only request and a sub-10 quote
spot non-reduce-only request still encode, while spot reduce-only fails locally.

## Validation

Use focused red/green tests for encoding and TWAP, then run Ruff, every CI `ty`
shard sequentially, and the deterministic CI pytest suite. Signed live Exchange
tests are not required because all new behavior is deterministic and must fail
before submission.
