# Concurrent Cancel Benchmark Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the published provider comparison with a rate-controlled testnet benchmark that places 20 BTC ALO orders per round and concurrently sends ten single-order OID cancellations plus ten single-order CLOID cancellations.

**Architecture:** Keep the provider diagnostic suite intact, but extend the async provider with arbitrary-count placement and make `cancel-id` the only publishable live suite. The cancel runner creates all 20 tasks behind a shared start gate, records 300 request samples per identifier, derives per-round maxima for reporting, and uses conservative CLOID recovery for every unconfirmed cancellation.

**Tech Stack:** Python 3.12, asyncio/aiohttp, async-hyperliquid, pytest/pytest-asyncio, Matplotlib, uv, Ruff, Ty.

## Global Constraints

- Testnet only; `IS_MAINNET=false` remains mandatory.
- BTC perpetual only; buy price is `mid * 0.90`, sell price is `mid * 1.10`.
- Every order targets approximately 11 USDC notional and uses ALO with a unique CLOID.
- Each round places exactly ten buys and ten sells in one batch.
- Each round starts exactly ten OID and ten CLOID single-order cancellations through one shared gate.
- The pacer reserves 250 ms per REST weight and reserves weight 20 before each cancellation burst.
- Default publication shape is three warmups plus 30 measured rounds: 300 OID and 300 CLOID request samples.
- No measured failure is retried, dropped, or replaced; incomplete cleanup blocks publication.
- Preserve `providers`, `all`, SDK, and CCXT diagnostic implementation.
- Remove the committed `20260805T112127Z` provider results and publish no provider comparison values.
- Never persist credentials, addresses, OIDs, CLOIDs, nonces, signatures, request bodies, or response bodies.

---

### Task 1: Arbitrary-count async placement

**Files:**
- Modify: `benchmarks/live/results.py`
- Modify: `benchmarks/live/providers.py`
- Test: `tests/unit/test_live_benchmark_results.py`
- Test: `tests/unit/test_live_benchmark_providers.py`

**Interfaces:**
- Consumes: `CanonicalOrder`, `PlaceOrderRequest`, existing strict Hyperliquid response envelopes.
- Produces: `parse_resting_oids(response: object, *, expected: int, provider: str) -> tuple[int, ...]` and `AsyncHyperliquidProvider.place_many(orders: Sequence[CanonicalOrder]) -> tuple[int, ...]`.

- [ ] **Step 1: Write failing arbitrary-count parser tests**

Add a 20-status fixture and exact-count rejection cases:

```python
def _place_response(oids: Sequence[int]) -> dict[str, object]:
    return {
        "status": "ok",
        "response": {
            "type": "order",
            "data": {
                "statuses": [{"resting": {"oid": oid}} for oid in oids]
            },
        },
    }


def test_parse_twenty_resting_oids_requires_exact_count() -> None:
    response = _place_response(range(100, 120))
    assert parse_resting_oids(
        response, expected=20, provider="async-hyperliquid"
    ) == tuple(range(100, 120))

    with pytest.raises(BenchmarkFailure, match="non-resting"):
        parse_resting_oids(response, expected=19, provider="async-hyperliquid")
```

- [ ] **Step 2: Run the parser test and verify RED**

Run:

```bash
uv run --frozen pytest -q tests/unit/test_live_benchmark_results.py -k resting
```

Expected: FAIL because `parse_resting_oids` has no `expected` parameter and only accepts two statuses.

- [ ] **Step 3: Generalize the parser without weakening validation**

Implement the exact-count contract:

```python
def parse_resting_oids(
    response: object, *, expected: int, provider: str
) -> tuple[int, ...]:
    if expected < 1:
        raise ValueError("expected must be positive")
    statuses = _statuses(response, provider=provider, operation="placement")
    oids: list[int] = []
    if len(statuses) == expected:
        for status in statuses:
            status_mapping = _mapping(status)
            resting = (
                _mapping(status_mapping.get("resting"))
                if status_mapping is not None
                else None
            )
            oid = _positive_oid(resting.get("oid")) if resting is not None else None
            if oid is None:
                break
            oids.append(oid)
    if len(oids) != expected:
        raise BenchmarkFailure(f"{provider} produced a non-resting placement result")
    return tuple(oids)
```

Retain the existing error wording and sensitive-value exclusion. Update all existing callers to pass `expected=2`.

- [ ] **Step 4: Write a failing provider test for one 20-order call**

Extend `AsyncClientStub` with a dynamic response and assert one public call receives all 20 requests:

```python
class AsyncClientStub:
    def __init__(self, resting_oids: tuple[int, ...] = (101, 202)) -> None:
        self.resting_oids = resting_oids
        self.placed: object = None

    async def place_orders(self, orders: object) -> object:
        self.placed = orders
        return {
            "status": "ok",
            "response": {
                "type": "order",
                "data": {
                    "statuses": [
                        {"resting": {"oid": oid}} for oid in self.resting_oids
                    ]
                },
            },
        }


async def test_async_provider_places_arbitrary_order_batch() -> None:
    client = AsyncClientStub(resting_oids=tuple(range(100, 120)))
    provider = AsyncHyperliquidProvider(
        cast(Any, client), coin="BTC", asset=0, size_decimals=5
    )
    orders = tuple(
        CanonicalOrder(
            is_buy=index % 2 == 0,
            price=90_000.0 if index % 2 == 0 else 110_000.0,
            size=0.00013 if index % 2 == 0 else 0.0001,
            cloid=f"0x{index + 1:032x}",
        )
        for index in range(20)
    )

    assert await provider.place_many(orders) == tuple(range(100, 120))
    assert len(cast(tuple[object, ...], client.placed)) == 20
```

- [ ] **Step 5: Run the provider test and verify RED**

Run:

```bash
uv run --frozen pytest -q tests/unit/test_live_benchmark_providers.py -k arbitrary_order_batch
```

Expected: FAIL because `place_many` does not exist.

- [ ] **Step 6: Implement `place_many` and preserve pair behavior**

Use one request tuple and keep `place` as the two-order adapter:

```python
async def place_many(
    self, orders: Sequence[CanonicalOrder]
) -> tuple[int, ...]:
    if not orders:
        raise ValueError("orders must not be empty")
    requests = tuple(_async_request(order, self._coin) for order in orders)
    response = await self._client.place_orders(requests)
    return parse_resting_oids(
        response, expected=len(orders), provider=self.name
    )

async def place(self, pair: OrderPair) -> tuple[int, int]:
    return cast(tuple[int, int], await self.place_many(pair.as_tuple()))
```

- [ ] **Step 7: Run focused tests and commit**

Run:

```bash
uv run --frozen pytest -q tests/unit/test_live_benchmark_results.py tests/unit/test_live_benchmark_providers.py
uv run --frozen ruff check benchmarks/live/results.py benchmarks/live/providers.py tests/unit/test_live_benchmark_results.py tests/unit/test_live_benchmark_providers.py
```

Commit:

```bash
git add benchmarks/live/results.py benchmarks/live/providers.py tests/unit/test_live_benchmark_results.py tests/unit/test_live_benchmark_providers.py
git commit -m "feat: place concurrent cancel order batches"
```

---

### Task 2: Twenty-request gated cancellation runner

**Files:**
- Modify: `benchmarks/live/runner.py`
- Test: `tests/unit/test_live_benchmark_cancel_id.py`

**Interfaces:**
- Consumes: `AsyncHyperliquidProvider.place_many`, `WeightedPacer.wait`, `CanonicalOrder`, `LatencySample`.
- Produces: `run_cancel_id_suite` with one 20-order batch and a gated 20-task cancellation burst per logical round.

- [ ] **Step 1: Replace the sequential expectations with failing 20-request tests**

Make the existing `ProviderStub` accept arbitrary placement and a set of
failing cancellation call numbers:

```python
class ProviderStub:
    def __init__(
        self,
        clock: TickClock,
        *,
        fail_place: bool = False,
        fail_cancel_calls: set[int] | None = None,
    ) -> None:
        self.clock = clock
        self.fail_place = fail_place
        self.fail_cancel_calls = fail_cancel_calls or set()
        self.placement_sizes: list[int] = []
        self.cancel_calls = 0
        self.completed_calls: set[int] = set()
        self.events: list[tuple[str, str]] = []

    async def place_many(
        self, orders: Sequence[CanonicalOrder]
    ) -> tuple[int, ...]:
        self.placement_sizes.append(len(orders))
        if self.fail_place:
            raise TimeoutError("indeterminate placement")
        return tuple(range(100, 100 + len(orders)))
```

Keep the existing single-order cancel methods, but increment `cancel_calls`
before checking `fail_cancel_calls` and add successful call numbers to
`completed_calls`. Then add assertions for two measured rounds:

```python
async def test_cancel_identifier_launches_balanced_twenty_request_burst() -> None:
    config = BenchmarkConfig(rounds=2, warmups=0)
    clock = TickClock()
    provider = ProviderStub(clock)
    pacer = PacerStub(clock)
    recorder = _recorder(config)

    await run_cancel_id_suite(
        cast(Any, provider), cast(Any, RecoveryStub()),
        cast(Any, MarketSourceStub()), cast(Any, pacer), config, recorder,
        clock_ns=clock.now, cloid_factory=_cloid_factory(),
    )

    assert provider.placement_sizes == [20, 20]
    assert pacer.weights == [2, 1, 20, 2, 1, 20]
    assert sum(method == "oid" for method, _ in provider.events[:20]) == 10
    assert sum(method == "cloid" for method, _ in provider.events[:20]) == 10
    assert len(recorder.samples) == 40
```

Also assert each method receives five buys/five sells per round, OID/CLOID launch-slot parity swaps in round two, and all 20 stub calls observe the gate as open.

- [ ] **Step 2: Run the balance test and verify RED**

Run:

```bash
uv run --frozen pytest -q tests/unit/test_live_benchmark_cancel_id.py -k balanced_twenty
```

Expected: FAIL because the current runner places two orders and performs sequential weight-1 cancellations.

- [ ] **Step 3: Implement order construction and fair descriptors**

Build ten pairs and flatten them to 20 interleaved buy/sell orders:

```python
pairs = tuple(
    build_order_pair(
        mid,
        size_decimals,
        target_notional=config.target_notional,
        cloids=(cloid_factory(), cloid_factory()),
        buy_multiplier=config.buy_multiplier,
        sell_multiplier=config.sell_multiplier,
    )
    for _ in range(10)
)
orders = tuple(order for pair in pairs for order in pair.as_tuple())
```

Assign five pairs to OID and five pairs to CLOID using `(pair_index + logical_round) % 2`, then interleave the two ten-item descriptor lists. Swap which method owns launch slot zero every round.

- [ ] **Step 4: Implement the shared start gate and per-request timing**

Add a small internal result type and task helper:

```python
async def _cancel_one(
    provider: LiveProvider,
    gate: asyncio.Event,
    operation: str,
    order: CanonicalOrder,
    oid: int,
    clock_ns: Callable[[], int],
) -> int:
    await gate.wait()
    started = clock_ns()
    if operation == "cancel_by_oid":
        await provider.cancel_oids((order,), (oid,))
    else:
        await provider.cancel_cloids((order,))
    return clock_ns() - started
```

Reserve the complete burst weight before creating tasks:

```python
await pacer.wait(weight=20)
gate = asyncio.Event()
tasks = tuple(asyncio.create_task(_cancel_one(...)) for descriptor in descriptors)
await asyncio.sleep(0)
gate.set()
results = await asyncio.gather(*tasks, return_exceptions=True)
```

Only confirmed successes leave `pending`. Record `provider_order=launch_slot` after all task results have been inspected.

- [ ] **Step 5: Write failing concurrent failure/recovery tests**

Cover one and multiple request failures:

```python
async def test_concurrent_cancel_waits_for_all_tasks_and_recovers_pending() -> None:
    config = BenchmarkConfig(rounds=1, warmups=0)
    clock = TickClock()
    provider = ProviderStub(clock, fail_cancel_calls={4, 15})
    recovery = RecoveryStub()

    with pytest.raises(ExceptionGroup, match="concurrent cancel"):
        await run_cancel_id_suite(
            cast(Any, provider),
            cast(Any, recovery),
            cast(Any, MarketSourceStub()),
            cast(Any, PacerStub(clock)),
            config,
            _recorder(config),
            clock_ns=clock.now,
            cloid_factory=_cloid_factory(),
        )

    assert provider.completed_calls == set(range(1, 21)) - {4, 15}
    assert len(recovery.cleaned) == 1
    assert len(recovery.cleaned[0]) == 2
```

Also retain placement-failure recovery for all 20 CLOIDs and cleanup-failure terminal behavior.

- [ ] **Step 6: Run runner tests and commit**

Run:

```bash
uv run --frozen pytest -q tests/unit/test_live_benchmark_cancel_id.py tests/unit/test_live_benchmark_core.py
uv run --frozen ruff check benchmarks/live/runner.py tests/unit/test_live_benchmark_cancel_id.py
```

Commit:

```bash
git add benchmarks/live/runner.py tests/unit/test_live_benchmark_cancel_id.py
git commit -m "feat: benchmark concurrent oid and cloid cancellation"
```

---

### Task 3: Cancel-only publication and derived round maxima

**Files:**
- Modify: `benchmarks/live/reporting.py`
- Test: `tests/unit/test_live_benchmark_reporting.py`
- Test: `tests/unit/test_live_benchmark_results.py`

**Interfaces:**
- Consumes: schema-v1 cancellation request samples grouped by operation and round.
- Produces: `round_max_summaries(report: LiveBenchmarkReport) -> dict[str, LatencySummary]`, cancel-only publishability validation, and cancel-only README/chart rendering.

- [ ] **Step 1: Write failing exact-shape publication tests**

Change `_valid_report()` to contain 30 rounds × ten samples for each identifier and no provider samples. Assert:

```python
def test_publication_requires_concurrent_cancel_shape() -> None:
    report = _valid_report()
    validate_publishable(report)
    assert len(report["samples"]) == 600

    report["samples"].pop()
    with pytest.raises(BenchmarkFailure, match="sample shape"):
        validate_publishable(report)
```

Add mutations for duplicate launch slots, wrong slot parity, an 11/9 method split, provider samples, and an `all` report.

- [ ] **Step 2: Run publication tests and verify RED**

Run:

```bash
uv run --frozen --group benchmark pytest -q tests/unit/test_live_benchmark_reporting.py -k publication
```

Expected: FAIL because publication currently requires the two-sample cancel suite plus all six provider groups.

- [ ] **Step 3: Implement exact concurrent sample validation**

Make `_expected_counts()` return only:

```python
Counter({
    ("cancel-id", "async-hyperliquid", "cancel_by_oid"): 300,
    ("cancel-id", "async-hyperliquid", "cancel_by_cloid"): 300,
})
```

For each measured round require exactly ten samples per operation. Require launch slots `0..19` to be unique across both methods and require OID to own even slots when `(warmups + round_index)` is even, odd slots otherwise.

- [ ] **Step 4: Write failing derived-statistics tests**

Use hand-derived values for two synthetic rounds:

```python
def _small_concurrent_report(
    oid_rounds: tuple[tuple[int, ...], ...],
    cloid_rounds: tuple[tuple[int, ...], ...],
) -> LiveBenchmarkReport:
    samples = []
    for operation, rounds in (
        ("cancel_by_oid", oid_rounds),
        ("cancel_by_cloid", cloid_rounds),
    ):
        for round_index, durations in enumerate(rounds):
            for launch_slot, duration_ns in enumerate(durations):
                samples.append(
                    {
                        "suite": "cancel-id",
                        "provider": "async-hyperliquid",
                        "operation": operation,
                        "round_index": round_index,
                        "provider_order": launch_slot,
                        "duration_ns": duration_ns,
                    }
                )
    return cast(LiveBenchmarkReport, {"samples": samples})


def test_round_max_summaries_use_the_slowest_request_per_method_round() -> None:
    report = _small_concurrent_report(
        oid_rounds=((1, 2, 9), (3, 4, 8)),
        cloid_rounds=((5, 6, 7), (2, 10, 11)),
    )
    summaries = round_max_summaries(report)
    assert summaries["cancel_by_oid"]["median_ns"] == 8.5
    assert summaries["cancel_by_cloid"]["median_ns"] == 9.0
```

- [ ] **Step 5: Implement derived round maxima and cancel-only rendering**

Group by `(operation, round_index)`, take each ten-request maximum, and call `summarize_ns` on the 30 maxima. Render two chart views: all individual request distributions/median/p95 and derived round-max distributions/median/p95.

Remove `_combined_scores` and every provider table/ranking from `_detail_markdown` and `_overall_markdown`. Display both request and round-max statistics and state `concurrency=20 (10 OID + 10 CLOID)`.

- [ ] **Step 6: Make publication require only cancel artifacts**

Change `publish_report` source requirements to:

```python
required = {
    "report.json",
    "samples.csv",
    "cancel-id-latency.png",
    "cancel-id-latency.svg",
}
```

Continue regenerating CSV and figures from the validated report rather than trusting source artifacts.

- [ ] **Step 7: Run reporting tests and commit**

Run:

```bash
uv run --frozen --group benchmark pytest -q tests/unit/test_live_benchmark_reporting.py tests/unit/test_live_benchmark_results.py
uv run --frozen ruff check benchmarks/live/reporting.py tests/unit/test_live_benchmark_reporting.py tests/unit/test_live_benchmark_results.py
```

Commit:

```bash
git add benchmarks/live/reporting.py tests/unit/test_live_benchmark_reporting.py tests/unit/test_live_benchmark_results.py
git commit -m "feat: publish concurrent cancel benchmarks"
```

---

### Task 4: CLI contract, documentation, and provider-result cleanup

**Files:**
- Modify: `benchmarks/live_exchange.py`
- Modify: `tests/unit/test_live_benchmark_cli.py`
- Modify: `README.md`
- Modify: `benchmarks/README.md`
- Delete: `benchmarks/results/20260805T112127Z/report.json`
- Delete: `benchmarks/results/20260805T112127Z/samples.csv`
- Delete: `benchmarks/results/20260805T112127Z/cancel-id-latency.png`
- Delete: `benchmarks/results/20260805T112127Z/cancel-id-latency.svg`
- Delete: `benchmarks/results/20260805T112127Z/providers-latency.png`
- Delete: `benchmarks/results/20260805T112127Z/providers-latency.svg`

**Interfaces:**
- Consumes: existing `cancel-id`, `providers`, `all`, and `publish` commands.
- Produces: cancel-only default reproduction/publication documentation while retaining provider diagnostics.

- [ ] **Step 1: Write failing CLI/publication contract tests**

Assert `cancel-id` remains the default publishable shape and help text calls provider/all diagnostic:

```python
def test_cancel_id_is_the_only_publishable_live_suite() -> None:
    args = parse_args(["cancel-id", "--output-dir", "/tmp/result"])
    assert args.command == "cancel-id"
    assert args.rounds == 30
    assert args.warmups == 3
    assert args.interval_ms == 250
    help_text = build_parser().format_help()
    assert "publishable 20-request OID/CLOID benchmark" in help_text
    assert "unpublishable provider diagnostic suite" in help_text
```

Update command-outcome tests so a default `cancel-id` report contains 600 samples. Keep provider/all execution tests to prove the code was not removed.

- [ ] **Step 2: Run CLI tests and verify RED**

Run:

```bash
uv run --frozen pytest -q tests/unit/test_live_benchmark_cli.py
```

Expected: FAIL on the old sequential sample expectations and old publication language.

- [ ] **Step 3: Update CLI descriptions without removing commands**

Use help text that distinguishes the publishable concurrent suite:

```python
("cancel-id", "run the publishable 20-request OID/CLOID benchmark"),
("providers", "run the unpublishable provider diagnostic suite"),
("all", "run both suites for diagnostics; output is not publishable"),
```

Do not delete `run_provider_suite`, provider construction, adapters, or tests.

- [ ] **Step 4: Remove the old committed result directory**

Run the exact scoped deletion authorized by the user:

```bash
git rm -r benchmarks/results/20260805T112127Z
```

Verify `git status --short` lists only that exact result directory as deleted plus intended code/docs changes.

- [ ] **Step 5: Rewrite methodology and reset result markers**

Document 20-order placement, the shared start gate, 300/300 samples, weight-20 burst reservation, 759 total default weight, derived round maxima, and the approximately 660-order testnet requirement.

Keep provider diagnostic commands but explicitly label them unpublishable. Replace both README marker bodies with a neutral message:

```markdown
No validated concurrent OID/CLOID result has been published yet. Provider
diagnostic reports are not eligible for this section.
```

Ensure no SDK/CCXT place/cancel number, provider ranking, or provider figure link remains in either README.

- [ ] **Step 6: Run CLI/docs/package tests and commit**

Run:

```bash
uv run --frozen pytest -q tests/unit/test_live_benchmark_cli.py tests/package/test_readme.py
rg -n "569\.62|868\.22|Provider comparison|providers-latency|Overall equal-weight ranking" README.md benchmarks/README.md
git diff --check
```

Expected: tests pass; `rg` returns no published-result matches.

Commit:

```bash
git add benchmarks/live_exchange.py tests/unit/test_live_benchmark_cli.py README.md benchmarks/README.md benchmarks/results/20260805T112127Z
git commit -m "docs: retire provider benchmark results"
```

---

### Task 5: Deterministic verification and routed review

**Files:**
- Update ignored task state: `.agent/state.md`
- Create review artifacts only if routed review needs them: `.agent/review_artifacts/<timestamp>--concurrent-cancel-benchmark-20260805/`

**Interfaces:**
- Consumes: all implementation commits from Tasks 1–4.
- Produces: a clean, reviewed revision eligible for the real testnet run.

- [ ] **Step 1: Run the complete deterministic suite**

Run:

```bash
uv run --frozen --group benchmark pytest -q tests/contracts tests/oracle tests/package tests/public_api tests/unit
uv run --frozen ruff check
uv run --frozen ruff format --check
uv run --frozen ty check
git diff --check
```

Expected: zero failures; package-only environmental skips are allowed and must be reported.

- [ ] **Step 2: Run the mandatory routed review workflow**

Run `$diff-semantic-analyzer`, `$risk-router`, `$linus-review`, `$red-team-review`, and `$rollback-safety`; run the router-selected concurrency, data-integrity, operational-risk, or observability skills; merge with `$merge-review`. Resolve every blocking finding with a new RED/GREEN test cycle and rerun Step 1.

- [ ] **Step 3: Confirm live preconditions**

Verify without printing secrets:

```bash
git status --short
pgrep -afil benchmarks/live_exchange.py
uv run --frozen python -c 'from pathlib import Path; assert Path(".env.local").is_file(); print("dotenv_present=true")'
```

Require a clean worktree, no competing benchmark process, testnet credentials with correct API-wallet derivation/roles, and no unrelated open-order concern on the execution subaccount.

---

### Task 6: Execute, validate, and publish the concurrent live result

**Files:**
- Create: `benchmarks/results/<UTC timestamp>/report.json`
- Create: `benchmarks/results/<UTC timestamp>/samples.csv`
- Create: `benchmarks/results/<UTC timestamp>/cancel-id-latency.png`
- Create: `benchmarks/results/<UTC timestamp>/cancel-id-latency.svg`
- Modify: `README.md`
- Modify: `benchmarks/README.md`
- Update ignored completion ledger: `.agent/state.md`
- Create ignored completion archive: `.agent/state_archive/<timestamp>--concurrent-cancel-benchmark-20260805.md`

**Interfaces:**
- Consumes: clean reviewed implementation revision and `.env.local` testnet credentials.
- Produces: one committed, sanitized, cancel-only benchmark publication.

- [ ] **Step 1: Run the live benchmark into a fresh directory**

Create a fresh explicit directory and run only the publishable suite:

```bash
OUTPUT_DIR=$(mktemp -d /private/tmp/hl-concurrent-cancel.XXXXXX)
UV_CACHE_DIR=/private/tmp/async-hyperliquid-uv-cache \
MPLCONFIGDIR=/private/tmp/async-hyperliquid-matplotlib \
uv run --frozen --group benchmark python benchmarks/live_exchange.py cancel-id \
  --output-dir "$OUTPUT_DIR"
```

Expected runtime is at least 189.75 seconds plus setup and network time. Do not publish an invalid report or retry a failed measured sample.

- [ ] **Step 2: Validate the live report independently**

Load the generated report and assert:

```python
validate_publishable(report)
assert report["valid"] is True
assert report["cleanup_ok"] is True
assert len(report["samples"]) == 600
assert Counter(sample["operation"] for sample in report["samples"]) == {
    "cancel_by_oid": 300,
    "cancel_by_cloid": 300,
}
```

Scan JSON/CSV against `HL_ADDR`, `HL_AK`, `HL_SK`, and `HL_SUB` without printing their values. Inspect the PNG and confirm labels, units, distributions, and summary values match the report.

- [ ] **Step 3: Publish from the validated report**

Run:

```bash
uv run --frozen --group benchmark python benchmarks/live_exchange.py publish \
  --report "$OUTPUT_DIR/report.json"
```

Verify the new result directory contains exactly four artifacts and that both README markers contain only concurrent OID/CLOID statistics.

- [ ] **Step 4: Run final verification**

Run:

```bash
uv run --frozen --group benchmark pytest -q tests/contracts tests/oracle tests/package tests/public_api tests/unit
uv run --frozen ruff check
uv run --frozen ruff format --check
uv run --frozen ty check
git diff --check
git status --short
```

Re-run publishability, 600-sample, secret-absence, LF/SVG whitespace, and artifact-count assertions against the committed destination.

- [ ] **Step 5: Commit the replacement publication**

```bash
git add README.md benchmarks/README.md benchmarks/results
git commit -m "docs: publish concurrent cancel benchmark results"
```

- [ ] **Step 6: Archive task state and hand off**

Create the required immutable `.agent/state_archive` record containing revisions, workload, exact results, validation evidence, unresolved testnet variability, and rollback commits. Rewrite `.agent/state.md` to keep only the new last-archived pointer and confirm the ignored hot file remains below 160 lines/12 KiB.
