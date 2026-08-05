# TWAP Advanced Prices Design

## Goal

Add Hyperliquid's optional TWAP trigger-price and stop-price fields without
changing the request bytes produced by existing `place_twap` calls.

The public API adds two keyword-only arguments:

```python
trigger_px: float | None = None
stop_px: float | None = None
```

The response contract remains `PlaceTwapResponse`.

## Wire Contract

The optional fields belong in an action-level `details` object beside `twap`:

```json
{
  "type": "twapOrder",
  "twap": {"a": 3, "b": true, "s": "0.00311", "r": false, "m": 5, "t": false},
  "details": {
    "t": {"p": "63000", "a": false},
    "s": "65000"
  }
}
```

The four supported combinations are:

| `trigger_px` | `stop_px` | Wire representation |
|---|---|---|
| `None` | `None` | Omit `details` entirely |
| value | `None` | `details={"t": {"p": "...", "a": ...}, "s": null}` |
| `None` | value | `details={"t": null, "s": "..."}` |
| value | value | Encode both fields |

The explicit JSON `null` values are protocol-significant. Omitting a missing
member inside an existing `details` object is not equivalent.

Unlike ordinary JSON semantics, insertion order is also signature-significant:
the current official frontend passes the action maps directly to a MessagePack
encoder with key sorting disabled. The advanced object must therefore be built
as `details: t, s`, and its non-null trigger as `p, a`. The surrounding action
and `twap` map retain their historical construction order. Tests assert these
orders explicitly so refactoring cannot silently change the recovered signer.

## Encoding and Market Data

Both prices use the same market-aware normalization already used for order
prices:

- five significant figures;
- the venue's maximum decimal precision;
- existing outcome-market bounds where applicable;
- canonical wire strings without trailing zeroes.

Non-finite, non-positive, out-of-bounds, or below-precision prices fail before
signing and before posting the action.

When `trigger_px` is present, the client obtains the current mark price through
`InfoClient.mark_price(coin)`. It computes `details.t.a` from the final encoded
trigger price so that the boolean describes the price actually signed:

```python
a = float(encoded_trigger_px) > mark_price
```

Equality therefore produces `false`. A mark-price lookup or protocol parsing
failure propagates before signing. No mark-price request is made when only
`stop_px` is present or when advanced prices are absent.

## Components

`AsyncHyperliquid.place_twap` owns user-intent validation, market lookup,
price normalization, and mark-price comparison. It passes an encoded optional
details object to the info-independent `ExchangeClient`.

The exchange wire types gain:

- an encoded trigger-details shape containing `a` and `p`;
- an encoded TWAP-details shape containing nullable `s` and `t`;
- an optional `details` member on `TwapOrderAction`.

`ExchangeClient._submit_twap` conditionally adds `details`. It must omit the
key when no advanced price was requested, preserving the historical msgpack
payload and signature.

No response model changes are required because the server's successful
`twapOrder` response remains unchanged.

## Compatibility and Failure Behavior

The new parameters are keyword-only and default to `None`, so all existing
source calls remain valid. Existing calls also retain byte-for-byte action
compatibility because they omit `details`.

Validation and mark-price failures occur before nonce consumption, signing,
or transport calls. This keeps retry behavior aligned with existing local
TWAP validation failures.

## Tests

Implementation follows a red-green TDD cycle. Unit tests will assert literal
action payloads for:

1. trigger and stop together;
2. trigger only, including `s: null`;
3. stop only, including `t: null` and no mark-price lookup;
4. neither field, proving `details` remains absent;
5. trigger equal to mark price, proving `a` is `false`;
6. trigger above mark price, proving `a` is `true`;
7. invalid and below-precision prices failing before signing and transport.

Typing coverage will exercise the new keyword arguments. The existing TWAP
response fixtures and response-validation tests remain authoritative because
the response schema does not change. The changelog and public usage
documentation will describe the new optional arguments.
