# Live Exchange Benchmark Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build rate-controlled, testnet-only OID/CLOID and three-provider live order benchmarks with validated machine-readable reports, charts, and README publication.

**Architecture:** A `benchmarks.live` package owns canonical workload construction, weighted pacing, provider adapters, suite orchestration, and reporting. One CLI exposes `cancel-id`, `providers`, `all`, and `publish`; normal tests replace transports/providers and never contact Hyperliquid.

**Tech Stack:** Python 3.12, asyncio, aiohttp, async-hyperliquid, hyperliquid-python-sdk 0.24.0, CCXT 4.5.71, Matplotlib, pytest, uv, Ruff, Ty.

## Global Constraints

- Require `IS_MAINNET=false`; no code path may submit a mainnet Exchange action.
- Use `HL_SK` as the API-wallet signer and `HL_SUB` as the execution subaccount for all three providers.
- Use one BTC perpetual ALO buy at `mid * 0.90` and one ALO sell at `mid * 1.10`, approximately 11 USDC each.
- Default to three live warmup rounds and 30 measured rounds.
- Enforce at least 250 ms of request-start spacing per REST weight unit; slower overrides are allowed, faster overrides are rejected.
- Include warmed public-method encoding, signing, HTTP, and response parsing in timed intervals; exclude initialization, metadata, mid lookup, pacing, cleanup, plotting, and serialization.
- Admit only explicit two-order `resting` placements and explicit cancel `success` responses; do not retry or drop failed measured samples.
- Give every order a unique CLOID and clean all possibly open CLOIDs in `finally`.
- Never persist keys, addresses, signatures, nonces, OIDs, CLOIDs, raw requests, or raw responses.
- Publish detailed validated results to `benchmarks/README.md` and only an overall summary to `README.md`.
- Do not fabricate or publish live numbers when `.env.local` credentials are absent.
- Keep benchmark-only code out of `src/async_hyperliquid/`; production runtime behavior and public API remain unchanged.

---

### Task 1: Canonical Workload and Weighted Pacing

**Files:**
- Create: `benchmarks/live/__init__.py`
- Create: `benchmarks/live/models.py`
- Create: `benchmarks/live/pacing.py`
- Create: `benchmarks/live/workload.py`
- Create: `tests/unit/test_live_benchmark_core.py`

**Interfaces:**
- Produces: `BenchmarkConfig`, `CanonicalOrder`, `OrderPair`, `LatencySample`, `BenchmarkFailure`.
- Produces: `WeightedPacer.wait(weight: int = 1) -> Awaitable[None]`.
- Produces: `build_order_pair(mid: float, size_decimals: int, *, target_notional: float, cloids: tuple[str, str]) -> OrderPair`.
- Produces: `rotate_names(names: Sequence[str], round_index: int) -> tuple[str, ...]`.

- [ ] **Step 1: Write failing model, workload, and pacing tests**

```python
async def test_weighted_pacer_reserves_250_ms_per_weight() -> None:
    clock = FakeClock()
    pacer = WeightedPacer(interval_ns=250_000_000, clock_ns=clock.now, sleep=clock.sleep)
    await pacer.wait(weight=2)
    await pacer.wait(weight=1)
    assert clock.sleeps == [0.5]


def test_order_pair_uses_balanced_alo_prices_and_minimum_notional() -> None:
    pair = build_order_pair(
        100_000.0,
        5,
        target_notional=11.0,
        cloids=("0x" + "01" * 16, "0x" + "02" * 16),
    )
    assert (pair.buy.price, pair.sell.price) == (90_000.0, 110_000.0)
    assert pair.buy.size * pair.buy.price >= 10.0
    assert pair.sell.size * pair.sell.price >= 10.0
    assert pair.buy.tif == pair.sell.tif == "Alo"
```

- [ ] **Step 2: Run the core tests and verify RED**

Run:

```bash
UV_CACHE_DIR=/private/tmp/async-hyperliquid-uv-cache uv run --frozen pytest -q tests/unit/test_live_benchmark_core.py
```

Expected: collection fails because `benchmarks.live` does not exist.

- [ ] **Step 3: Implement immutable core models and canonical rounding**

Use frozen slotted dataclasses. `BenchmarkConfig.__post_init__` rejects rounds
below 1, warmups below 0, interval values below `250_000_000`, and non-positive
notional/multipliers. `build_order_pair` uses the package's existing
five-significant-figure price rounding and ceiling-to-size-decimals logic:

```python
units = math.ceil((target_notional / price) * 10**size_decimals)
size = units / 10**size_decimals
```

Construct exactly one buy and one sell with `reduce_only=False` and `tif="Alo"`.

- [ ] **Step 4: Implement deterministic weighted pacing**

The first reservation starts immediately. Later calls sleep until
`next_start_ns`; after a start, reserve `interval_ns * weight`. Reject bools,
zero, and negative weights.

- [ ] **Step 5: Run tests and verify GREEN**

Run the Task 1 test file; expect all tests to pass with no network access.

- [ ] **Step 6: Commit Task 1**

```bash
git add benchmarks/live tests/unit/test_live_benchmark_core.py
git commit -m "feat: add live benchmark workload core"
```

### Task 2: Response Gates, Statistics, and Safe Report Schema

**Files:**
- Modify: `benchmarks/live/models.py`
- Create: `benchmarks/live/results.py`
- Create: `tests/unit/test_live_benchmark_results.py`

**Interfaces:**
- Produces: `parse_resting_oids(response: object, *, provider: str) -> tuple[int, int]` for raw async/SDK envelopes.
- Produces: `parse_cancel_success(response: object, *, expected: int, provider: str) -> None`.
- Produces: `parse_ccxt_resting_oids(orders: object) -> tuple[int, int]` and `parse_ccxt_cancel_success(orders: object, *, expected: int) -> None`.
- Produces: `summarize_ns(samples: Sequence[int]) -> LatencySummary`.
- Produces: `build_report(...) -> LiveBenchmarkReport` and `assert_report_is_sanitized(report, forbidden_values) -> None`.
- Produces: `SampleRecorder.record(sample: LatencySample) -> None`, `SampleRecorder.samples`, and `SampleRecorder.build_report(*, valid: bool, failure_reason: str | None) -> LiveBenchmarkReport`.

- [ ] **Step 1: Write failing response-gate tests**

Cover exact two-resting success, filled, error, malformed status, bool-as-OID,
wrong status counts, CCXT parsed order IDs, and exact cancel-success counts:

```python
def test_filled_place_response_invalidates_the_run() -> None:
    response = {"status": "ok", "response": {"data": {"statuses": [{"filled": {"oid": 1}}, {"resting": {"oid": 2}}]}}}
    with pytest.raises(BenchmarkFailure, match="non-resting"):
        parse_resting_oids(response, provider="sdk")
```

- [ ] **Step 2: Run the response tests and verify RED**

Expected: imports fail because `benchmarks.live.results` is absent.

- [ ] **Step 3: Implement fail-closed response parsing and robust summaries**

`summarize_ns` returns `count`, `median_ns`, `mad_ns`, nearest-rank `p95_ns`,
`min_ns`, and `max_ns`. All latency values must be positive finite integers.
Response errors identify only provider and response class, never interpolate
the raw response.

- [ ] **Step 4: Write failing report-redaction tests**

Build a report with safe samples and assert JSON serialization succeeds. Pass
representative key/address/OID/CLOID strings as `forbidden_values` and require
the sanitizer to reject any occurrence in keys or string values.

- [ ] **Step 5: Implement the versioned safe report schema**

Store only suite, provider, operation, measured round index, provider order,
duration, validity, value-free failure reason, safe configuration, versions,
and environment. Do not put provider return values on any report type.

- [ ] **Step 6: Run tests and commit Task 2**

```bash
git add benchmarks/live/models.py benchmarks/live/results.py tests/unit/test_live_benchmark_results.py
git commit -m "feat: validate live benchmark results"
```

### Task 3: Testnet Preflight and Real Provider Adapters

**Files:**
- Create: `benchmarks/live/preflight.py`
- Create: `benchmarks/live/providers.py`
- Create: `tests/unit/test_live_benchmark_preflight.py`
- Create: `tests/unit/test_live_benchmark_providers.py`

**Interfaces:**
- Produces: `Credentials.from_environ(environ: Mapping[str, str]) -> Credentials`.
- Produces: `validate_roles(master_address: str, api_role: object, sub_role: object) -> None`.
- Produces: `LiveProvider` protocol with async `prepare`, `wire_orders`, `place`, `cancel_oids`, `cancel_cloids`, and `close` methods.
- Produces: `MarketSource.snapshot() -> Awaitable[tuple[float, int]]` for one mid price and BTC size-decimal value.
- Produces: `ProviderSet(measured: tuple[LiveProvider, ...], recovery: LiveProvider, mid_source: MarketSource)` with reverse-order async close ownership.
- Produces: `AsyncHyperliquidProvider`, `SdkProvider`, `CcxtProvider`, and `build_providers(credentials) -> Awaitable[ProviderSet]`.

- [ ] **Step 1: Write failing credential and role tests**

Test missing variables, values other than normalized `false`, key/address
mismatch, wrong API role owner, wrong subaccount owner, and value-free error
messages. Patch role results; never make a real info request.

- [ ] **Step 2: Implement strict testnet-only credential preflight**

Reuse the validation semantics in `tests/integration/config.py` without
importing test code. `Credentials` stores values only in memory and defines a
redacted `repr` that never includes field values.

- [ ] **Step 3: Write failing adapter request tests**

Patch each library at its transport boundary, invoke the real public batch
methods through the adapter, and assert:

```python
assert [order["b"] for order in captured_action["orders"]] == [True, False]
assert [order["t"] for order in captured_action["orders"]] == [
    {"limit": {"tif": "Alo"}},
    {"limit": {"tif": "Alo"}},
]
assert captured_payload["vaultAddress"].lower() == HL_SUB.lower()
```

Also assert OID cancellation batches two integer OIDs and recovery cancellation
batches only the requested CLOIDs.

- [ ] **Step 4: Implement the three adapters**

- async-hyperliquid: `place_orders`, `cancel_orders`, `cancel_orders_by_cloid`.
- SDK: `bulk_orders`, `bulk_cancel`, `bulk_cancel_by_cloid` with
  `TESTNET_API_URL` and `vault_address=HL_SUB`.
- CCXT: `set_sandbox_mode(True)`, preload markets, resolve the swap whose market
  ID is `BTC`, then use `create_orders` and `cancel_orders` with
  `vaultAddress=HL_SUB`; use `clientOrderId` for recovery.

Synchronous SDK/CCXT calls execute directly inside async adapter methods. All
adapters call the Task 2 parsers before returning.

- [ ] **Step 5: Add local wire-parity assertions**

For a supplied `OrderPair`, require `wire_orders` from all providers to equal
the canonical Hyperliquid order action fields `a,b,p,s,r,t,c`. Stop before any
live action on a mismatch.

- [ ] **Step 6: Run adapter tests and commit Task 3**

```bash
git add benchmarks/live/preflight.py benchmarks/live/providers.py tests/unit/test_live_benchmark_preflight.py tests/unit/test_live_benchmark_providers.py
git commit -m "feat: add testnet benchmark providers"
```

### Task 4: Cancellation-Identifier Suite

**Files:**
- Create: `benchmarks/live/runner.py`
- Create: `tests/unit/test_live_benchmark_cancel_id.py`

**Interfaces:**
- Produces: `run_cancel_id_suite(provider: LiveProvider, recovery: LiveProvider, mid_source: MarketSource, pacer: WeightedPacer, config: BenchmarkConfig, recorder: SampleRecorder, clock_ns: Callable[[], int]) -> Awaitable[None]`.
- Consumes: Task 1 models/pacer/workload and Task 3 provider protocol.

- [ ] **Step 1: Write failing rotation and timing tests with fake providers**

For four measured rounds, assert the call order is:

```python
[
    ("oid", "buy"), ("cloid", "sell"),
    ("cloid", "buy"), ("oid", "sell"),
    ("oid", "buy"), ("cloid", "sell"),
    ("cloid", "buy"), ("oid", "sell"),
]
```

Assert pacing occurs before `clock_ns()` starts, placement durations are not
included in the OID/CLOID summary, and warmup samples are omitted.

- [ ] **Step 2: Run the suite tests and verify RED**

Expected: import fails because `runner.py` is absent.

- [ ] **Step 3: Implement the RED/GREEN suite path**

Before placement, add both CLOIDs to a pending set. After each confirmed cancel,
remove only that order's CLOID. Record one `cancel_by_oid` or
`cancel_by_cloid` latency sample per measured operation.

- [ ] **Step 4: Write failing cleanup and invalidation tests**

Inject timeout during placement, error during first cancel, error during second
cancel, and recovery failure. Assert recovery receives exactly the still-pending
CLOIDs, measured operations are never retried, and recovery failure is terminal.

- [ ] **Step 5: Implement conservative `finally` cleanup**

Use the dedicated recovery provider through the same pacer. Preserve the
original failure as context, but raise a value-free `BenchmarkFailure` if
cleanup also fails.

- [ ] **Step 6: Run tests and commit Task 4**

```bash
git add benchmarks/live/runner.py tests/unit/test_live_benchmark_cancel_id.py
git commit -m "feat: benchmark oid and cloid cancellation"
```

### Task 5: Three-Provider Suite and Invalid-Run Persistence

**Files:**
- Modify: `benchmarks/live/runner.py`
- Modify: `benchmarks/live/results.py`
- Create: `tests/unit/test_live_benchmark_providers_suite.py`

**Interfaces:**
- Produces: `run_provider_suite(providers: Sequence[LiveProvider], recovery: LiveProvider, mid_source: MarketSource, pacer: WeightedPacer, config: BenchmarkConfig, recorder: SampleRecorder, clock_ns: Callable[[], int]) -> Awaitable[None]`.
- Produces: `write_report(report, output_dir: Path) -> Path` with atomic writes and `report.invalid.json` naming.

- [ ] **Step 1: Write failing provider-order rotation tests**

With provider names `(ccxt, sdk, async-hyperliquid)`, assert three successive
rounds use ABC, BCA, and CAB. Every provider receives the same price, size, and
ALO semantics for a round but fresh CLOIDs, so every submitted live order has a
globally unique recovery identifier. Exact wire parity is checked separately
with one unsubmitted probe pair.

- [ ] **Step 2: Implement paced two-operation provider timing**

For each provider, pace and time one two-order `place_batch_2`, then pace and
time one two-OID `cancel_batch_2_by_oid`. Remove both pending CLOIDs only after
explicit batch cancel success. Record no warmup samples.

- [ ] **Step 3: Write failing invalid-run persistence tests**

Force a rate-limit error and assert the report is `valid=false`, has a
value-free reason, contains the already collected safe samples, writes only
`report.invalid.json`, and exits through a caller-visible failure.

- [ ] **Step 4: Implement atomic safe report writes**

Serialize with sorted keys and a trailing newline to a sibling temporary file,
then replace the destination. Re-run the sanitizer immediately before writing.

- [ ] **Step 5: Run tests and commit Task 5**

```bash
git add benchmarks/live/runner.py benchmarks/live/results.py tests/unit/test_live_benchmark_providers_suite.py
git commit -m "feat: compare live exchange providers"
```

### Task 6: Charts and Validated README Publisher

**Files:**
- Create: `benchmarks/live/reporting.py`
- Create: `tests/unit/test_live_benchmark_reporting.py`
- Modify: `pyproject.toml`
- Modify mechanically: `uv.lock`

**Interfaces:**
- Produces: `write_csv(report, output_dir) -> Path`.
- Produces: `write_figures(report, output_dir) -> tuple[Path, ...]`.
- Produces: `validate_publishable(report) -> None`.
- Produces: `publish_report(report_path: Path, repository_root: Path) -> Path`.

- [ ] **Step 1: Write failing summary, CSV, and figure-input tests**

Assert deterministic rows, p50/MAD/p95 values, separate place/cancel series,
and OID/CLOID sample points. Patch Matplotlib save calls; unit tests do not
compare raster bytes.

- [ ] **Step 2: Add Matplotlib to the opt-in benchmark group**

Run:

```bash
UV_CACHE_DIR=/private/tmp/async-hyperliquid-uv-cache uv add --group benchmark 'matplotlib>=3.10,<4'
```

Keep it out of runtime dependencies.

- [ ] **Step 3: Implement CSV and two-panel PNG/SVG plots**

Each suite figure shows individual latency points/distribution on the left and
labelled median/p95 bars on the right. Provider place and cancel use separate
axes. Convert nanoseconds to milliseconds only for display.

- [ ] **Step 4: Write failing publication-gate and README rendering tests**

Reject invalid, partial, non-default-shape, wrong-provider, wrong-version, or
cleanup-failed reports. In a temporary repository, assert one detailed marker
block and one overall marker block are replaced from the same report while
surrounding prose remains byte-for-byte unchanged.

- [ ] **Step 5: Implement explicit publication**

Copy sanitized JSON, CSV, PNG, and SVG to
`benchmarks/results/<UTC timestamp>/`. Render both README updates in memory,
verify both marker pairs occur exactly once, then atomically replace both
files. The detailed block contains environment, method, full tables, figures,
artifact links, and limitations. The root block contains OID/CLOID winner,
provider median/p95 rankings, combined geometric-mean ranking, and a detailed
report link.

- [ ] **Step 6: Run tests and commit Task 6**

```bash
git add pyproject.toml uv.lock benchmarks/live/reporting.py tests/unit/test_live_benchmark_reporting.py
git commit -m "feat: publish live benchmark reports"
```

### Task 7: CLI, Manuals, and Offline End-to-End Tests

**Files:**
- Create: `benchmarks/live_exchange.py`
- Create: `tests/unit/test_live_benchmark_cli.py`
- Modify: `benchmarks/README.md`
- Modify: `README.md`

**Interfaces:**
- Produces CLI subcommands `cancel-id`, `providers`, `all`, and `publish`.
- Produces exit 0 only for a complete valid benchmark or successful publish.

- [ ] **Step 1: Write failing CLI parsing and guard tests**

Test defaults of three warmups, 30 rounds, and 250 ms; reject a 249 ms
interval; require `--output-dir` for live commands and `--report` for publish;
assert missing credentials fail before provider construction.

- [ ] **Step 2: Implement the CLI and resource lifecycle**

Load `.env.local` without overriding explicit environment values. Build the
recovery client first, validate roles, prepare providers, run local wire parity,
execute the chosen suites, write valid/invalid reports, write CSV/figures only
for valid runs, and close every client in reverse construction order.

- [ ] **Step 3: Add offline fake-provider end-to-end tests**

Run `all` through injected factories with a fake clock and one measured round.
Assert both suites appear in JSON and no network constructor runs.

- [ ] **Step 4: Document safe usage and add result marker blocks**

`benchmarks/README.md` documents credentials, testnet-only behavior, exact
commands, request-weight math, timing boundaries, cleanup verification,
artifacts, and publishing. Both READMEs receive marker sections that state no
validated live result has been published yet; do not insert simulated values.

- [ ] **Step 5: Run CLI tests and help smoke checks**

```bash
UV_CACHE_DIR=/private/tmp/async-hyperliquid-uv-cache uv run --frozen --group benchmark pytest -q tests/unit/test_live_benchmark_cli.py
UV_CACHE_DIR=/private/tmp/async-hyperliquid-uv-cache uv run --frozen --group benchmark python benchmarks/live_exchange.py --help
```

- [ ] **Step 6: Commit Task 7**

```bash
git add benchmarks/live_exchange.py tests/unit/test_live_benchmark_cli.py benchmarks/README.md README.md
git commit -m "docs: add live exchange benchmark workflow"
```

### Task 8: Full Validation and Credential-Gated Live Publication

**Files:**
- Modify only from a valid live publish: `benchmarks/results/<UTC timestamp>/**`, `benchmarks/README.md`, `README.md`
- Update at terminal state if present: `.agent/state.md`, `.agent/review_notes.md`, state/review archives.

**Interfaces:**
- Preserves all production APIs and default offline test behavior.
- Produces real README results only when a default-shape live report validates.

- [ ] **Step 1: Run Ruff formatting and linting**

```bash
UV_CACHE_DIR=/private/tmp/async-hyperliquid-uv-cache uv run --frozen ruff format
UV_CACHE_DIR=/private/tmp/async-hyperliquid-uv-cache uv run --frozen ruff check
```

- [ ] **Step 2: Run focused and complete offline tests**

Run all `test_live_benchmark_*.py`, existing benchmark tests, then the complete
default non-Exchange suite using repository-owned collection rules. Do not pass
an Exchange marker or collect `tests/integration/exchange/`.

- [ ] **Step 3: Run complete sequential Ty shards**

Enumerate all Python files under configured roots, verify shard coverage has no
gaps or duplicates, then run separate sequential `uv run --frozen ty check`
processes for `src`, `benchmarks`, each immediate `tests` package, and any
repository-configured Python script roots. Split any shard over 100 files.

- [ ] **Step 4: Review the implementation against the design**

Check every testnet, pacing, response, cleanup, redaction, plotting, and README
publication requirement. Run the repository-mandated routed review workflow
for the final non-trivial diff and resolve concrete findings.

- [ ] **Step 5: Run the credential-gated live benchmark when possible**

If `.env.local` or equivalent environment credentials are available, run:

```bash
UV_CACHE_DIR=/private/tmp/async-hyperliquid-uv-cache uv run --frozen --group benchmark python benchmarks/live_exchange.py all --output-dir /tmp/hl-live-final
UV_CACHE_DIR=/private/tmp/async-hyperliquid-uv-cache uv run --frozen --group benchmark python benchmarks/live_exchange.py publish --report /tmp/hl-live-final/report.json
```

Inspect JSON, CSV, both figures, targeted cleanup, and README diffs before
accepting the publication. If credentials are absent, report that live results
and README numeric publication remain blocked; do not weaken guards or insert
made-up data.

- [ ] **Step 6: Archive terminal state and hand off**

If `.agent/` exists, follow its immutable UTC archive protocol, compact hot
snapshots, and record changed paths, commands, exact pass/fail evidence,
unresolved live-run status, and rollback instructions.
