# Hyperliquid API Contract and Live Tests Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Align the v1 public API with Hyperliquid's documented Info and Exchange contracts, restore every user-added integration scenario, establish one typed order-request vocabulary with `is_buy` and `cloid`, and enforce a testnet-only live-validation boundary.

**Architecture:** `InfoClient` owns credential-free reads and read-only metadata helpers. `ExchangeClient` owns direct signed actions where one public call produces one Exchange action; `AsyncHyperliquid` owns workflows that combine Info reads with one or more Exchange actions. Live tests use separate master and API-wallet clients, never infer signing authority from endpoint URLs, and never execute Exchange integration during this implementation pass.

**Tech Stack:** Python 3.12 via uv pin, aiohttp, eth-account, pytest/pytest-asyncio, Ruff, Ty, Hyperliquid HTTP APIs.

## Global Constraints

- Do not delete `tests/integration/test_info.py`, `tests/integration/exchange/test_orders.py`, `tests/integration/exchange/test_actions.py`, or the behavioral scenarios the user added.
- Do not execute the Exchange integration suite in this implementation pass.
- All live clients are explicitly `Network.TESTNET`; `IS_MAINNET=true` must fail before an Exchange client or request is created.
- `.env.local` remains ignored and no test, assertion message, log, or exception may include `HL_PK` or `HL_SK`.
- `HL_ADDR` is the master address; `HL_PK` is its private key; `HL_AK` is the API-wallet address; `HL_SK` is the API-wallet private key; `HL_SUB` is the Hyperliquid subaccount.
- Preserve custom/self-hosted/third-party `info_url` and `exchange_url`; only `Network` selects the signing domain.
- Use `TypedDict` for JSON-shaped SDK requests, wire actions, and responses;
  use frozen slotted dataclasses only for value-style inputs such as `Builder`.
  Do not add runtime response wrappers.
- Use `is_buy: bool`; do not retain or replace `Side` with another enum.
- Keep only root `place_order` expanded for 0.5 source compatibility; direct
  Exchange and batch order APIs accept typed request mappings.
- Use `dex`/`dexs` for public request parameters. Close workflows always close
  the full live size and expose neither size nor slippage controls.
- Keep Copycat out of this repository. Record its migration impact only in the migration guide.

---

## Strategic Direction

### Success standards

- Every public `InfoClient` endpoint/helper has deterministic coverage and a named live integration case.
- Every public `ExchangeClient` action has deterministic envelope/signature coverage and a named, testnet-only integration case, even though those live cases remain unexecuted for this pass.
- The mandatory GitBook Exchange actions are all represented by public methods. Current official-SDK extensions already exposed by this package remain available and tested.
- `AsyncHyperliquid.place_order(...)`, `place_orders(...)`, and the exact
  `batch_place_orders` alias remain intent-level entry points. For source
  compatibility, only root `place_order(...)` retains its expanded 0.5 call
  shape; root batch methods and direct Exchange methods consume
  `PlaceOrderRequest` mappings. The expanded method constructs that same typed
  request once before dispatch, so there is still one order vocabulary.
- The default and CI suites never send signed Exchange actions.
- `IS_MAINNET=true` produces an immediate explicit failure when an Exchange live fixture is selected.
- `AsyncHyperliquid` contains only resource ownership and genuine cross-capability workflows; it does not forward raw Info/Exchange methods.

### P10 workstream boundaries

- **P10-A — API contract and ownership:** public signatures, `is_buy`, action schemas/signing, high-level workflow placement, unit/contracts/public-surface tests.
- **P10-B — live validation and safety:** `.env.local` role validation, Info live cases, preservation/migration of Exchange integration scenarios, markers and mainnet fail-fast behavior.
- **Interface between workstreams:** P10-A freezes method names/signatures first; P10-B targets only that manifest. Neither workstream changes the other's contract implicitly.

### Deliberate exclusions

- No Exchange live request, even a nominally harmless `noop`, is executed in this pass.
- No mainnet live test is enabled. Existing mainnet-specific Info scenarios are retained but marked inactive while the testnet lock is in force.
- No WebSocket, Copycat, deployment, retry, provider-fallback, or key-management framework is added.
- No generic `execute(action: dict)` escape hatch is added; it would discard typing and make coverage unverifiable.

---

## Target Ownership and Public Interfaces

### `InfoClient`

Keep direct Info endpoints and the existing read helpers on `InfoClient`. The standalone constructor remains the zero-credential path. Account queries receive the actual `HL_ADDR` or `HL_SUB`; they must not use `HL_AK`, because an API-wallet address has no master/subaccount portfolio.

Public request/configuration parameter names follow the protocol: `dex` for one
DEX and `dexs` for a sequence. `AsyncHyperliquid.__init__` exposes
`dexs: tuple[str, ...] = ("",)`, and the Info helpers use:

```python
async def account_state(
    self,
    account_address: str,
    *,
    dexs: tuple[str, ...] = ("",),
) -> AccountState: ...

async def positions(
    self,
    account_address: str,
    *,
    dexs: tuple[str, ...] = ("",),
) -> list[Position]: ...
```

Remove public parameters named `perp_dexs` or `perp_dexes`; do not keep alias
kwargs. The `InfoClient.perp_dexes()` method remains because it names the
official `perpDexs` query/result, not a request parameter. Root workflows own
the configured `dexs`; `ExchangeClient` no longer stores a DEX list after close
orchestration moves out of it.

### `ExchangeClient`

One public method must construct and submit one documented Exchange action. Symbol-to-asset and decimal lookup through the bound `InfoClient` is allowed because it is protocol encoding, not business orchestration.

Mandatory direct-action surface:

- Orders: `place_limit_order`, `place_trigger_order`, `place_market_order`,
  `place_market_orders`, `place_orders`, `cancel_order`, `cancel_orders`,
  `cancel_by_cloid`, `cancel_orders_by_cloid`, `schedule_cancel`,
  `modify_order`, `modify_orders`, `update_leverage`,
  `update_isolated_margin`, `place_twap`, `cancel_twap`.
- Transfers/staking: `send_asset`, `agent_send_asset`, `send_to_evm_with_data`, `usd_transfer`, `spot_transfer`, `withdraw`, `usd_class_transfer`, `staking_deposit`, `staking_withdraw`, `token_delegate`, `vault_transfer`, `hip3_liquidator_transfer`.
- Authorization/operations: `approve_agent`, `approve_builder_fee`, `reserve_request_weight`, `noop`, `user_dex_abstraction`, `agent_enable_dex_abstraction`, `user_set_abstraction`, `agent_set_abstraction`.
- Outcomes/AQA: `split_outcome`, `merge_outcome`, `merge_question`, `negate_outcome`, `vote_risk_free_rate`, `authorize_aqav2_role`, `claim_rewards`.
- Retained official-SDK extensions: `set_referrer_code`, `create_sub_account`, `use_big_blocks`, `convert_to_multi_sig_user`.

`modify_order` must encode action type `modify`; `modify_orders` must encode `batchModify`. A single-action method may share a private encoder, but public methods must not forward through another public method.

All direct order methods consume the same command model; the method name states
the operation and the request object carries its data:

```python
async def place_limit_order(
    self,
    order: PlaceOrderRequest,
    *,
    builder: Builder | None = None,
    expires_after: int | None = None,
) -> PlaceOrderResponse: ...

async def place_trigger_order(
    self,
    order: PlaceOrderRequest,
    *,
    builder: Builder | None = None,
    expires_after: int | None = None,
) -> PlaceOrderResponse: ...

async def place_market_order(
    self,
    order: PlaceOrderRequest,
    *,
    builder: Builder | None = None,
    expires_after: int | None = None,
) -> PlaceOrderResponse: ...

async def place_orders(
    self,
    orders: Sequence[PlaceOrderRequest],
    *,
    grouping: OrderGrouping = OrderGrouping.NA,
    builder: Builder | None = None,
    expires_after: int | None = None,
) -> PlaceOrderResponse: ...

async def place_market_orders(
    self,
    orders: Sequence[PlaceOrderRequest],
    *,
    grouping: OrderGrouping = OrderGrouping.NA,
    builder: Builder | None = None,
    expires_after: int | None = None,
) -> PlaceOrderResponse: ...

async def modify_order(
    self,
    order: ModifyOrderRequest,
    *,
    expires_after: int | None = None,
) -> PlaceOrderResponse: ...

async def modify_orders(
    self,
    orders: Sequence[ModifyOrderRequest],
    *,
    expires_after: int | None = None,
) -> PlaceOrderResponse: ...
```

Do not add expanded overloads for these methods. That would preserve two public
contracts and recreate the drift this model removes.

Each explicit method rejects only a contradictory discriminator before any
metadata lookup: limit accepts a limit/missing `order_type`, trigger requires a
trigger `order_type`, and market requires `is_market` to be missing/true. The
batch counterparts apply the same rule to every item. Keep value/precision
checks in the shared encoder; do not duplicate validation in the root client.

### `AsyncHyperliquid`

Keep the original intent-level order entry points. They are dispatchers, not raw
endpoint forwarding: `is_market` selects price discovery versus typed-order
construction, and `order_type` selects limit versus trigger encoding.

```python
async def place_order(
    self,
    coin: str,
    is_buy: bool,
    sz: float,
    px: float,
    is_market: bool = True,
    *,
    ro: bool = False,
    order_type: OrderType | None = None,
    cloid: Cloid | None = None,
    slippage: float = 0.05,
    builder: Builder | None = None,
    expires_after: int | None = None,
) -> PlaceOrderResponse: ...

async def place_orders(
    self,
    orders: Sequence[PlaceOrderRequest],
    *,
    grouping: OrderGrouping = OrderGrouping.NA,
    builder: Builder | None = None,
    expires_after: int | None = None,
) -> PlaceOrderResponse: ...

batch_place_orders = place_orders

async def close_position(
    self,
    coin: str,
    *,
    builder: Builder | None = None,
    expires_after: int | None = None,
) -> PlaceOrderResponse | None: ...

async def close_positions(
    self,
    coins: Sequence[str] | None = None,
    *,
    dexs: tuple[str, ...] | None = None,
    builder: Builder | None = None,
    expires_after: int | None = None,
) -> PlaceOrderResponse | None: ...

async def close_all_positions(
    self,
    *,
    dexs: tuple[str, ...] | None = None,
    builder: Builder | None = None,
    expires_after: int | None = None,
) -> PlaceOrderResponse | None: ...
```

`place_order(...)` is the single compatibility exception to the request-object
rule. It constructs one local `PlaceOrderRequest` from the expanded arguments,
then dispatches directly without calling another public root method. A market
call uses `slippage`, ignores `px` and `order_type` for quote construction, and
calls `ExchangeClient.place_market_order` exactly once. With
`is_market=False`, `order_type=None` is normalized to
`{"limit": {"tif": TimeInForce.IOC}}`; a `LimitOrderType` calls
`ExchangeClient.place_limit_order`, and a `TriggerOrderType` calls
`ExchangeClient.place_trigger_order`. The root performs selection and input
translation only. Each Exchange method owns metadata/price encoding, signing,
and its single POST.

`place_orders` preserves input order and partitions no work: all commands must
have the same `is_market` value. It calls `ExchangeClient.place_market_orders`
once for a market batch and `ExchangeClient.place_orders` once for a typed
limit/trigger batch. Mixed market/typed batches fail before metadata lookup;
callers split them into two requests because they require different price
construction semantics.
`batch_place_orders = place_orders` is a class-level alias to the same function
object, not an async forwarding wrapper.
`close_positions` is the one canonical close workflow. It reads the immutable
execution target (`vault_address`/subaccount when configured), fetches positions
exactly once, filters by `coins` when supplied, constructs every full-size
reduce-only market command, and calls `ExchangeClient.place_market_orders`
exactly once. `coins=None` means all positions within `dexs`; an empty sequence
is a no-op. Deduplicate requested coins while preserving first occurrence and
emit close orders in that order; missing or already-flat coins add no order.
When `coins` is supplied and `dexs` is omitted, derive the minimal DEX set from
the coin names (`BTC -> ""`, `xyz:NVDA -> "xyz"`). Otherwise use the explicit
`dexs`, or the client's configured `dexs` for the all-position case.

`close_position(coin)` directly returns `close_positions((coin,), ...)`.
`close_all_positions(dexs=...)` directly returns
`close_positions(None, dexs=dexs, ...)`. Neither wrapper fetches positions, so
there is no duplicate Info request. They intentionally delegate to the one
workflow because this is semantic API convergence, not a raw endpoint facade.
Remove the old `ExchangeClient.close_positions` only after these root workflows
and public migration tests exist.

Close APIs do not expose `size` or `slippage`: close means the complete live
position, and immediate-market price protection is an internal Exchange
encoding policy. A partial reduce-only trade remains available through
`place_order`. Never implement close batches as `asyncio.gather` over individual
orders; submit one order action containing the full batch. If multiple DEX
position reads are required, `InfoClient.positions` may issue those reads
concurrently because the protocol has no multi-DEX account-state batch request;
that concurrency must not leak into signed order submission.

### Order command model

Use these exact input fields/signatures:

```python
class LimitOrderOption(TypedDict):
    tif: TimeInForce


class LimitOrderType(TypedDict):
    limit: LimitOrderOption


class TriggerOrderOption(TypedDict):
    isMarket: bool
    triggerPx: str
    tpsl: Literal["tp", "sl"]


class TriggerOrderType(TypedDict):
    trigger: TriggerOrderOption


OrderType: TypeAlias = LimitOrderType | TriggerOrderType


@dataclass(frozen=True, slots=True)
class Builder:
    address: str
    fee_tenths_bps: int


class BaseOrderRequest(TypedDict):
    coin: str
    is_buy: bool
    sz: float
    px: float
    cloid: NotRequired[Cloid | None]


class PlaceOrderRequest(BaseOrderRequest):
    is_market: NotRequired[bool]
    ro: NotRequired[bool]
    order_type: NotRequired[OrderType | None]
    slippage: NotRequired[float]


class ModifyOrderRequest(BaseOrderRequest):
    oid: int | Cloid
    ro: NotRequired[bool]
    order_type: NotRequired[OrderType | None]
```

`OrderType` is exactly the documented `LimitOrderType | TriggerOrderType`
TypedDict union. `TimeInForce` is only the nested `limit.tif` value and is never
accepted as a top-level order type. `limit_order_type(TimeInForce.IOC)` and
`trigger_order_type(...)` remain the typed constructors for callers that do not
want to write the nested dictionaries directly.

The two market flags have different responsibilities: top-level `is_market`
selects immediate market-price discovery in `AsyncHyperliquid`, while
`order_type["trigger"]["isMarket"]` is the documented trigger execution mode.
A trigger placement therefore uses top-level `is_market=False` even when its
nested `isMarket` is true.

`BaseOrderRequest` is the only declaration of `coin`, `is_buy`, `sz`, `px`, and
`cloid`. The last field is optional at the public boundary but still belongs to
the shared schema. `PlaceOrderRequest` adds placement semantics;
`ModifyOrderRequest` adds the existing order identifier and typed replacement
semantics. Optional keys use `NotRequired`; methods apply the SDK defaults
`is_market=True`, `ro=False`, `order_type=None`, and `slippage=0.05` without
mutating the caller's mapping. Remove
`LimitOrder`, `TriggerOrder`, `MarketOrder`, and `ModifyOrder`; order kind is
already represented by `is_market` plus the `OrderType` discriminator, so a
second class hierarchy would duplicate the protocol. All public order methods
except the compatibility root `place_order` accept these request objects as a
whole and never expose the same fields again as expanded parameters. Root
`place_order` immediately constructs this exact `TypedDict`; it does not define
a second model. Do not accept a parallel `dict[str, object]` type; the
`TypedDict` is the dictionary contract wherever a mapping crosses a method
boundary.

The public vocabulary is `cloid` everywhere, including `CancelByCloid`; remove
`client_order_id` from source, exports, tests, examples, and migration docs.
Only the human-readable `Cloid` docstring may explain that the value is a client
order ID. `ExchangeClient.place_twap` takes `is_buy: bool`. `encode_order`
writes `b=order["is_buy"]`. Info response fields named `side` remain unchanged
because they are wire data, not command inputs.
Every public placement/close method that supports builder attribution uses the
keyword `builder: Builder | None`.
Only the official `approve_builder_fee` action retains `builder_fee` in its
method name; internal wire fields continue to follow the protocol.

---

### Task 1: Establish testnet credential and collection safety

**Files:**
- Create: `tests/integration/conftest.py`
- Modify: `tests/conftest.py`
- Modify: `pyproject.toml`
- Modify: `README.md`
- Test: `tests/unit/test_live_test_config.py`

**Interfaces:**
- Produces fixtures `live_info`, `master_hl`, `api_hl`, `master_address`, `api_wallet_address`, and `subaccount_address`.
- `live_info` uses `InfoClient(network=Network.TESTNET)` and no private key.
- `master_hl` uses `AsyncHyperliquid(HL_ADDR, HL_PK, network=Network.TESTNET)`.
- `api_hl` uses `AsyncHyperliquid(HL_ADDR, HL_SK, vault_address=HL_SUB, network=Network.TESTNET)`.

- [ ] Load `.env.local` with `override=False` only inside integration configuration.
- [ ] Implement `_required_env(name)` with an error containing only the missing variable name.
- [ ] Before constructing either Exchange fixture, fail with `pytest.UsageError` when `IS_MAINNET.lower() == "true"`; do not downgrade this case to skip.
- [ ] Validate `Account.from_key(HL_PK).address == HL_ADDR` and `Account.from_key(HL_SK).address == HL_AK` without formatting either private key into output.
- [ ] Validate `HL_SUB` as an Ethereum address.
- [ ] Require explicit `RUN_LIVE_INFO_TESTS=true` for the Info fixture and `RUN_LIVE_EXCHANGE_TESTS=true` for Exchange fixtures.
- [ ] Register `live_info`, `live_exchange`, `destructive_exchange`, and `mainnet_info` markers.
- [ ] Remove `--capture=no`; tests should not print responses or account state by default.
- [ ] Keep CI's deterministic command explicitly outside `tests/integration`.
- [ ] Unit-test missing variables, key/address mismatches, and the `IS_MAINNET=true` fail-fast path using fake values only.

Validation:

```bash
uv run pytest -q tests/unit/test_live_test_config.py
uv run ruff check tests/conftest.py tests/integration/conftest.py tests/unit/test_live_test_config.py
uv run ty check tests/integration/conftest.py tests/unit/test_live_test_config.py
```

### Task 2: Migrate the user-added integration tests before production changes

**Files:**
- Modify in place: `tests/integration/test_info.py`
- Modify in place: `tests/integration/exchange/test_orders.py`
- Modify in place: `tests/integration/exchange/test_actions.py`
- Do not recreate: deleted legacy `tests/integration/test_exchange_orders.py`

**Interfaces:**
- Consumes the fixtures from Task 1 and the target signatures in this plan.
- Produces named live cases using `test_live_<public_method>` naming.

- [ ] Preserve every user-added scenario; replace obsolete 0.5 imports and flat `hl.<endpoint>` calls instead of deleting tests.
- [ ] Rewrite Info calls to `live_info.<method>` and pass `HL_ADDR`/`HL_SUB` explicitly for account queries.
- [ ] Rewrite direct Exchange actions to `api_hl.exchange.<method>` or `master_hl.exchange.<method>` according to signer authority.
- [ ] Preserve the behavior of every existing `api_hl.place_order(...)` and
  `api_hl.batch_place_orders(...)` scenario while annotating each payload as
  `PlaceOrderRequest`. Keep `api_hl.place_order(**payload)` for the expanded
  compatibility API; pass mappings directly to `place_orders` and
  `batch_place_orders`. Add the equivalent `api_hl.place_orders(...)` case;
  cover `api_hl.close_position(...)`, `api_hl.close_positions(...)`, and
  `api_hl.close_all_positions()`.
- [ ] Keep action-level `builder` outside `PlaceOrderRequest`: migrate existing
  payloads containing it to a separate `builder=builder` keyword on the root or
  batch call.
- [ ] Use the same `PlaceOrderRequest` commands in direct `.exchange` order
  tests. Migrate modify scenarios to `ModifyOrderRequest`, use `cloid` in every
  request/cancel assertion, and remove every `# type: ignore`.
- [ ] Rename every public request argument in the preserved scenarios from
  `perp_dexs`/`perp_dexes` to `dexs`; keep `perp_dexes()` only where the test is
  explicitly calling that Info endpoint/helper.
- [ ] Replace every `pass` and `print` with a shape/invariant assertion.
- [ ] Wrap order/TWAP lifecycle scenarios in `try/finally` cleanup so a later opt-in run cannot strand open orders.
- [ ] Mark transfer, withdrawal, staking, delegation, authorization, abstraction, outcome, and AQA mutations as `destructive_exchange` in addition to `live_exchange`.
- [ ] Retain mainnet-only alias/price scenarios under `mainnet_info`, but keep that marker excluded while testnet lock is active.
- [ ] Do not execute or collect `tests/integration/exchange` as a pytest validation step in this pass. Ruff and Ty may statically check the files.

Expected RED evidence: `tests/integration/test_info.py` currently fails collection because it imports removed `get_is_mainnet`; the rewritten tests should then expose missing target APIs through static checking/unit contract tests rather than live Exchange execution.

### Task 3: Establish the canonical order command model

**Files:**
- Modify: `src/async_hyperliquid/types/common.py`
- Modify: `src/async_hyperliquid/types/exchange.py`
- Modify: `src/async_hyperliquid/types/__init__.py`
- Modify: `src/async_hyperliquid/_signing.py`
- Modify: `src/async_hyperliquid/exchange.py`
- Modify: all order/typing/public API tests containing `Side`

**Interfaces:**
- Produces `LimitOrderOption`, `TriggerOrderOption`, `OrderType`,
  `BaseOrderRequest`, `PlaceOrderRequest`, `ModifyOrderRequest`, and the
  `place_twap(..., is_buy: bool, ...)` signature defined above.

- [ ] First update command/public-signature tests to require the singular
  `LimitOrderOption` and `TriggerOrderOption` names, require `is_buy`, and
  require `Side` to be absent from package exports.
- [ ] Run focused tests and retain the expected failures as RED evidence.
- [ ] Replace `LimitOrder`, `TriggerOrder`, `MarketOrder`, and `ModifyOrder`
  with the base/request TypedDicts above. Declare `coin`, `is_buy`, `sz`,
  `px`, and `cloid` exactly once on `BaseOrderRequest`; do not repeat their
  annotations on either subclass.
- [ ] Change all encoders to consume `BaseOrderRequest` fields directly. Do not
  convert a request to a second internal command object before encoding.
- [ ] Rename the public `BuilderFee` command to `Builder` and rename every
  public order/workflow parameter from `builder_fee` to `builder`; keep the
  explicit `fee_tenths_bps` field.
- [ ] Export the concrete `OrderType`, `LimitOrderType`, and
  `TriggerOrderType` TypedDicts, their singular option TypedDicts, the request
  TypedDicts, plus `limit_order_type` and `trigger_order_type` constructors.
- [ ] Rename `CancelByCloid.client_order_id` to `cloid`; make
  `rg -n "client_order_id|LimitOrderOptions|TriggerOrderOptions" src tests
  README.md CHANGELOG.md docs/migration-0.5-to-1.0.md` return no code/API
  occurrences. Historical implementation plans are immutable evidence and are
  excluded from this scan.
- [ ] Keep internal encoded option type names singular as well; do not replace
  the public names with `*Options` aliases.
- [ ] Add public-signature/type tests proving `TimeInForce` is valid only at
  `order_type["limit"]["tif"]`, not as `order_type` itself.
- [ ] Add typing fixtures assigning both concrete requests to
  `BaseOrderRequest` and checking the exact five shared field types. Review the
  declarations for zero duplicated annotations; do not add runtime
  `__annotations__` introspection merely to test inheritance syntax. Prove
  direct Exchange and batch methods accept request mappings; separately freeze
  the exact expanded root `place_order` compatibility signature.
- [ ] Keep `TimeInForce`, `TriggerKind`, `OrderGrouping`, and wire-response `side` fields; they represent more than a binary input choice or are protocol output.
- [ ] Update README, changelog, migration guide, typing fixtures, and benchmarks.
- [ ] Run focused tests, Ruff, and Ty until green.

Validation:

```bash
uv run pytest -q tests/unit/types tests/unit/test_order_encoding.py tests/public_api tests/typing
uv run ruff check src tests scripts
uv run ty check src/async_hyperliquid
uv run ty check tests
```

### Task 4: Enforce direct-action versus workflow ownership

**Files:**
- Modify: `src/async_hyperliquid/client.py`
- Modify: `src/async_hyperliquid/exchange.py`
- Create: `tests/unit/test_place_order.py`
- Create: `tests/unit/test_close_positions.py`
- Modify: `tests/unit/test_exchange_client.py`
- Modify: `tests/unit/test_info_client.py`
- Modify: `tests/unit/test_metadata.py`
- Modify: `tests/public_api/test_surface.py`
- Modify: `tests/unit/test_client_hotpath_benchmark.py`

**Interfaces:**
- Produces root workflow signatures defined above.
- Produces singular direct methods `place_limit_order`, `place_trigger_order`,
  `place_market_order`, `cancel_order`, `cancel_by_cloid`, and `modify_order`
  alongside their batch forms.
- Produces `dex`/`dexs` public request naming and removes DEX-list ownership
  from `ExchangeClient`.

The canonical close workflow constructs one batch with this exact shape; `px`
is the required market-command placeholder and is ignored by the market
encoder:

```python
orders: list[PlaceOrderRequest] = [
    {
        "coin": coin,
        "is_buy": position_size < 0,
        "sz": abs(position_size),
        "px": 0.0,
        "is_market": True,
        "ro": True,
    }
    for coin, position_size in selected_positions
]
return await self.place_market_orders(
    orders,
    builder=builder,
    expires_after=expires_after,
)
```

Freeze the one-read/one-submit behavior with assertions equivalent to:

```python
await client.close_positions(("BTC", "xyz:NVDA"), builder=builder)

info.positions.assert_awaited_once_with(
    execution_address,
    dexs=("", "xyz"),
)
exchange.place_market_orders.assert_awaited_once()
orders = exchange.place_market_orders.await_args.args[0]
assert [order["coin"] for order in orders] == ["BTC", "xyz:NVDA"]
assert all(order["ro"] and order["is_market"] for order in orders)
```

- [ ] Restore RED routing coverage from the pre-refactor
  `tests/unit/test_place_order.py` using the expanded root call: market
  dispatch, typed limit dispatch, trigger dispatch, default IOC, builder/cloid
  propagation, one `PlaceOrderRequest` construction, and batch input order.
- [ ] Include a trigger case with top-level `is_market=False` and nested
  `trigger.isMarket=True`; prove it routes to `place_trigger_order`, not the
  immediate-market path.
- [ ] Add RED public-surface tests requiring root `place_order`,
  `place_orders`, `batch_place_orders`, `close_position`, `close_positions`,
  and `close_all_positions`; prove
  `ExchangeClient` retains the three explicit order-kind methods but has no
  `close_positions` workflow.
- [ ] Add an identity assertion that
  `AsyncHyperliquid.batch_place_orders is AsyncHyperliquid.place_orders`; test
  behavior once through each public name without implementing a forwarding
  wrapper.
- [ ] Add envelope tests proving `modify_order` emits `type="modify"` while `modify_orders` emits `type="batchModify"`.
- [ ] Add signature tests freezing expanded root `place_order` exactly as
  defined above. Prove direct Exchange methods accept `PlaceOrderRequest`, root
  and direct batch methods accept `Sequence[PlaceOrderRequest]`, modify methods
  accept `ModifyOrderRequest`, and no direct method provides an expanded
  compatibility overload.
- [ ] Implement root `place_order` as a direct dispatcher with exactly one
  Exchange call: market -> `place_market_order`, limit -> `place_limit_order`,
  trigger -> `place_trigger_order`. Construct one local `PlaceOrderRequest`
  from the expanded arguments and pass it once; the selected encoder treats
  `order_type=None` as IOC limit.
- [ ] Implement canonical `place_orders` with exactly one Exchange call:
  market -> `place_market_orders`, typed limit/trigger -> `place_orders`.
- [ ] Reject an empty batch and a batch mixing market and typed requests before
  metadata lookup; do not partition it into multiple signed actions.
- [ ] Bind `batch_place_orders = place_orders` in the class body after the
  canonical method definition.
- [ ] Keep mid-price lookup, IOC price calculation, metadata encoding, signing,
  and POST inside the selected Exchange method; root must not reimplement them.
- [ ] Rename the public constructor and Info request parameters to `dexs`; keep
  singular endpoint arguments as `dex`. Store configured `dexs` on
  `AsyncHyperliquid`, remove `_perp_dexes`/`_dexs` from `ExchangeClient`, and
  update public-surface, Info, metadata, migration, and benchmark tests.
- [ ] Move positions orchestration to canonical root `close_positions`; do not
  add root forwarding for raw Info/Exchange endpoints. `coins=None` closes all
  positions in the selected/configured DEX set, while an empty sequence returns
  `None` without Info or Exchange calls.
- [ ] Make `close_position` call `close_positions((coin,), ...)` and make
  `close_all_positions` call `close_positions(None, dexs=dexs, ...)`. Assert
  each public call causes exactly one `InfoClient.positions` invocation; the
  wrappers must not prefetch.
- [ ] Ensure the canonical close workflow queries `HL_SUB` when the client has
  `vault_address=HL_SUB`, derives the minimal DEX set for specified coins,
  filters returned positions, and creates full-size reduce-only requests with
  `is_buy = position_size < 0`, `is_market=True`, and no public
  size/slippage override.
- [ ] Submit all close requests through one
  `ExchangeClient.place_market_orders` call. Assert one metadata lookup batch,
  one mid-price lookup batch, and one signed Exchange POST; forbid
  `asyncio.gather`/per-order Exchange calls in this workflow.
- [ ] Preserve concurrent per-DEX Info reads inside `InfoClient.positions`
  because the protocol has no multi-DEX state request, but only query the DEXs
  needed by the close request.
- [ ] Update migration docs to state that `place_order`, `place_orders`, and
  the `batch_place_orders` alias remain at the root, while direct protocol
  actions move to `.exchange`; document the `builder_fee` -> `builder` rename
  and `client_order_id` -> `cloid` rename, expanded root versus typed batch
  call shapes, `perp_dexs`/`perp_dexes` -> `dexs`, and migrate
  `client.exchange.close_positions(...)` to root workflows.

Validation:

```bash
uv run pytest -q tests/unit/test_place_order.py tests/unit/test_close_positions.py tests/unit/test_exchange_client.py tests/unit/test_info_client.py tests/unit/test_metadata.py tests/public_api/test_surface.py tests/unit/test_client_hotpath_benchmark.py
```

### Task 5: Complete the documented Exchange action surface

**Files:**
- Modify: `src/async_hyperliquid/exchange.py`
- Modify: `src/async_hyperliquid/_signing.py`
- Modify: `src/async_hyperliquid/types/exchange.py`
- Modify: `src/async_hyperliquid/types/__init__.py` only for reusable public command types
- Modify: `tests/unit/test_exchange_client.py`
- Modify: `tests/unit/test_action_failures.py`
- Modify: `tests/contracts/fixtures/exchange-responses.json`

**Interfaces:**
- Add the missing mandatory methods listed in the `ExchangeClient` target surface.
- Use keyword-only arguments for `send_to_evm_with_data` fields after `coin` and `amount`.
- Use `Literal["hex", "base58"]` for address encoding and `Literal["technical", "treasury"]` for AQAv2 roles; do not add enums for two protocol literals.
- Use `float | None` for merge amounts where `None` means protocol `null`/maximum.

- [ ] Freeze one request/action fixture per official action type before implementation.
- [ ] Implement `agent_send_asset` with the same nonce in the inner action and outer envelope.
- [ ] Implement `send_to_evm_with_data` as a user-signed action with typed token/amount/source/destination/data fields.
- [ ] Implement `hip3_liquidator_transfer` with exact 1e-6 notional conversion and the documented multiple constraint.
- [ ] Implement `noop`, outcome actions, risk-free-rate vote, AQAv2 authorization, and reward claim as direct typed actions.
- [ ] Preserve `expires_after` only on actions for which the official contract supports it; do not append it to user-signed transfers.
- [ ] Keep current official-SDK extensions and give each a deterministic test; do not claim they are GitBook-mandatory.
- [ ] Add malformed-acknowledgement and indeterminate-post tests for every new response family; reuse `DefaultActionResponse` where the wire contract is the same.

Validation:

```bash
uv run pytest -q tests/unit/test_exchange_client.py tests/unit/test_action_failures.py tests/contracts
uv run ruff check src/async_hyperliquid tests/unit tests/contracts
uv run ty check src/async_hyperliquid
```

### Task 6: Close Info and Exchange test coverage mechanically

**Files:**
- Create: `tests/contracts/test_endpoint_coverage.py`
- Modify: `tests/unit/test_info_client.py`
- Modify: `tests/unit/test_metadata.py`
- Modify: `tests/unit/test_exchange_client.py`
- Modify: the three live integration files

**Interfaces:**
- The coverage test compares public coroutine names against `test_live_<method>` cases.
- Exclude only lifecycle (`open`, `close`, context-manager methods), properties, and private methods from endpoint coverage.

- [ ] Give every public Info endpoint/helper a named deterministic test and named live case.
- [ ] Give every public Exchange action a named envelope/signature test and named testnet live case.
- [ ] Make the coverage gate fail when a future public coroutine is added without both deterministic and live coverage declarations.
- [ ] For live Info cases, derive test coins, token IDs, and DEX names from testnet metadata instead of hardcoding mainnet-only asset IDs/prices.
- [ ] Use `HL_ADDR` and `HL_SUB` for portfolio/state queries and use `HL_AK` only for the API-wallet role query/key-consistency assertion.
- [ ] When a valid testnet resource does not exist (vault, open order, outcome, validator role), assert the documented empty/unknown response or skip with the missing protocol capability—not with a generic exception catch.

Validation:

```bash
uv run pytest -q tests/contracts/test_endpoint_coverage.py tests/unit/test_info_client.py tests/unit/test_metadata.py tests/unit/test_exchange_client.py
RUN_LIVE_INFO_TESTS=true uv run pytest -q tests/integration/test_info.py
```

Do not run a pytest command containing `tests/integration/exchange` in this task.

### Task 7: Documentation, full non-Exchange verification, and review

**Files:**
- Modify: `README.md`
- Modify: `CHANGELOG.md`
- Modify: `docs/migration-0.5-to-1.0.md`
- Modify: `.github/workflows/ci.yml` only if its deterministic path needs explicit integration exclusion

- [ ] Document the five `.env.local` identities without showing example secrets.
- [ ] Correct every README use of `HL_AK` as a private key to `HL_SK`; show master-only actions with `HL_PK` and API-wallet/subaccount trading with `HL_SK` + `HL_SUB`.
- [ ] Document that API-wallet addresses sign but must not be used to query master/subaccount state.
- [ ] Document the direct-action/workflow ownership rule and the `Side` to `is_buy` migration.
- [ ] Document expanded root `place_order` as the intentional compatibility
  boundary; document `PlaceOrderRequest` as the single batch/direct Exchange
  placement payload, `ModifyOrderRequest` as its base-derived modify payload,
  singular order option names, and `cloid` as the only client-order-ID field
  spelling.
- [ ] Document `dex`/`dexs` request naming and the close contract: full live
  size only, no public slippage, one position query per workflow, and one signed
  batch order for any number of positions.
- [ ] In the separately labeled Copycat impact section, record only the changes
  that its own repository must apply: `perp_dexs`/`perp_dexes` -> `dexs`, typed
  batch payloads, and removal of close size/slippage arguments. Make no Copycat
  source edit in this repository.
- [ ] Document Exchange live opt-in and the `IS_MAINNET=true` hard failure.
- [ ] Run the full deterministic suite, Info live suite, format/lint/type/package gates, and build/install smoke.
- [ ] Do not run Exchange integration; report it explicitly as intentionally pending, not passed.
- [ ] Perform the repository's routed review workflow with API-contract, data-integrity, concurrency, operational-risk, and rollback specialists selected.

Final validation commands:

```bash
uv run pytest -q tests/unit tests/contracts tests/public_api tests/package
RUN_LIVE_INFO_TESTS=true uv run pytest -q tests/integration/test_info.py
uv run ruff format --check
uv run ruff check src tests scripts
uv run ty check src/async_hyperliquid
uv run ty check tests
uv run ty check scripts
uv run pre-commit run --all-files
uv lock --check
uv build --no-sources
git diff --check
```

## Commit Boundaries

1. `test: restore testnet live integration fixtures`
2. `refactor!: unify typed order request contracts`
3. `refactor!: separate exchange actions from client workflows`
4. `feat: complete documented exchange actions`
5. `test: enforce endpoint integration coverage`
6. `docs: document credential roles and live test safety`

Each commit must pass its focused deterministic tests. Exchange integration remains unexecuted until a later explicit authorization.

## Rollback

- Revert commits in reverse order; no persistent local migration exists.
- The live-test safety commit must be reverted last so an intermediate rollback cannot accidentally re-enable mainnet Exchange tests.
- Consumers can remain pinned to `<1`; Copycat migration stays in its own repository.
