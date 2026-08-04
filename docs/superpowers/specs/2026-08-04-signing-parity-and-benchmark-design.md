# Signing Parity and Benchmark Design

## Goal

Keep `1.0.0rc1` wire-compatible with `hyperliquid-python-sdk==0.24.0`, then
measure CCXT, the official SDK, and async-hyperliquid with identical signing
inputs before accepting any signing optimization.

## Payload contract

The official SDK is the oracle for the final `/exchange` request envelope.
For the same action, nonce, network, vault address, expiry, and private key,
async-hyperliquid must produce the same `action`, `nonce`, `signature`,
`vaultAddress`, and `expiresAfter` values. The two optional envelope fields are
present with JSON `null` when unset because that is the SDK's current wire
shape.

Parity covers:

- a single order and a ten-order batch;
- testnet source signing;
- no vault and a subaccount/vault target;
- no expiry and an explicit `expiresAfter` value;
- a committed, non-secret deterministic key vector;
- local master and API-wallet keys loaded from `.env.local`.

The `.env.local` oracle validates `HL_PK -> HL_ADDR`, `HL_SK -> HL_AK`, and
uses `HL_SUB` as the API-wallet vault. It never sends a request. Real private
keys, signatures, or payloads are neither printed nor persisted. A mismatch
raises a value-free error message.

## Benchmark contract

The benchmark has two lanes and excludes import time, process startup, client
initialization, metadata lookup, and network I/O.

The signing-only lane measures:

- action hashing;
- one-order L1 signing;
- ten-order L1 signing.

The full local construction lane measures:

- one normalized order through native order encoding, action construction,
  signing, and request-envelope construction;
- ten normalized orders through the same path.

Each provider probe validates its action and signature against the committed
safe vector before timing. A parity failure invalidates the run. CCXT's native
envelope may omit null optional fields, so its gate compares the exact action
and signature; SDK versus async-hyperliquid additionally compares the complete
envelope.

Providers run in rotating order in isolated child processes. The measured loop
runs inside each child, so interpreter startup is excluded. Reports contain
median, median absolute deviation, nearest-rank p95, and operations per second.

## Dependency policy

Use the real implementations:

- `hyperliquid-python-sdk==0.24.0` through the existing dev dependency range;
- `ccxt==4.5.71` in an exact, opt-in benchmark dependency group;
- the current async-hyperliquid source tree.

No CCXT signing code is copied into the repository.

## Optimization gate

Record and profile the unoptimized implementation first. Investigate EIP-712
encoding and secp256k1 signing separately. Retain a production change only if:

1. every deterministic and `.env.local` parity test remains exact;
2. the signing-only benchmark improves repeatably rather than within noise;
3. the implementation stays smaller and clearer than a generic signer layer;
4. user-signed actions and vault scoping remain unchanged.

If these conditions are not met, keep the existing signer and deliver the
benchmark evidence without speculative optimization.

## Non-goals

- No live Exchange request or Exchange integration-test collection.
- No Copycat changes.
- No version bump beyond `1.0.0rc1`.
- No wrapper abstraction shared across unrelated signing domains.
