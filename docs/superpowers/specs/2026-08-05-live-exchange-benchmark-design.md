# Live Exchange Benchmark Design

## Goal

Add two reproducible Hyperliquid testnet benchmarks:

1. compare async-hyperliquid order cancellation by exchange OID and client
   order ID (CLOID); and
2. compare warmed end-to-end two-order placement and cancellation across
   async-hyperliquid, `hyperliquid-python-sdk==0.24.0`, and `ccxt==4.5.71`.

Both benchmarks must control their request rate, reject incomparable samples,
clean up every potentially resting order, generate machine-readable results
and charts, and publish validated results into the benchmark and repository
READMEs.

## Scope and non-goals

The benchmark measures live testnet latency. It is deliberately separate from
the existing local signing benchmark.

Measured latency includes everything inside each library's warmed public order
method:

- request validation and normalization;
- order encoding and signing;
- HTTP request and response latency; and
- response parsing performed before the public method returns.

The timer excludes:

- imports and client construction;
- authentication and role preflight;
- market metadata loading;
- mid-price retrieval;
- rate-limit waiting;
- report serialization and chart rendering; and
- cleanup requests after a failed or indeterminate sample.

The benchmark does not measure maximum exchange throughput, concurrent order
submission, websocket performance, mainnet behavior, or market-order fill
latency. It must not make any mainnet Exchange request.

## Confirmed workload

Every placement submits one two-order BTC perpetual batch:

- one ALO buy at the current mid price multiplied by `0.90`;
- one ALO sell at the current mid price multiplied by `1.10`;
- approximately 11 USDC notional per order;
- `reduceOnly=false`; and
- a unique 128-bit CLOID on each order.

The runner retrieves one current BTC mid price before each logical round. That
mid is shared by all providers in the round. It calculates canonical wire
prices using Hyperliquid's five-significant-figure and perpetual-decimal rules.
It rounds each size upward to the market's size precision so the resulting
notional is at least 10 USDC and close to the 11 USDC target. Before the first
live action, the runner requires all three adapters to construct the same two
canonical orders.

The 10% distance on each side keeps the ALO orders away from the spread while
remaining inside Hyperliquid's 80%-from-reference price bound. A placement is
valid only when both statuses are successful `resting` results with integer
OIDs. A filled, rejected, or otherwise non-resting status invalidates the run.

## Credentials and network safety

The runner uses the repository's existing testnet credential contract:

- `HL_ADDR`: master account address;
- `HL_AK`: API wallet address;
- `HL_SK`: API wallet signing key;
- `HL_SUB`: execution subaccount address; and
- `IS_MAINNET=false`: explicit testnet guard.

It may load these variables from the process environment and `.env.local` but
must never write their values to a result, exception, log message, plot, or
README.

Preflight fails before placing an order unless all of the following hold:

1. `IS_MAINNET`, after whitespace and case normalization, is exactly `false`;
2. `HL_SK` is a valid 32-byte private key whose derived address is `HL_AK`;
3. `HL_ADDR`, `HL_AK`, and `HL_SUB` are valid Ethereum addresses;
4. the API wallet role belongs to `HL_ADDR`;
5. the subaccount role belongs to `HL_ADDR`;
6. every adapter is configured with a Hyperliquid testnet base URL; and
7. every placement and cancellation targets `HL_SUB` as its vault/subaccount.

The current worktree does not contain `.env.local`. Implementation and offline
validation can complete without credentials, but real measurements and README
result publication require the user to supply the testnet variables.

## Rate-limit model

The rate-control policy is based on the official Hyperliquid documentation:

<https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/rate-limits-and-user-limits>

The relevant rules are:

- one IP receives 1200 aggregate REST weight per minute;
- an Exchange action has weight `1 + floor(batch_length / 40)`;
- a batch of two orders or two cancels therefore has IP weight 1;
- address limits count a batch of `n` orders or cancels as `n` actions;
- an address begins with a 10,000-request buffer plus volume-derived capacity;
  and
- cancels receive a larger cumulative address allowance.

The runner uses one shared start-time scheduler for controlled REST calls. The
minimum reservation is 250 ms per weight unit, which caps benchmark-generated
traffic at 4 weight/second or 240 weight/minute, 20% of the documented IP
limit. Waiting occurs before the timer starts. A weight-2 mid-price request
reserves 500 ms. Metadata initialization happens before measurement, is
reported separately, and is never interleaved with measured Exchange calls.

The default run has three live warmup rounds and 30 measured rounds per suite.
Including warmups:

- the cancellation-identifier suite uses 99 Exchange IP weight and 132
  address actions; and
- the provider suite uses 198 Exchange IP weight and 396 address actions.

Mid-price and initialization requests add REST weight but leave substantial
headroom below 1200 weight/minute. The manual must instruct the operator to
stop other Hyperliquid clients sharing the same IP during a run. The runner
cannot observe traffic generated by unrelated processes.

The scheduler accepts slower intervals but rejects any configured interval
below 250 ms per weight. There is no option that silently disables the
testnet or minimum-spacing guard.

## Architecture

Use a single CLI and a small shared package:

```text
benchmarks/live_exchange.py       CLI: cancel-id, providers, all, publish
benchmarks/live/
  __init__.py                     Package boundary
  models.py                       Config, sample, summary, and report types
  pacing.py                       Weighted request-start scheduler
  workload.py                     Mid, price, size, CLOID, and response rules
  providers.py                    Three public-API provider adapters
  runner.py                       Warmup/measured rotation and cleanup ownership
  reporting.py                    Statistics, JSON/CSV, plots, README rendering
tests/unit/test_live_benchmark_*.py
                                  Offline behavioral coverage
```

Files may be combined only when their resulting responsibilities remain clear
and no non-generated source file approaches the repository's oversized-file
threshold. Production client behavior remains unchanged; benchmark-specific
abstractions stay under `benchmarks/`.

### Provider interface

Each adapter exposes the same conceptual operations:

- initialize and preload BTC perpetual metadata;
- construct the canonical two-order batch without submitting it;
- place the canonical two-order batch and return two resting OIDs;
- cancel two orders by OID in one public batch call;
- cancel selected orders by CLOID for recovery; and
- close owned HTTP resources.

The async-hyperliquid adapter calls `place_orders`, `cancel_orders`, and
`cancel_orders_by_cloid`. The official SDK adapter calls `bulk_orders`,
`bulk_cancel`, and `bulk_cancel_by_cloid`. The CCXT adapter calls
`create_orders` and `cancel_orders` with `vaultAddress=HL_SUB`, using CLOID
cancellation through its documented `clientOrderId` parameter for recovery.

Official SDK and CCXT methods are synchronous. They execute directly in the
otherwise sequential runner so thread-pool scheduling does not pollute their
measurements. No benchmark operation is concurrent.

## Suite 1: OID versus CLOID cancellation

This suite uses async-hyperliquid only.

For each logical round:

1. retrieve the current mid outside the measured interval;
2. place the two canonical orders in one unmeasured batch;
3. require both orders to be resting;
4. cancel one order through `cancel_order(CancelOrder(...))`;
5. cancel the other through `cancel_by_cloid(CancelByCloid(...))`; and
6. require each cancellation to return exactly one successful status.

Even rounds use OID for the buy first and CLOID for the sell second. Odd rounds
use CLOID for the buy first and OID for the sell second. This balances both
side and first/second-request effects. Placement latency may be retained as
diagnostic data but is not part of the OID/CLOID conclusion.

## Suite 2: Three-provider place and cancel

For each logical round, calculate one canonical order pair and run all three
providers. Provider order rotates cyclically across rounds.

For each provider:

1. reserve one scheduler weight unit;
2. time the provider's public two-order placement method;
3. require two successful resting results and extract both OIDs;
4. reserve another scheduler weight unit;
5. time the provider's public two-OID batch cancellation method; and
6. require two successful cancel statuses.

This suite reports `place_batch_2` and `cancel_batch_2_by_oid` independently.
The overall provider score gives them equal weight by using the geometric mean
of their median latencies. Separate place and cancel tables remain the primary
evidence so the combined score cannot hide an operation-specific regression.

## Failure, retry, and cleanup semantics

Only explicitly successful operations enter the result set. The following
events invalidate and stop a run:

- HTTP 429 or an address-based rate-limit response;
- timeout, connection loss, or an indeterminate action exception;
- an error response from Hyperliquid or a provider wrapper;
- a placement status that is filled, rejected, or not resting;
- a cancel status other than explicit success;
- adapter disagreement about the canonical order batch; or
- inability to confirm cleanup.

The benchmark never retries a measured operation and then treats the retry as
the original sample. It never drops failed samples and continues toward a
nominal sample count, because either behavior would bias the latency result.

The runner tracks potentially open orders by CLOID. After each confirmed
cancel it removes the corresponding CLOID from the pending set. A `finally`
block uses a dedicated async-hyperliquid recovery client to cancel only the
remaining CLOIDs, with normal rate scheduling. Ambiguous placements add both
CLOIDs to the pending set before submission so cleanup remains conservative.
The recovery path may check order status where needed, but those requests are
outside measured timing.

Cleanup failure is a terminal safety error. The CLI prints a value-free
message identifying the provider, suite, round, and operation, not an address,
OID, CLOID, signature, request body, or raw response.

## Results and statistics

Use `time.perf_counter_ns()` around each warmed public method. For each
operation/provider combination, report:

- measured sample count;
- median latency;
- median absolute deviation (MAD);
- nearest-rank p95;
- minimum; and
- maximum.

Network benchmarks do not report paced operations per second: the enforced
sleep would make that number a property of the safety policy rather than of a
library. Relative comparisons state which implementation is faster and divide
the slower median by the faster median. Provider comparisons also report a
clearly labelled SDK-relative median ratio.

Every run writes a sanitized JSON report, including:

- `valid` and any value-free invalidation reason;
- UTC start and completion times;
- git revision and dirty-state flag;
- OS, architecture, Python version, and dependency versions;
- network, coin, price multipliers, target notional, rounds, warmups, and
  scheduler interval;
- provider execution order by round; and
- latency samples and summaries.

It must not contain environment-variable values, account addresses, keys,
signatures, nonces, OIDs, CLOIDs, raw requests, or raw responses. A flattened
CSV contains the safe sample fields needed for independent analysis.

Matplotlib is an opt-in benchmark dependency. Each suite generates PNG and SVG
figures with two panels:

1. the full measured latency distribution with individual samples; and
2. median and p95 comparisons with values labelled.

The provider figure separates place and cancel rather than combining unlike
operations on one axis.

## CLI and artifact lifecycle

The public CLI supports:

```bash
uv run --frozen --group benchmark python benchmarks/live_exchange.py \
  cancel-id --output-dir /tmp/hl-cancel-id

uv run --frozen --group benchmark python benchmarks/live_exchange.py \
  providers --output-dir /tmp/hl-providers

uv run --frozen --group benchmark python benchmarks/live_exchange.py \
  all --output-dir /tmp/hl-live

uv run --frozen --group benchmark python benchmarks/live_exchange.py \
  publish --report /tmp/hl-live/report.json
```

Benchmark commands default to three warmup and 30 measured rounds. Operators
may request more rounds, fewer warmups, or a slower interval. The `all`
subcommand runs both suites into one report while keeping their warmup and
measured samples separate.

An invalid run writes a diagnostic `report.invalid.json` and exits nonzero. It
does not generate comparison figures or publish documentation. A valid run
writes JSON, CSV, PNG, and SVG in the requested output directory.

`publish` is a separate explicit operation. It accepts only a valid complete
report with exactly 30 measured rounds, three warmups, the confirmed workload,
the required providers and versions, and no failed cleanup. It copies the
sanitized report, CSV, and figures into:

```text
benchmarks/results/<UTC timestamp>/
```

It then updates marker-delimited generated sections in both READMEs. A publish
failure leaves the existing documented result intact.

## Documentation contract

`benchmarks/README.md` contains the detailed published report:

- exact environment and dependency versions;
- testnet account model without addresses;
- workload and rate-limit calculations;
- methodology and validity gates;
- OID/CLOID full statistics and figure;
- per-provider place/cancel statistics and figure;
- combined equal-weight provider score;
- links to sanitized JSON and CSV; and
- limitations, including shared-IP traffic and changing testnet conditions.

The repository `README.md` contains only an overall report:

- the faster cancellation identifier and slower/faster median ratio;
- provider place and cancel median/p95 ranking;
- the combined provider ranking; and
- a link to the detailed benchmark report.

Both generated sections use stable HTML comment markers. They are rendered
from the same validated JSON report so numbers cannot diverge through manual
copying. Simulated, unit-test, partial, invalid, or non-default-shape reports
cannot update either README.

## Testing and validation

All normal tests remain offline. Focused unit tests use fake providers and a
fake monotonic clock to cover:

- weighted 250 ms pacing and rejection of faster configuration;
- provider-order rotation;
- OID/CLOID first/second and buy/sell balancing;
- canonical BTC price and size calculation;
- exact adapter order semantics;
- resting OID and cancel-success parsing;
- filled, error, 429, timeout, and indeterminate failure closure;
- pending-CLOID ownership and cleanup;
- invalid-run persistence and nonzero exit behavior;
- secret and identifier absence from JSON/CSV/log output;
- robust statistics;
- deterministic plot inputs; and
- marker-delimited detailed and overall README rendering.

Integration-style adapter tests replace transports and call the real library
public APIs without network access. A low-round live smoke run is permitted
only through the explicit CLI with valid testnet credentials; it cannot be
collected by the default pytest command.

After Python changes, validation follows the repository's uv workflow:

1. Ruff formatting and linting;
2. focused benchmark unit tests;
3. the complete default offline test scope;
4. sequential Ty shards covering all configured Python roots; and
5. a CLI help/offline preflight smoke check.

When credentials are available, final publication additionally requires one
fresh default-shape `all` run, inspection of its valid JSON and figures, and a
successful `publish` command. No real result is fabricated when credentials
are absent.

## Rollback and operational impact

The feature is isolated to optional benchmark dependencies, benchmark code,
tests, generated result artifacts, and documentation. It does not change the
runtime package API or production order path. Rollback consists of removing
those benchmark additions and restoring the two generated README marker
sections. Any orders left by an interrupted process remain discoverable by
their unique CLOIDs; the manual includes the targeted recovery command and
warns operators to verify the subaccount has no benchmark orders before a new
run.
