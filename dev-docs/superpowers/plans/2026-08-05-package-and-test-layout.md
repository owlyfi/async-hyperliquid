# Package and Test Layout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give private runtime code, benchmarks, and tests concise domain-owned locations while making every Exchange integration case visible to pytest and VS Code.

**Architecture:** Keep the public package root limited to clients, protocol constants/errors, and types. Move private implementation code into `_internal`, split pure Exchange/Info helpers by domain, keep network execution fixture-gated, and let directory context replace duplicated test filename words.

**Tech Stack:** Python 3.12, uv, pytest, pytest-asyncio, Ruff, ty, aiohttp, Hyperliquid testnet.

## Global Constraints

- Do not create `utils/` or compatibility wrappers for private RC1 modules.
- Keep `errors.py`, `constants.py`, and all public client/type names stable.
- Keep Exchange execution testnet-only and load credentials from `.env.local`.
- Preserve the destructive-action opt-in and cleanup behavior.
- Do not modify Copycat or another repository.
- Rename every non-magic test-side Python filename containing more than one underscore according to the approved spec table.

---

### Task 1: Make Exchange tests discoverable

**Files:**
- Create: `tests/package/test_collection.py`
- Modify: `pyproject.toml`

**Interfaces:**
- Consumes: repository pytest configuration and `tests/integration/exchange/test_orders.py`.
- Produces: default collection that includes `test_place_limit_order` without a marker override.

- [ ] **Step 1: Add the subprocess discovery regression**

```python
def test_exchange_tests_are_collected_by_default() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "tests/integration/exchange"],
        cwd=Path(__file__).parents[2],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "test_place_limit_order" in result.stdout
```

- [ ] **Step 2: Verify the regression fails for the current global marker expression**

Run: `uv run pytest -q tests/package/test_collection.py`

Expected: FAIL because the child process reports 60 deselected and exits 5.

- [ ] **Step 3: Remove marker selection from default addopts**

Keep only `--verbose` in `tool.pytest.ini_options.addopts`. Runtime fixtures,
not collection configuration, own opt-in behavior.

- [ ] **Step 4: Verify discovery and the deterministic default behavior**

Run:

```bash
uv run pytest -q tests/package/test_collection.py
uv run pytest --collect-only -q tests/integration/exchange
uv run pytest -q
```

Expected: collection succeeds and integration cases skip without opt-in rather
than disappearing.

### Task 2: Establish the private package boundary

**Files:**
- Create: `src/async_hyperliquid/_internal/__init__.py`
- Move: `_encoding.py` → `_internal/encoding.py`
- Move: `_http.py` → `_internal/http.py`
- Move: `_metadata.py` → `_internal/metadata.py`
- Move: `_signing.py` → `_internal/signing.py`
- Create: `_internal/exchange.py`
- Create: `_internal/info.py`
- Modify: `client.py`, `exchange.py`, `info.py`, tests, and benchmarks imports.

**Interfaces:**
- `_internal.exchange` produces `format_token_amount`, `amount_in_units`,
  `exact_signed_units`, `positive_wire_amount`, and `expect_action_response`.
- `_internal.info` produces `expect_object`, `expect_optional_object`,
  `expect_list`, `expect_optional_list`, `expect_bool`, `expect_int`,
  `expect_string`, `expect_pair`, `wait_for_tasks`, `context_price`,
  `context_price_by_coin`, and `price_from_context`.

- [ ] **Step 1: Record the green behavioral baseline**

Run:

```bash
uv run pytest -q tests/unit tests/oracle tests/public_api tests/contracts
```

Expected: PASS before moving implementation.

- [ ] **Step 2: Move the four existing private modules and repair relative imports**

Private modules import root contracts with `..constants`, `..errors`, and
`..types`. All runtime/tests/benchmarks import `_internal.<domain>` directly.
Do not leave old forwarding modules.

- [ ] **Step 3: Extract pure Exchange helpers**

Move lines 109-242 of the current Exchange module into
`_internal/exchange.py`; remove leading underscores from module-private exports
because privacy is already expressed by `_internal`. Preserve exact parsing,
decimal rounding, status discrimination, and exception messages.

- [ ] **Step 4: Extract pure Info helpers**

Move JSON shape validators, cancellation-safe task waiting, and context-price
functions into `_internal/info.py`. Preserve `wait_for_tasks` cancellation and
exception-draining behavior exactly.

- [ ] **Step 5: Run focused behavioral suites**

Run:

```bash
uv run pytest -q tests/unit/test_actions.py tests/unit/test_exchange.py tests/unit/test_info.py tests/unit/test_metadata.py tests/unit/test_transport.py tests/oracle/test_signing.py
```

Expected: PASS with no old private-module imports remaining.

### Task 3: Normalize benchmark and test names

**Files:**
- Move: `scripts/client_hotpath_benchmark.py` → `benchmarks/hotpath.py`
- Move: all test files listed in the approved design table.
- Move: `tests/integration/live_config.py` → `tests/integration/config.py`
- Modify: imports, integration fixture names, contract coverage, docs, and CI.

**Interfaces:**
- `benchmarks.hotpath` retains the same CLI and `compare_wheels` API.
- Integration exports `require_env`, `require_testnet`, `validate_credentials`,
  and `validate_roles`.
- The subaccount/API-wallet client fixture is `hl`; master-only tests continue
  to request `master_hl`.

- [ ] **Step 1: Apply the exact filename mapping from the design spec**

Do not rename magic `__init__.py`. After moving, run:

```bash
rg --files tests | rg '/[^/]*_[^/]*_[^/]*\.py$'
```

Expected: only magic `__init__.py` matches.

- [ ] **Step 2: Rename integration vocabulary**

Use `hl`, `Markets`, `config.py`, `validate_credentials`, `validate_roles`,
`RUN_INFO_TESTS`, and `RUN_EXCHANGE_TESTS`. Remove the redundant word `live`
from integration test/support identifiers and marker descriptions.

- [ ] **Step 3: Repair benchmark and test references**

Update imports to `benchmarks.hotpath`, current README commands, CI Ruff/ty
roots, build/source documentation, and executable plans. Remove `scripts/`
after its final file moves.

- [ ] **Step 4: Run renamed suites**

Run:

```bash
uv run pytest -q tests/unit tests/contracts tests/oracle tests/package tests/public_api
uv run python benchmarks/hotpath.py --help
```

Expected: PASS and the benchmark CLI prints usage.

### Task 4: Validate real testnet behavior and review

**Files:**
- Modify: `README.md`, `CHANGELOG.md`, `.github/workflows/ci.yml`
- Update local `.agent` state/review archives; these remain untracked.

**Interfaces:**
- Consumes: `.env.local` keys `HL_ADDR`, `HL_PK`, `HL_AK`, `HL_SK`, `HL_SUB`,
  and `IS_MAINNET=false`.
- Produces: visible collection, passing deterministic/type/build gates, real
  Exchange execution, and zero residual test state.

- [ ] **Step 1: Run formatting, lint, and sequential type shards**

Run Ruff over `src tests benchmarks`. Run separate `ty check` processes for
`src`, `tests/contracts`, `tests/integration`, `tests/oracle`, `tests/package`,
`tests/public_api`, `tests/typing`, `tests/unit`, and `benchmarks`.

- [ ] **Step 2: Run deterministic, contract, build, and benchmark gates**

Run:

```bash
uv run pytest -q
uv lock --check
uv build
uv run --frozen --group benchmark python benchmarks/signing.py --rounds 3 --warmups 1 --iterations 1000
```

- [ ] **Step 3: Execute the complete Exchange suite against testnet**

Run:

```bash
RUN_EXCHANGE_TESTS=true RUN_DESTRUCTIVE_EXCHANGE_TESTS=true \
  uv run pytest -q tests/integration/exchange
```

The fixture must hard-fail when `.env.local` says `IS_MAINNET=true`. Record the
actual pass/skip counts and query the subaccount afterward for residual orders
and nonzero positions.

- [ ] **Step 4: Run the mandatory routed review**

Apply `diff-semantic-analyzer`, `risk-router`, `linus-review`,
`red-team-review`, `rollback-safety`, all risk-selected reviewers, and
`merge-review`. Fix every concrete finding, repeat affected gates, archive the
terminal state/review, and commit the final implementation.
