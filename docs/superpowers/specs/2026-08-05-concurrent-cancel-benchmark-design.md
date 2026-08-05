# Concurrent OID versus CLOID cancellation benchmark design

## Objective

Replace the published three-provider place/cancel comparison with a focused
`async-hyperliquid` benchmark that measures 20 simultaneous single-order
cancellation requests on Hyperliquid testnet: ten cancellations by exchange
order ID (OID) and ten cancellations by client order ID (CLOID).

The benchmark must retain the existing provider-comparison implementation as a
diagnostic tool. Only committed results, figures, README tables, and the
publication eligibility rules change.

## Non-goals

- Do not remove the `providers` or `all` CLI commands.
- Do not remove the SDK or CCXT adapters, dependencies, tests, or local signing
  benchmark.
- Do not claim exchange capacity or generalize one testnet run to production.
- Do not retry, omit, or replace failed measured cancellation requests.
- Do not submit any order to mainnet.

## Live workload

Each logical round performs the following operations:

1. Reserve weight 2 and fetch one BTC perpetual mid-price snapshot.
2. Build 20 unique ALO orders at approximately 11 USDC notional each:
   - ten buys at `mid * 0.90`;
   - ten sells at `mid * 1.10`;
   - every order has a unique valid CLOID.
3. Reserve weight 1 and place all 20 orders in one Exchange batch request.
4. Require exactly 20 `resting` statuses and retain every returned OID.
5. Partition the orders into two ten-order groups. Each group contains five
   buys and five sells. One group uses OID cancellation and the other uses
   CLOID cancellation; the concrete pair assignment swaps every logical round.
6. Reserve weight 20 once, create 20 single-order cancellation tasks, release
   them through a shared async start gate, and await all tasks.
7. Require an explicit successful response from every cancellation request.

The default publishable run remains three warmup rounds followed by 30 measured
rounds. It therefore places 660 testnet orders in total and records 600 measured
single-request cancellation samples: 300 OID and 300 CLOID.

## Concurrency and fairness

The runner creates all 20 tasks before opening a shared `asyncio.Event` gate.
Each task starts its own timer after the gate opens and immediately invokes one
public single-order cancel operation. This minimizes event-loop launch skew and
keeps signing, encoding, HTTP transport, response parsing, and strict response
validation inside the measured interval.

Task launch slots alternate OID and CLOID. The method assigned to the first slot
swaps every logical round. Order pairs also swap methods every logical round, so
each method receives the same buy/sell composition and the same launch-slot
distribution over a complete run.

The existing monotonic nonce generator is safe for this design: nonce
allocation occurs synchronously before each Exchange coroutine reaches its
first await, and the repository already verifies unique nonces when the clock
does not advance.

Each request sample retains the existing schema:

- suite: `cancel-id`;
- provider: `async-hyperliquid`;
- operation: `cancel_by_oid` or `cancel_by_cloid`;
- round index: `0..29` for measured rounds;
- provider order: the task launch slot `0..19`;
- duration: the individual request latency in nanoseconds.

For each method and measured round, reporting derives the maximum of its ten
individual request latencies. These 30 derived round-max values describe how
long the slowest request in each ten-request method group took without adding a
second persisted sample type or changing the report schema.

## Rate-limit control

The global pacer continues to reserve 250 ms per REST weight, or at most 240
weight/minute on average.

- mid snapshot: weight 2;
- one 20-order placement batch: `1 + floor(20 / 40) = 1`;
- 20 independent cancellation requests: weight 20, reserved before the burst.

One round therefore reserves 23 weight. After the cancellation burst, the next
request cannot start until the pacer has honored the five-second reservation.
The 33-round default run reserves 759 weight and has a theoretical pacing floor
of 189.75 seconds, excluding network time and initialization.

This controls the documented IP-weight budget but cannot override cumulative
address-based limits. Any rate-limit response invalidates the run.

## Failure handling and cleanup

The runner tracks all 20 placed orders by CLOID until their individual
cancellation receives an explicit success response.

All launched tasks are awaited, including when one or more tasks fail. Confirmed
successes are removed from the pending set. Any failed, timed-out, malformed, or
indeterminate request makes the round and report invalid. The recovery client
then submits a targeted CLOID batch cancellation for the remaining pending
orders after reserving its documented request weight.

No failed operation is retried as a measured sample. A failed recovery or
client close sets `cleanup_ok=false` and requires manual inspection of the
testnet subaccount before another run.

## Reporting and publication

The cancel chart and README report show two views:

1. all 300 individual request latencies per identifier, including median, MAD,
   p95, minimum, and maximum;
2. the 30 derived per-round maxima per identifier, including median and p95.

Publication accepts only a valid, cleanup-successful, clean-revision
`cancel-id` report with the exact default configuration and exactly 300 samples
for each operation. A diagnostic `providers` or `all` report remains runnable
but is not publishable.

The repository cleanup removes the existing
`benchmarks/results/20260805T112127Z/` directory because its report and CSV
contain provider-comparison data. The replacement published directory contains
only:

- sanitized `report.json`;
- `samples.csv` with the 600 cancellation samples;
- `cancel-id-latency.png`;
- `cancel-id-latency.svg`.

The detailed benchmark README and repository overall README remove every
published SDK/CCXT place/cancel value, ranking, provider chart, and provider
result table. They retain diagnostic command documentation and clearly state
that only the concurrent OID/CLOID run is publishable.

## Testing and validation

Implementation follows test-driven development and covers:

- construction of exactly ten buy and ten sell orders with unique CLOIDs;
- arbitrary-count resting-OID parsing with an exact expected count;
- one batch placement of 20 orders;
- creation of all tasks before the shared start gate opens;
- ten OID and ten CLOID single-order calls per round;
- balanced sides, pair assignment, and launch slots across rounds;
- one weight-20 reservation for the concurrent burst;
- unique concurrent nonces;
- waiting for every task and recovering only pending CLOIDs after failures;
- omission of warmup samples and exact 300/300 measured sample counts;
- derived round-max statistics and chart consistency;
- rejection of provider or non-default reports by publication;
- absence of provider results from both README marker blocks and replacement
  artifacts;
- credential and identifier sanitization.

Before publication, the implementation must pass the deterministic test suite,
Ruff, formatting, Ty, `git diff --check`, publishability validation, artifact
secret scanning, and visual inspection of the generated chart. The live run
must start from a clean committed revision and use a fresh output directory.

## Rollback

Code and publication changes are committed separately where practical. Revert
the publication commit to restore the prior README/artifact state. Revert the
implementation commit to restore the sequential two-order cancel workload.
Because the old result directory is removed only as part of the publication
commit, rollback does not require reconstructing generated files manually.
