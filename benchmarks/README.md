# Benchmarks

## Live Exchange benchmark

This benchmark submits real orders to Hyperliquid testnet. It compares
`async-hyperliquid` cancellation by order ID (OID) with cancellation by client
order ID (CLOID), then compares `async-hyperliquid`,
`hyperliquid-python-sdk==0.24.0`, and `ccxt==4.5.71` for batch placement and
batch cancellation. It never targets mainnet, but it does require a funded
testnet subaccount and should be treated as a live trading program.

Every logical workload uses the BTC perpetual and submits exactly two ALO
orders with unique CLOIDs:

- buy price: `mid * 0.90`;
- sell price: `mid * 1.10`;
- target notional: approximately 11 USDC for each order after exchange size
  rounding.

Both orders must return a `resting` status. A fill, rejection, malformed
response, rate-limit response, or unsuccessful cancellation invalidates the
whole run; measured failures are never retried or dropped.

### Safety prerequisites

Install the locked opt-in dependencies:

```bash
uv sync --frozen --group benchmark
```

Create `.env.local` in the repository root with testnet-only credentials:

```dotenv
IS_MAINNET=false
HL_ADDR=0x_master_account
HL_AK=0x_api_wallet
HL_SK=0x_api_wallet_private_key
HL_SUB=0x_execution_subaccount
```

`HL_SK` must derive `HL_AK`; the API wallet and subaccount must both belong to
`HL_ADDR`. The runner validates those roles before submitting an order. Do not
run another process with the same API-wallet key: Exchange nonces are local to
one client owner and concurrent submissions can make the run invalid. Verify
that the testnet subaccount has adequate available margin and no unrelated
open orders before starting.

The runner loads `.env.local` without overriding environment variables already
set by the shell. Credentials, addresses, OIDs, CLOIDs, signatures, request
bodies, and response bodies are excluded from every persisted artifact.

### Reproducible commands

Use a fresh output directory for every run. The default, publishable shape is
three untallied warmups followed by 30 measured rounds with 250 ms reserved per
REST weight:

```bash
uv run --frozen --group benchmark python benchmarks/live_exchange.py all \
  --output-dir /tmp/hl-live-default
```

The suites can also be run separately for diagnostics:

```bash
uv run --frozen --group benchmark python benchmarks/live_exchange.py cancel-id \
  --output-dir /tmp/hl-live-cancel-id

uv run --frozen --group benchmark python benchmarks/live_exchange.py providers \
  --output-dir /tmp/hl-live-providers
```

`--rounds`, `--warmups`, and `--interval-ms` may be changed for smoke runs;
`--interval-ms` cannot be lower than 250. Only a complete `all` report with
the exact defaults and locked library versions can update the committed
results.

### Rate-limit budget

Hyperliquid documents a 1,200 REST-weight/minute IP limit. An Exchange batch
containing two orders or two cancellations has weight
`1 + floor(batch_length / 40) = 1`. The global pacer reserves at least 250 ms
for every unit of request weight, limiting the controlled workload to 240
weight/minute, or 20% of the documented IP allowance. Market snapshots are
reserved at their documented weight as well. Metadata and role validation
happen before timing and use the remaining headroom; avoid any other traffic
from the same public IP while collecting a report. See the
[official rate-limit documentation](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/rate-limits-and-user-limits).

Address-based cumulative limits still apply. The benchmark does not claim
exchange capacity and cannot isolate other traffic sharing the IP, API wallet,
or execution account.

### Timing and fairness

A measured sample begins immediately before the provider's public batch method
and ends after encoding, signing, HTTP transport, response receipt, response
parsing, and strict success validation. Imports, client construction, metadata,
role checks, mid lookup, pacing sleep, recovery cleanup, report serialization,
and chart generation are outside the measured interval.

Provider order rotates every round. OID/CLOID cancellation order and the order
side assigned to each identifier alternate by round. All providers first build
an unsubmitted canonical probe and must produce identical wire orders. Each
real provider placement then receives a different pair of CLOIDs so one
provider can never cancel another provider's orders.

CCXT's default Hyperliquid initialization may submit builder/referrer setup
actions and attach builder parameters. After sandbox market initialization,
the adapter explicitly disables that initialization path and builder fee so
the measured Exchange action matches the other two providers exactly.

### Cleanup, artifacts, and publication

Each successful measured placement is cancelled immediately. If placement,
parsing, or measured cancellation fails, the recovery client attempts a
targeted batch cancellation using the two unique CLOIDs before the error is
propagated. An explicit successful cancel response is required. Any recovery
or client-close failure sets `cleanup_ok=false`; inspect the testnet subaccount
manually before another run whenever the command exits nonzero.

A valid selected-suite run writes sanitized `report.json`, `samples.csv`, and
the applicable PNG/SVG figures. An invalid run writes
`report.invalid.json`, preserves already collected safe samples, and does not
publish figures or CSV as a successful result. Exit status zero means all
selected suites, cleanup, report, CSV, and figures completed.

After inspecting a default-shape `all` run, publish it explicitly:

```bash
uv run --frozen --group benchmark python benchmarks/live_exchange.py publish \
  --report /tmp/hl-live-default/report.json
```

Publication recomputes and validates the exact sample shape and summaries,
requires clean completion and pinned versions, copies JSON/CSV/PNG/SVG into
`benchmarks/results/<UTC timestamp>/`, then updates the detailed block below
and the overall block in the repository README from the same report.

<!-- live-exchange-benchmark:detail:start -->
## Published live Exchange benchmark

No validated live testnet result has been published yet. Simulated, partial,
non-default, cleanup-failed, and locally edited reports are not eligible for
this section.
<!-- live-exchange-benchmark:detail:end -->

## Signing benchmark

This benchmark compares Hyperliquid signing and order-payload construction in
three real Python implementations:

- the current `async-hyperliquid` checkout;
- `hyperliquid-python-sdk==0.24.0`;
- `ccxt==4.5.71`.

It is a local CPU benchmark. It does not measure imports, client startup,
metadata loading, HTTP latency, or exchange throughput. Do not use its results
to predict end-to-end order latency.

## Safety and parity gate

The runner uses a committed public test key and a fixed testnet nonce. It does
not read `.env.local`, use production credentials, or make network requests.
CCXT receives an in-memory market description, so it does not fetch markets.
The benchmark dependency group pins `coincurve==21.0.0`. Before constructing
the CCXT probes, the runner directly exercises CCXT's CoinCurve secp256k1
signer; an unavailable or unusable backend fails the run instead of silently
benchmarking CCXT's cryptography fallback.

Before timing a provider, the runner requires its action hash, one-order
signature, ten-order signature, and payload action/signature to match the
committed vectors. A mismatch stops the run instead of publishing incomparable
timings. Exact full-envelope parity between async-hyperliquid and the official
SDK is covered separately by `tests/oracle/test_signing.py`.

## Locked environment

The repository pins Python 3.12 in `.python-version` and locks all benchmark
dependencies in `uv.lock`. From the repository root, create or refresh the
environment without changing the lockfile:

```bash
uv sync --frozen --group benchmark
```

The first sync may download packages. The benchmark itself runs offline after
the environment exists. Keep `uv.lock` unchanged when comparing results across
commits.

For a meaningful comparison, use the same machine and power mode, connect AC
power, close CPU-intensive programs, and let the machine reach a stable
temperature. Record the environment alongside the JSON result. On macOS:

```bash
uname -a
sysctl -n machdep.cpu.brand_string
uv run --frozen python --version
git rev-parse HEAD
```

On Linux, replace the `sysctl` command with `lscpu`.

## Reproducible run

Run the benchmark from the repository root and save the machine-readable
report outside the worktree:

```bash
uv run --frozen --group benchmark python benchmarks/signing.py \
  --rounds 7 \
  --warmups 1 \
  --iterations 5000 \
  --output /tmp/async-hyperliquid-signing-benchmark.json
```

Omit `--output` to print the report. Exit status zero means all parity gates
and measurements completed; any provider failure makes the command fail.

### CLI options

| Option | Default | Meaning |
|---|---:|---|
| `--rounds` | `7` | Measured child-process samples per provider. Provider order rotates each round. |
| `--warmups` | `1` | Untallied full provider runs before measured rounds. |
| `--iterations` | `5000` | Baseline inner-loop count. See the operation table for scaling. |
| `--output` | stdout | Optional path for the final JSON report. |

`--provider` is an internal child-process option and is not part of the manual
benchmark interface.

## Measured operations

| JSON key | Work measured | Inner iterations for baseline `N` |
|---|---|---:|
| `action_hash` | MessagePack action encoding and action hash | `N` |
| `sign_l1_single` | L1 signature for one encoded order | `max(100, N / 10)` |
| `sign_l1_batch_10` | L1 signature for ten encoded orders | `max(100, N / 10)` |
| `build_payload_single` | Native order encoding, action construction, and signing | `max(100, N / 10)` |
| `build_payload_batch_10` | Native encoding of ten orders, one action, and one signature | `max(100, N / 20)` |

The divisions use integer floor division. Each operation also performs an
untimed in-process warmup of `max(10, inner_iterations / 100)` calls. The
runner then collects garbage, disables the garbage collector for the timed
loop, and restores it afterward.

Each provider runs in its own child process. Imports, provider initialization,
parity validation, subprocess startup, and JSON serialization occur outside
the timed loops. Rotating provider order reduces systematic thermal and
scheduler bias.

## Reading the report

For every operation and provider, the JSON contains:

- `median_ns`: median of the per-round nanoseconds-per-operation samples;
- `mad_ns`: median absolute deviation, used as a noise indicator;
- `p95_ns`: nearest-rank 95th percentile across rounds;
- `ops_per_second`: `1_000_000_000 / median_ns`.

Use `median_ns` for the primary comparison. A large MAD or a p95 far above the
median means the machine was noisy; stabilize it and repeat the whole command.
For a performance claim, collect at least three complete reports on the same
machine and compare all three, not only the best run. Results from different
machines, Python patch releases, dependency locks, power modes, or thermal
states are not directly comparable.

## Local reference results

These results were collected on 2026-08-04 from the current 1.0.0rc1 worktree.
They are a reference for this machine, not a universal performance claim.

| Environment | Value |
|---|---|
| Machine | MacBook Air (Mac17,3), Apple M5, 10 cores, 24 GB memory |
| OS | macOS 26.5.2, arm64 |
| Python | CPython 3.12.13 |
| async-hyperliquid | 1.0.0rc1 |
| Official SDK | hyperliquid-python-sdk 0.24.0 |
| CCXT | 4.5.71 |
| Signing backend | CoinCurve 21.0.0; CCXT direct backend preflight enabled |
| Base revision | `7b9f6de1d0c95d5489fbc4123c5829020c54a97d` plus the documented RC1 worktree changes |
| Run shape | 3 independent reports; each has 1 warmup and 7 measured rounds with `--iterations 5000` |

For each cell below, the displayed median, MAD, and p95 are the median of that
field across the three complete reports. Throughput is derived from the
displayed aggregate median. `vs SDK` is the official SDK aggregate median
divided by the provider aggregate median, so higher is better.

| Operation | Library | Median (us) | MAD (us) | p95 (us) | Throughput (ops/s) | vs SDK |
|---|---|---:|---:|---:|---:|---:|
| `action_hash` | async-hyperliquid | 2.93 | 0.08 | 3.14 | 341,705 | 1.015x |
| `action_hash` | Official SDK | 2.97 | 0.09 | 3.24 | 336,592 | 1.000x |
| `action_hash` | CCXT | 176.83 | 2.58 | 189.03 | 5,655 | 0.0168x |
| `sign_l1_single` | async-hyperliquid | 73.72 | 2.75 | 78.30 | 13,564 | 1.642x |
| `sign_l1_single` | Official SDK | 121.04 | 1.41 | 133.34 | 8,262 | 1.000x |
| `sign_l1_single` | CCXT | 1,748.71 | 10.75 | 1,892.10 | 572 | 0.0692x |
| `sign_l1_batch_10` | async-hyperliquid | 77.31 | 3.31 | 83.71 | 12,935 | 1.602x |
| `sign_l1_batch_10` | Official SDK | 123.87 | 2.31 | 135.43 | 8,073 | 1.000x |
| `sign_l1_batch_10` | CCXT | 2,288.07 | 64.63 | 2,425.93 | 437 | 0.0541x |
| `build_payload_single` | async-hyperliquid | 74.25 | 2.19 | 82.19 | 13,467 | 1.662x |
| `build_payload_single` | Official SDK | 123.38 | 0.92 | 135.27 | 8,105 | 1.000x |
| `build_payload_single` | CCXT | 1,751.98 | 53.14 | 1,877.09 | 571 | 0.0704x |
| `build_payload_batch_10` | async-hyperliquid | 88.87 | 1.37 | 97.80 | 11,252 | 1.497x |
| `build_payload_batch_10` | Official SDK | 133.00 | 2.69 | 145.23 | 7,519 | 1.000x |
| `build_payload_batch_10` | CCXT | 2,409.28 | 57.05 | 2,567.24 | 415 | 0.0552x |

### Overall comparison

The overall score gives each of the five operations equal weight. It is the
geometric mean of their aggregate throughputs:

| Library | Geometric-mean throughput | Relative to SDK | Relative to fastest |
|---|---:|---:|---:|
| async-hyperliquid | 24,641 ops/s | 1.460x | 100.0% |
| Official SDK | 16,874 ops/s | 1.000x | 68.5% |
| CCXT | 803 ops/s | 0.0476x | 3.3% |

The geometric mean prevents the much faster `action_hash` workload from
dominating the result merely because it has a larger absolute ops/s value. The
same five workloads, versions, and weighting must be used for comparisons.

## Correctness verification

The benchmark's fixed public vector protects timing comparability. The
repository oracle additionally verifies exact official-SDK request envelopes,
including locally configured master/API-wallet and subaccount combinations
when `.env.local` is available:

```bash
uv run --frozen pytest -q tests/oracle/test_signing.py
```

This test constructs payloads locally and does not submit Exchange requests.
Missing local credentials skip only the credential-specific cases.

## Updating the benchmark

Treat implementation versions, committed vectors, payload construction, and
the benchmark as one contract:

1. update the opt-in dependency group and `uv.lock` together;
2. update or add parity tests before accepting a new vector;
3. run the oracle and a low-iteration smoke benchmark;
4. run the full command above and retain the raw JSON with the environment and
   commit identifier;
5. reject all timing data if a parity gate fails.

## Client hot-path benchmark

`benchmarks/hotpath.py` compares two built wheels with alternating AB/BA rounds.
It covers order preparation and signing without metadata or HTTP latency:

```bash
uv run python benchmarks/hotpath.py \
  --baseline-wheel /path/to/base.whl \
  --candidate-wheel dist/async_hyperliquid-1.0.0rc1-py3-none-any.whl \
  --baseline-api v1
```

Both wheels run in isolated extraction directories. The probe inspects the
private encoding signature once before timing so pre- and post-market-context
RC1 wheels remain comparable without putting reflection inside the hot loop.

Benchmarks belong in `benchmarks/`; production client code belongs in
`src/async_hyperliquid/`.
