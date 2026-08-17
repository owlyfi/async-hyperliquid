# Dual-Network Info and Vault Parity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run the complete read-only Info integration contract against mainnet and testnet, remove redundant integration switches, and prove subaccount order payload/routing parity for master- and subaccount-rooted clients.

**Architecture:** Keep production behavior unchanged except for private helper names. Put retry/skip policy in one integration-only `InfoClient` subclass, parameterize one fixture across both networks, and keep network-specific market identities in small explicit tables. Prove offline payload equality against the official SDK before exercising the two client identities on testnet.

**Tech Stack:** Python 3.12 pin via uv, asyncio, aiohttp, pytest/pytest-asyncio, TypedDict, eth-account, hyperliquid-python-sdk, Ruff, ty.

## Global Constraints

- Do not add `RUN_INFO_TESTS`, `RUN_MAINNET_INFO_TESTS`, `RUN_EXCHANGE_TESTS`, `RUN_DESTRUCTIVE_EXCHANGE_TESTS`, or replacement opt-in switches.
- `IS_MAINNET` controls only Exchange integration and must hard-fail when true.
- Info integration always executes both `Network.MAINNET` and `Network.TESTNET`.
- Retry the first HTTP 429 after exactly 60 seconds; a second 429 skips the current case.
- TESTNET 5xx warns and skips; MAINNET 5xx and all other failures fail normally.
- Do not change production `InfoClient` error semantics or add compatibility aliases.
- Info tests read public addresses only; private keys are restricted to Exchange fixtures and offline signing parity.
- Every test function in `tests/integration/test_info.py` contains at most four underscores.
- No Copycat changes.

---

### Task 1: Finish the private market-helper naming cleanup

**Files:**
- Modify: `src/async_hyperliquid/client.py:45-120`
- Modify: `tests/unit/test_orders.py:1-115`

**Interfaces:**
- Produces: `_market_price(mid: float, *, is_buy: bool, slippage: float, is_outcome: bool) -> float`
- Produces: `_market_order(order: PlaceOrderRequest, mid: float, *, is_outcome: bool) -> PlaceOrderRequest`
- Removes: `_market_limit_price` and `_market_limit_order`

- [ ] **Step 1: Point the behavior test at the desired private name**

Change the import and existing outcome-price assertion:

```python
from async_hyperliquid.client import _market_order, _market_price


def test_outcome_market_price_stays_in_domain(
    mid: float, is_buy: bool, expected: float
) -> None:
    assert _market_price(
        mid, is_buy=is_buy, slippage=0.05, is_outcome=True
    ) == pytest.approx(expected)
```

- [ ] **Step 2: Run the focused test and verify RED**

Run: `uv run pytest -q tests/unit/test_orders.py -k 'market_price or market_order_normalizes'`

Expected: collection fails because `_market_price` is not defined; the existing `_market_order` test remains green once collection can proceed.

- [ ] **Step 3: Rename the helper and direct call without aliases**

```python
def _market_price(
    mid: float, *, is_buy: bool, slippage: float, is_outcome: bool
) -> float:
    price = mid * (1 + slippage if is_buy else 1 - slippage)
    if not is_outcome:
        return price
    return min(max(price, OUTCOME_MIN_PRICE), OUTCOME_MAX_PRICE)
```

Update `_market_order` to call `_market_price`. Retain the current uncommitted
`_market_limit_order` → `_market_order` change and its real normalization test.

- [ ] **Step 4: Verify GREEN and no stale production names**

Run:

```bash
uv run pytest -q tests/unit/test_orders.py
uv run ty check src/async_hyperliquid tests/unit/test_orders.py
! rg '_market_limit_(price|order)' src tests/unit/test_orders.py
```

Expected: all order tests pass and the old names are absent.

- [ ] **Step 5: Commit**

```bash
git add src/async_hyperliquid/client.py tests/unit/test_orders.py
git commit -m "refactor: simplify market helper names"
```

---

### Task 2: Add bounded Info availability handling for integration only

**Files:**
- Create: `tests/integration/info_client.py`
- Modify: `tests/unit/test_integration.py`

**Interfaces:**
- Produces: `IntegrationInfoClient(network: Network)`
- Produces: `IntegrationInfoClient.network -> Network`
- Consumes: `InfoClient._post(payload: JsonObject) -> JsonValue`

- [ ] **Step 1: Write failing availability-policy tests**

Add tests that patch `InfoClient._post` and `asyncio.sleep`:

```python
async def test_info_retries_one_rate_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    post = AsyncMock(side_effect=[HttpError(429), {"BTC": "100000"}])
    sleep = AsyncMock()
    monkeypatch.setattr(InfoClient, "_post", post)
    monkeypatch.setattr("tests.integration.info_client.asyncio.sleep", sleep)
    client = IntegrationInfoClient(Network.MAINNET)

    assert await client._post({"type": "allMids"}) == {"BTC": "100000"}
    sleep.assert_awaited_once_with(60)
    assert post.await_count == 2


async def test_info_skips_second_rate_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        InfoClient, "_post", AsyncMock(side_effect=[HttpError(429), HttpError(429)])
    )
    monkeypatch.setattr(
        "tests.integration.info_client.asyncio.sleep", AsyncMock()
    )
    with pytest.raises(pytest.skip.Exception, match="rate limited after retry"):
        await IntegrationInfoClient(Network.TESTNET)._post({"type": "allMids"})


async def test_testnet_info_warns_on_server_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(InfoClient, "_post", AsyncMock(side_effect=HttpError(503)))
    with pytest.warns(RuntimeWarning, match="TESTNET allMids returned HTTP 503"):
        with pytest.raises(pytest.skip.Exception):
            await IntegrationInfoClient(Network.TESTNET)._post({"type": "allMids"})


async def test_mainnet_info_fails_on_server_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(InfoClient, "_post", AsyncMock(side_effect=HttpError(503)))
    with pytest.raises(HttpError) as error:
        await IntegrationInfoClient(Network.MAINNET)._post({"type": "allMids"})
    assert error.value.status == 503
```

- [ ] **Step 2: Run the policy tests and verify RED**

Run: `uv run pytest -q tests/unit/test_integration.py -k 'info_'`

Expected: import fails because `tests.integration.info_client` does not exist.

- [ ] **Step 3: Implement the integration client with one retry**

Create `tests/integration/info_client.py` with a slotted subclass that stores
the network, calls `super()._post`, catches only `HttpError`, and follows this
exact branch order:

```python
class IntegrationInfoClient(InfoClient):
    __slots__ = ("_network",)

    def __init__(self, network: Network) -> None:
        super().__init__(network=network)
        self._network = network

    @property
    def network(self) -> Network:
        return self._network

    async def _post(self, payload: JsonObject) -> JsonValue:
        try:
            return await super()._post(payload)
        except HttpError as error:
            if error.status != 429:
                self._handle_unavailable(error, payload)
            await asyncio.sleep(60)
        try:
            return await super()._post(payload)
        except HttpError as error:
            if error.status == 429:
                pytest.skip("Info API remained rate limited after retry")
            self._handle_unavailable(error, payload)

    def _handle_unavailable(self, error: HttpError, payload: JsonObject) -> Never:
        status = error.status
        if self._network is Network.TESTNET and status is not None and 500 <= status < 600:
            request_type = payload.get("type", "unknown")
            warnings.warn(
                f"TESTNET {request_type} returned HTTP {status}",
                RuntimeWarning,
                stacklevel=2,
            )
            pytest.skip(f"TESTNET {request_type} is temporarily unavailable")
        raise error
```

Import `Never` from `typing`. Do not catch `TimeoutError` or `ProtocolError`.

- [ ] **Step 4: Verify GREEN**

Run:

```bash
uv run pytest -q tests/unit/test_integration.py
uv run ruff check tests/integration/info_client.py tests/unit/test_integration.py
uv run ty check tests/integration tests/unit/test_integration.py
```

Expected: policy and existing credential tests pass.

- [ ] **Step 5: Commit**

```bash
git add tests/integration/info_client.py tests/unit/test_integration.py
git commit -m "test: bound info availability retries"
```

---

### Task 3: Parameterize Info and remove redundant execution gates

**Files:**
- Modify: `tests/integration/conftest.py`
- Modify: `tests/integration/exchange/test_actions.py`
- Modify: `tests/integration/exchange/test_orders.py`
- Modify: `tests/package/test_collection.py`
- Modify: `pyproject.toml`

**Interfaces:**
- Produces: session fixture `info: IntegrationInfoClient` with IDs `mainnet`, `testnet`
- Preserves: `hl` as master-address/subaccount-vault Exchange fixture
- Removes: every `RUN_*` integration control and the destructive autouse gate

- [ ] **Step 1: Extend the collection regression before fixture changes**

Add a second subprocess assertion:

```python
def test_info_tests_collect_both_networks() -> None:
    result = _collect("tests/integration/test_info.py")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "test_all_mids[mainnet]" in result.stdout
    assert "test_all_mids[testnet]" in result.stdout
```

Extract the existing subprocess body into `_collect(path: str)` so Exchange
and Info collection share one implementation.

- [ ] **Step 2: Run collection and verify RED**

Run: `uv run pytest -q tests/package/test_collection.py`

Expected: `test_all_mids[mainnet]` and `[testnet]` are absent.

- [ ] **Step 3: Replace opt-ins with a dual-network fixture**

In `conftest.py`, remove `_require_opt_in` and the destructive autouse fixture.
Use:

```python
@pytest_asyncio.fixture(
    scope="session",
    loop_scope="session",
    params=(Network.MAINNET, Network.TESTNET),
    ids=("mainnet", "testnet"),
)
async def info(request: pytest.FixtureRequest) -> AsyncIterator[IntegrationInfoClient]:
    network = cast(Network, request.param)
    async with IntegrationInfoClient(network) as client:
        yield client


def _prepare_exchange() -> None:
    require_testnet(os.environ)
    validate_credentials(os.environ)
```

Remove `pytest.mark.destructive_exchange` from both Exchange modules. Remove
`destructive_exchange` and `mainnet_info` declarations from `pyproject.toml`;
keep the descriptive `info` and `exchange` markers.

- [ ] **Step 4: Verify collection and deterministic safety**

Run:

```bash
uv run pytest -q tests/package/test_collection.py
uv run pytest -q tests/unit tests/contracts tests/oracle tests/public_api tests/package
! rg 'RUN_(INFO|MAINNET_INFO|EXCHANGE|DESTRUCTIVE_EXCHANGE)_TESTS|destructive_exchange|mainnet_info' tests pyproject.toml
```

Expected: both network IDs collect, deterministic paths pass, and deleted
switches/markers are absent.

- [ ] **Step 5: Commit**

```bash
git add tests/integration/conftest.py tests/integration/exchange/test_actions.py tests/integration/exchange/test_orders.py tests/package/test_collection.py pyproject.toml
git commit -m "test: run integration without redundant gates"
```

---

### Task 4: Convert the complete Info suite to the dual-network contract

**Files:**
- Modify: `tests/integration/test_info.py`
- Modify: `tests/integration/exchange/test_orders.py`
- Modify: `tests/contracts/test_coverage.py`

**Interfaces:**
- Consumes: `IntegrationInfoClient.network`
- Produces: explicit HYPE/PURR/USDT0/USDE/USDH mapping assertions
- Produces: AST call-based Info endpoint coverage and the four-underscore rule

- [ ] **Step 1: Write failing coverage and naming contracts**

Change Info integration coverage from `_test_names` to `_called_methods`:

```python
integration = _called_methods(("tests/integration/test_info.py",))
assert methods <= integration
```

Add:

```python
def test_info_integration_names_are_concise() -> None:
    names = _test_names(("tests/integration/test_info.py",))
    assert {name for name in names if name.count("_") > 4} == set()
```

- [ ] **Step 2: Run contracts and verify RED**

Run: `uv run pytest -q tests/contracts/test_coverage.py`

Expected: the concise-name assertion reports the five current noisy names.

- [ ] **Step 3: Make network identity explicit and remove the second mainnet client**

Annotate `info`/`markets` with `IntegrationInfoClient`, remove the local
`mainnet_info` fixture and `RUN_MAINNET_INFO_TESTS`, and change `test_user_role`
to assert each returned discriminator is one of:

```python
{"missing", "user", "vault", "agent", "subAccount"}
```

Ownership checks stay in `_validate_exchange_roles`.

- [ ] **Step 4: Add the exact network mapping assertions**

Use one HYPE mapping keyed by `info.network`:

```python
HYPE_SPOT = {
    Network.MAINNET: ("@107", 10_107),
    Network.TESTNET: ("@1035", 11_035),
}
```

`test_hype_spot_mapping` asserts the protocol coin, asset ID, symbol/metadata,
and `all_mids` price. `test_purr_spot_mapping` asserts named `PURR/USDC` on
both networks and asset `10_000` on mainnet. Add a mainnet-only parameterized
`test_mainnet_spot_mapping` for:

```python
(
    ("USDT0/USDC", "@166", 10_166),
    ("USDE/USDC", "@150", 10_150),
    ("USDH/USDC", "@230", 10_230),
)
```

The test skips its TESTNET parameter before making mapping assertions.

- [ ] **Step 5: Apply the approved concise test names and remove duplicate I/O**

Rename the five functions exactly as specified in the design. Remove the
duplicate `spot = await client.info.spot_meta()` call in `_order_coins` while
touching the integration suite.

- [ ] **Step 6: Verify contracts and the full live Info suite**

Run:

```bash
uv run pytest -q tests/contracts/test_coverage.py
uv run pytest -q tests/integration/test_info.py
uv run ty check tests/integration tests/contracts
```

Expected: every common case has a mainnet and testnet node. A 429 waits once
and then either passes or skips; TESTNET 5xx warns/skips; MAINNET failures fail.

- [ ] **Step 7: Commit**

```bash
git add tests/integration/test_info.py tests/contracts/test_coverage.py tests/integration/exchange/test_orders.py
git commit -m "test: validate info on both networks"
```

---

### Task 5: Pin both subaccount account-address payloads to the official SDK

**Files:**
- Modify: `tests/oracle/test_signing.py`

**Interfaces:**
- Extends: `_sdk_order_payload(..., account_address: str, ...) -> JsonObject`
- Extends: `_async_order_payload(..., account_address: str, signing_key: str, ...) -> JsonObject`

- [ ] **Step 1: Add a failing local-credential parity case**

Add one test that loads `HL_SK`, `HL_AK`, `HL_ADDR`, and `HL_SUB`, validates
the key/address pair, builds the same order for the two root addresses, and
stores both SDK and async payloads:

```python
for account_address in (master_address, subaccount_address):
    sdk_payloads.append(
        _sdk_order_payload(
            account,
            sdk_orders,
            account_address=account_address,
            vault_address=subaccount_address,
            expires_after=None,
            monkeypatch=monkeypatch,
        )
    )
    async_payloads.append(
        await _async_order_payload(
            account_address,
            signing_key,
            async_orders,
            vault_address=subaccount_address,
            expires_after=None,
            monkeypatch=monkeypatch,
        )
    )

assert async_payloads == sdk_payloads
assert async_payloads[0] == async_payloads[1]
assert all(payload["vaultAddress"] == subaccount_address for payload in async_payloads)
```

- [ ] **Step 2: Run the oracle case and verify RED**

Run: `uv run pytest -q tests/oracle/test_signing.py -k subaccount_account_address`

Expected: helper calls fail because neither payload helper accepts the explicit
account address/signing key yet.

- [ ] **Step 3: Generalize the recording helpers without changing payload logic**

Set `SdkExchange.account_address` from the new argument. Construct
`AsyncHyperliquid(account_address, signing_key, vault_address=...)`. Keep the
fixed nonce and recording transports unchanged.

- [ ] **Step 4: Verify complete oracle parity**

Run:

```bash
uv run pytest -q tests/oracle/test_signing.py
uv run ty check tests/oracle
```

Expected: official SDK and async-hyperliquid payloads match for all committed,
native-builder, trigger, and local master/subaccount-rooted cases.

- [ ] **Step 5: Commit**

```bash
git add tests/oracle/test_signing.py
git commit -m "test: pin subaccount order payload parity"
```

---

### Task 6: Prove both account-address roots route live orders to the subaccount

**Files:**
- Modify: `tests/integration/conftest.py`
- Modify: `tests/integration/exchange/test_orders.py`

**Interfaces:**
- Produces: session fixture `sub_hl: AsyncHyperliquid`
- Consumes: `HL_SUB` as both `account_address` and `vault_address`

- [ ] **Step 1: Add two explicit live cases before the second fixture exists**

Extract one cleanup-safe assertion helper and expose two test names:

```python
async def _assert_subaccount_order(
    client: AsyncHyperliquid, subaccount_address: str
) -> None:
    order = await _limit_request(client, "BTC")
    oid: int | None = None
    try:
        response = await client.place_limit_order(order)
        oid = _resting_oid(response)
        status = await client.info.order_status(subaccount_address, oid)
        assert status["status"] == "order"
    finally:
        if oid is not None:
            await _cancel(client, (CancelOrder("BTC", oid),))


async def test_master_address_subaccount_order(
    hl: AsyncHyperliquid, subaccount_address: str
) -> None:
    await _assert_subaccount_order(hl, subaccount_address)


async def test_subaccount_address_order(
    sub_hl: AsyncHyperliquid, subaccount_address: str
) -> None:
    await _assert_subaccount_order(sub_hl, subaccount_address)
```

- [ ] **Step 2: Verify collection RED**

Run: `IS_MAINNET=false uv run pytest -q tests/integration/exchange/test_orders.py::test_subaccount_address_order`

Expected: setup fails with `fixture 'sub_hl' not found` before any request.

- [ ] **Step 3: Add the subaccount-rooted fixture**

```python
@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def sub_hl() -> AsyncIterator[AsyncHyperliquid]:
    _prepare_exchange()
    subaccount = require_env("HL_SUB", os.environ)
    async with AsyncHyperliquid(
        subaccount,
        require_env("HL_SK", os.environ),
        vault_address=subaccount,
        network=Network.TESTNET,
        dexs=_DEXS,
    ) as client:
        await client.info.refresh_metadata()
        await _validate_exchange_roles(client.info)
        yield client
```

- [ ] **Step 4: Execute both real testnet cases and inspect cleanup**

Run:

```bash
IS_MAINNET=false uv run pytest -q \
  tests/integration/exchange/test_orders.py::test_master_address_subaccount_order \
  tests/integration/exchange/test_orders.py::test_subaccount_address_order
```

Then query `open_orders(HL_SUB)` and `positions(HL_SUB)` with `InfoClient` and
assert zero remaining test-created open orders and zero nonzero positions. Do
not print addresses, keys, signatures, or payloads.

- [ ] **Step 5: Commit**

```bash
git add tests/integration/conftest.py tests/integration/exchange/test_orders.py
git commit -m "test: verify subaccount order routing"
```

---

### Task 7: Align documentation and run the final verification matrix

**Files:**
- Modify: `README.md`
- Modify: `CHANGELOG.md`
- Modify: `.github/workflows/ci.yml` only if its explicit deterministic paths need wording changes
- Modify: `tests/package/test_readme.py`

**Interfaces:**
- Documents: no integration `RUN_*` flags, dual-network Info command, and Exchange-only `IS_MAINNET`

- [ ] **Step 1: Update documentation tests first**

Extend `tests/package/test_readme.py` to reject all four removed flag names and
require these commands:

```text
uv run pytest -q tests/integration/test_info.py
IS_MAINNET=false uv run pytest -q tests/integration/exchange
```

- [ ] **Step 2: Run README tests and verify RED**

Run: `uv run pytest -q tests/package/test_readme.py`

Expected: README still contains the removed flags and lacks the dual-network
commands.

- [ ] **Step 3: Update README and changelog with exact execution semantics**

Describe the explicit offline deterministic suite separately from live Info.
State that Info always exercises both networks, 429 retries once after 60
seconds, TESTNET 5xx warns/skips, and Exchange is testnet-only via
`IS_MAINNET=false`.

- [ ] **Step 4: Run fresh final verification**

Run sequentially:

```bash
uv run ruff format --check src tests benchmarks
uv run ruff check src tests benchmarks
uv run ty check src/async_hyperliquid
uv run ty check tests/contracts
uv run ty check tests/integration
uv run ty check tests/oracle
uv run ty check tests/package
uv run ty check tests/public_api
uv run ty check tests/typing
uv run ty check tests/unit
uv run ty check benchmarks
uv run pytest -q tests/unit tests/contracts tests/oracle tests/public_api tests/package
uv run pytest -q tests/integration/test_info.py
uv build --no-sources
git diff --check
```

Run the two focused Exchange cases again only if source or their fixture/order
paths changed after Task 6. Record pass/skip/warning counts without secrets.

- [ ] **Step 5: Commit**

```bash
git add README.md CHANGELOG.md .github/workflows/ci.yml tests/package/test_readme.py
git commit -m "docs: describe dual-network integration tests"
```

- [ ] **Step 6: Archive task and review state**

Create terminal `.agent/state_archive/` and `.agent/review_archive/` records,
rewrite the hot snapshots to one last-archive pointer, and include exact test,
live-network, cleanup, and rollback evidence.
