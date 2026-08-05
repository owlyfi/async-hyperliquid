# TWAP Advanced Prices Integration Test Design

## Goal

Add a credentialed Hyperliquid testnet integration test that proves the three
advanced TWAP payload combinations are sent by the real client and accepted by
the real Exchange endpoint:

1. trigger and stop together;
2. trigger only, with `details.s` encoded as JSON null;
3. stop only, with `details.t` encoded as JSON null.

The exact wire mapping remains covered by deterministic unit tests. The new
integration test closes the remaining boundary: the captured action is the one
actually sent to testnet and the server returns a running TWAP id.

## Test Shape

Add one parameterized test to `tests/integration/exchange/test_orders.py`. Each
parameter case performs one signed testnet action and owns its cleanup. Keeping
the combinations in one test body prevents three copies of security-sensitive
capture and cleanup logic.

The parameter table contains booleans describing whether trigger and stop are
present. For each case, the test:

1. obtains the current BTC mark price;
2. chooses an integer trigger about 5% below mark when requested;
3. chooses an integer stop about 5% above mark when requested;
4. places a five-minute BTC TWAP with the existing 120 USDC test notional;
5. verifies the captured action's nullable members and trigger direction;
6. verifies testnet returned an integer `twapId`;
7. cancels the TWAP and closes any BTC position in nested `finally` blocks.

A below-mark trigger should remain dormant during a normal short test run and
must encode `a=false`. A stop-only TWAP starts immediately and may produce a
small fill before cancellation, which is why every case closes the position.

## Real Transport Capture

Use pytest's function-scoped `monkeypatch` fixture to wrap the session-scoped
client transport's bound `post_json` method. The wrapper forwards every request
to the original method, preserving a real network integration, and copies only
the `action` object when `action.type == "twapOrder"`.

The capture must not retain or print the envelope, signature, nonce, account
address, private key, or environment variables. Assertions operate only on the
non-secret action fields. Pytest restores the original transport method after
each parameter case.

The test asserts exactly one captured TWAP action. It checks:

- the signed `details` map preserves insertion order `t, s`;
- `details.s` equals the requested stop wire string or is `None`;
- `details.t` equals `None` when trigger is absent;
- when trigger exists, `details.t.p` equals the requested trigger wire string
  and `details.t.a is False`, with trigger insertion order `p, a`.

These assertions ensure the live success cannot be satisfied by silently
falling back to an ordinary TWAP without `details`.

## Failure and Cleanup Semantics

The response is parsed into `twap_id` immediately after the signed call, before
payload assertions, so later assertion failures still cancel the known TWAP.
Cancellation is attempted whenever an id was obtained. Position closing runs
even if cancellation raises, matching the existing nested cleanup style.

The Exchange cancel response may report that a TWAP already completed; the
cleanup call itself is still awaited, and position cleanup remains mandatory.
No broad account cleanup or cancellation of unrelated orders is allowed.

## Validation

Static validation runs Ruff and the `tests/integration` ty shard. Deterministic
tests continue to cover all action bytes without credentials. When testnet
credentials and network access are available, run only the new parameterized
test first, then the Exchange integration suite only if explicitly needed.

The live command remains guarded by the repository's existing
`IS_MAINNET=false` and credential/role validation. It must never run against
mainnet.
