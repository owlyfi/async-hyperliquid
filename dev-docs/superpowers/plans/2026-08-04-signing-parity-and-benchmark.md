# Signing Parity and Benchmark Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prove exact official-SDK request parity and deliver a parity-gated three-provider signing benchmark before making any measured signing optimization.

**Architecture:** Keep production signing ownership in `_signing.py` and envelope ownership in `ExchangeClient`. Add focused oracle tests plus a standalone benchmark runner whose provider probes call the real CCXT, SDK, and async-hyperliquid implementations in child processes.

**Tech Stack:** Python 3.12, pytest, eth-account, msgpack, hyperliquid-python-sdk 0.24.0, CCXT 4.5.71, uv, Ruff, Ty.

## Global Constraints

- Keep the package version at `1.0.0rc1`.
- Do not run or collect Exchange integration tests.
- Do not modify Copycat or remove user-added integration tests.
- Never print or persist `.env.local` private keys, real signatures, or real payloads.
- Benchmark only implementations that pass the same action/signature parity gate.
- Do not commit unless the user separately requests a commit.

---

### Task 1: Exact SDK Envelope Parity

**Files:**
- Create: `tests/oracle/test_signing_payload_parity.py`
- Modify: `tests/unit/test_exchange_client.py`
- Modify: `src/async_hyperliquid/types/exchange.py`
- Modify: `src/async_hyperliquid/exchange.py`

**Interfaces:**
- Consumes: `ExchangeClient._submit_action`, SDK `sign_l1_action`, and SDK `Exchange._post_action`.
- Produces: an `ActionEnvelope` where `vaultAddress: str | None` and `expiresAfter: int | None` are always present.

- [ ] **Step 1: Write a failing deterministic payload test**

  Capture the actual async-hyperliquid transport payload and the SDK
  `_post_action` payload for a fixed test key, order action, nonce, vault, and
  expiry. Compare dictionaries directly without HTTP.

- [ ] **Step 2: Verify the test fails on absent null envelope fields**

  Run:

  ```bash
  UV_CACHE_DIR=/private/tmp/async-hyperliquid-uv-cache uv run pytest -q tests/oracle/test_signing_payload_parity.py
  ```

  Expected: the no-vault/no-expiry case fails because async-hyperliquid omits
  keys that SDK 0.24.0 includes with `None`.

- [ ] **Step 3: Make the envelope contract exact**

  Define the two fields as required nullable `TypedDict` members and construct
  every envelope as:

  ```python
  envelope: ActionEnvelope = {
      "action": action,
      "nonce": nonce,
      "signature": signature,
      "vaultAddress": vault_address,
      "expiresAfter": expires_after,
  }
  ```

- [ ] **Step 4: Update focused envelope assertions**

  Replace assertions that expect omitted optional keys with assertions that
  require `None`; retain vault-scope assertions so root actions, `sendAsset`,
  and `usdClassTransfer` cannot accidentally target the configured vault.

- [ ] **Step 5: Verify deterministic parity passes**

  Run the oracle test and `tests/unit/test_exchange_client.py`; expect both to
  pass without collecting `tests/integration/exchange/`.

### Task 2: Safe `.env.local` Oracle

**Files:**
- Modify: `tests/oracle/test_signing_payload_parity.py`

**Interfaces:**
- Consumes: `HL_ADDR`, `HL_PK`, `HL_AK`, `HL_SK`, and `HL_SUB` from the already-loaded `.env.local`.
- Produces: local-only runtime equality checks with value-free failure messages.

- [ ] **Step 1: Add credential-shape and address-pair checks**

  Skip when the five variables are absent. Derive each account address with
  `Account.from_key` and use `is_same_address`; raise messages containing only
  variable names on failure.

- [ ] **Step 2: Add master and API-wallet payload comparisons**

  Compare SDK and async payloads for `HL_PK` without a vault and for `HL_SK`
  with `HL_SUB`, using fixed testnet nonces and no network call. Avoid bare
  rewritten `assert` expressions containing payload values.

- [ ] **Step 3: Run the oracle test with output capture enabled**

  Run the single test file with `-q`; expect pass and no secret-bearing output.

### Task 3: Real Three-Provider Benchmark

**Files:**
- Modify: `pyproject.toml`
- Modify mechanically: `uv.lock`
- Create: `benchmarks/signing.py`
- Create: `tests/unit/test_signing_benchmark.py`

**Interfaces:**
- Produces: `run_benchmark(commands, *, rounds, warmups) -> SigningBenchmarkReport` and a CLI accepting `--rounds`, `--warmups`, `--iterations`, and optional `--output`.
- Report summaries contain `median_ns`, `mad_ns`, `p95_ns`, and `ops_per_second`.

- [ ] **Step 1: Write failing benchmark orchestration tests**

  Test rotating provider order, exact operation-set validation, child failure
  propagation, nearest-rank p95, ops/sec calculation, and JSON serialization.

- [ ] **Step 2: Add `ccxt==4.5.71` to an opt-in benchmark group and refresh the lock**

  Use `uv lock`, keeping CCXT out of runtime dependencies.

- [ ] **Step 3: Implement provider probes**

  Use one committed safe key and fixed nonce. Call:

  - CCXT `action_hash`, `sign_l1_action`, and native order construction;
  - SDK `action_hash`, `sign_l1_action`, and `order_request_to_order_wire`;
  - async-hyperliquid `hash_action`, `sign_exchange_action`, and `encode_order`.

  Before timing, require the exact safe action and signature vector. The probe
  emits only positive numeric timings.

- [ ] **Step 4: Implement rotating subprocess orchestration**

  Rotate `(ccxt, sdk, async-hyperliquid)` each round, exclude child startup from
  the internally measured loop, and reject mismatched operation sets.

- [ ] **Step 5: Run unit tests and a low-iteration smoke benchmark**

  Expect all five operations for all three providers and a JSON report without
  keys, signatures, or payloads.

### Task 4: Baseline, Profile, and Minimal Optimization

**Files:**
- Modify only if justified: `src/async_hyperliquid/_signing.py`
- Modify: `tests/unit/test_order_encoding.py`
- Store raw evidence: `.agent/review_artifacts/<timestamp>--rc1-signing-parity-and-benchmark/`

**Interfaces:**
- Preserves: `sign_exchange_action(account, action, vault_address, nonce, signature_source, expires_after=None) -> Signature`.

- [ ] **Step 1: Record the unoptimized benchmark**

  Run at least seven rotating rounds after warmup and save the JSON report in
  the task artifact directory.

- [ ] **Step 2: Profile one-order and batch signing**

  Use `cProfile` around repeated calls and save sorted cumulative-time output.
  Identify whether msgpack, EIP-712 encoding, hashing, or secp256k1 dominates.

- [ ] **Step 3: Write a failing parity test for the selected optimization**

  Extend the fixed vectors across both networks, vault/no-vault, and expiry so
  a faster digest/signing path cannot change `r`, `s`, or `v`.

- [ ] **Step 4: Implement only the measured optimization**

  Prefer module-level immutable precomputation for the constant Exchange
  EIP-712 domain/type data. Do not add a generic signer object or global secret
  cache. If the profile does not justify a clean change, record “no production
  optimization” and leave `_signing.py` unchanged.

- [ ] **Step 5: Re-run the benchmark and apply the retention gate**

  Keep the change only when repeated signing medians improve beyond noise and
  all parity tests remain exact. Otherwise revert only this task's candidate
  edit with `apply_patch`.

### Task 5: Documentation and Full Validation

**Files:**
- Modify: `CHANGELOG.md`
- Modify: `README.md` with a concise benchmark overview and manual link.
- Create: `benchmarks/README.md` as the reproducible operations manual.
- Update and archive: `.agent/state.md`, `.agent/review_notes.md`, and task archives.

**Interfaces:**
- Produces: a reproducible benchmark command and final validation evidence.

- [ ] **Step 1: Document parity and benchmark usage**

  Keep the changelog entry under the existing `1.0.0rc1` section. Document that
  the benchmark is local-only and excludes network/client initialization. Keep
  the full procedure in `benchmarks/README.md`; keep the root README at overview
  level and link to the manual.

- [ ] **Step 2: Run focused and deterministic tests**

  Run oracle, benchmark, signing, and ExchangeClient unit tests, followed by
  the default non-Exchange suite. Do not pass flags that collect Exchange tests.

- [ ] **Step 3: Run formatting and static analysis sequentially**

  Run Ruff, then Ty separately for `src`, `tests`, and `scripts` using Python
  `scripts`, and `benchmarks` using Python 3.12 and the workspace uv cache.

- [ ] **Step 4: Run the final benchmark and review workflow**

  Save final benchmark evidence. Execute the repository-mandated semantic,
  routed, Linus, red-team, rollback, performance, API-contract, and merge
  reviews; resolve all concrete findings.

- [ ] **Step 5: Archive terminal state**

  Create immutable state/review archives with UTC names, compact the two hot
  ledger files, and report changed files, tests, benchmark comparisons, and
  unresolved risks.
