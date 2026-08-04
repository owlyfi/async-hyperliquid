# Async Hyperliquid v1 Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> `superpowers:subagent-driven-development` (recommended) or
> `superpowers:executing-plans` to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Release a typed, explicit and performance-preserving
`async-hyperliquid` 1.0 client with one network configuration, one HTTP
transport, no dynamic proxying and no compatibility wrappers on the v1 path.

**Architecture:** `AsyncHyperliquid` owns lifecycle and exposes concrete
`.info` and `.exchange` components. `Network` selects the signing domain and
official defaults; explicit `info_url` and `exchange_url` values may
independently route either service to protocol-compatible self-hosted or
third-party endpoints. One private `_HttpTransport` owns or borrows the
`aiohttp.ClientSession`; raw wire responses remain `TypedDict`, user-created
commands are frozen slotted dataclasses, and metadata is one atomically replaced
snapshot.

**Tech Stack:** Python 3.11+, with 3.12 pinned for development and CI coverage
through 3.13, plus `aiohttp`, `msgpack`, `eth-account`,
`eth-utils`, `uv`/`uv_build`, `pytest`, `ruff`, `ty`.

## Global Constraints

- Base revision: `b6b2844`; Target release: `1.0.0`.
- Preserve signing bytes and one-signature/one-POST batching behavior.
- Public signatures contain no `Any`, naked `dict` or naked `list`.
- No `__getattr__`, import-time monkeypatch or public-to-public forwarding.
- No automatic retries for signed actions.
- No runtime response-model framework or new mandatory dependency.
- No synchronous constructor may create an async resource.
- Python 3.11 syntax is the language floor.
- Copycat is read-only consumer evidence in this repository task. Its required
  compatibility work is recorded as a separate repository workstream below;
  no async-hyperliquid commit may modify Copycat files.

---

## P10 strategic decision

### Working Backwards

An async Hyperliquid user should be able to install 1.0, choose mainnet or
testnet once, optionally route Info and Exchange independently to
protocol-compatible self-hosted or third-party APIs, get exact IDE-visible
request/response types, submit one or many orders without hidden forwarding,
and know who owns the session and what a timeout means. No signed action may
derive its signing domain from a URL, mutate caller input, retry an ambiguous
trade, or silently return a different runtime type.

### Success standards

- The signing source and both official endpoint defaults derive from one
  `Network` value.
- `info_url` and `exchange_url` may independently override their exact endpoint.
  Neither can change the signing domain.
- Root public surface is exactly
  `AsyncHyperliquid`, `InfoClient`, `HyperliquidError`.
- Public signatures contain zero `Any` and zero naked containers.
- Warm signing/encoding p50 and p95 regress by at most 5%; batch N performs one
  signature and one POST.
- Lifecycle, cancellation, timeout and indeterminate-action semantics are
  deterministic and tested.
- Rollback is a package pin to `<1`; v1 carries no legacy execution path.

### P9 ownership

- P9-A owns public API, wire fixtures, type definitions, package exports and the
  migration guide. Runtime code may not change those contracts without P9-A
  review.
- P9-B owns transport, lifecycle, metadata concurrency, signing, order hot paths
  and benchmarks. Contract changes require P9-A approval.
- The interface between them is the frozen `types/` surface plus
  `_HttpTransport.post_json`. P10 resolves cross-boundary disagreement; neither
  team adds compatibility wrappers to avoid a decision.

## Verdict

Do not evolve the current facade into v1. It combines inheritance, composition,
dynamic proxying and import-time monkeypatching, then hides the resulting
contract holes behind `Any`. Keep the proven signing/batching algorithms, but
replace the object topology and public contract in vertical slices.

The target is deliberately small. Each object graph has exactly one transport
owner:

```text
standalone InfoClient
├── owns one _HttpTransport
├── binds one explicit Info URL
├── owns metadata and read-only derived queries
└── has no signer or Exchange capability

AsyncHyperliquid
├── owns one _HttpTransport
├── exposes one transport-bound InfoClient as .info
│   └── uses info_url or Network.info_url
└── exposes one transport-bound ExchangeClient as .exchange
    ├── uses exchange_url or Network.exchange_url
    ├── always signs with Network.signature_source
    └── reads one immutable metadata snapshot from InfoClient
```

There is no method forwarding on `AsyncHyperliquid`, no `__getattr__`, no
`__setattr__`, no compatibility monkeypatch and no inheritance between API
clients.

## Evidence from the current tree

### P0 correctness failures

1. `src/async_hyperliquid/exchange.py:17-30` derives the signing network from
   `base_url` before `AsyncAPI` resolves `None` to the mainnet URL. Direct
   `ExchangeAPI(...)` therefore posts to mainnet while signing as testnet.
   `tests/unit/test_http_and_nonce.py:114-147` currently freezes this bug as an
   expected value.
2. `src/async_hyperliquid/async_api.py:74-90` declares `Any` and returns either
   decoded JSON or raw text. Every endpoint annotation above this boundary is
   therefore aspirational rather than true.
3. `src/async_hyperliquid/utils/types.py` contains wrong wire contracts:
   `TwoHours = "4h"`, `FourHours = "1d"`, `"unknowOid"`, an incomplete rate-limit
   response, a wrong L2 book shape, and duplicate `Abstraction` aliases.
4. Cancelling one waiter for a shared metadata refresh cancels the refresh task
   observed by other waiters. The shared task in
   `src/async_hyperliquid/_async_hyperliquid/core.py:424-441` is not shielded.
5. The default `aiohttp.ClientTimeout` has `total=None`; connect and read phases
   are bounded, but the total operation is not.
6. The synchronous constructor creates `ClientSession`; construction outside a
   running event loop raises `RuntimeError`, and a later EVM initialization
   failure can leak the already-created session.
7. `AsyncAPI` caches `_request_url` in its constructor. Copycat 0.4.8 later
   assigns `hl.info.base_url = HL_INFO`, but that assignment does not update
   `_request_url`; the apparent local-node override still posts to the original
   official URL.

### Consumer evidence: Copycat local Info routing

Copycat establishes a required production use case, not a hypothetical custom
endpoint:

- `copycat/core/bots/base/hyperliquid.py` reads `HL_INFO`, creates a second
  Hyperliquid client, shares the primary session, and attempts to override only
  `raw_hl_local.info.base_url`.
- `copycat/core/bots/walle/preflight.py` describes `HL_INFO` as the trusted
  mainnet P2P read path and deliberately falls back to the official Info API.
- `copycat/portfolio/provider.py` accepts `HL_INFO` or `HL_LOCAL_NODE`,
  normalizes it to a full `/info` URL, and posts unsigned Info payloads there.
- `copycat/portfolio/executor.py` likewise attempts to redirect only
  `hl.info`; signed Exchange actions remain on the network-selected official
  endpoint.
- Every method admitted by Copycat's `_HL_LOCAL_CLIENT_METHOD_REQUEST_TYPES`
  resolves to an Info request or metadata lookup (`clearinghouseState`,
  `spotClearinghouseState`, `meta`, `perpDexs`, `spotMeta`, open orders). None
  requires signing or an Exchange endpoint.

Therefore v1 must preserve endpoint override capability, but it must not
preserve one generic URL knob whose effect on two services and signing is
ambiguous. Copycat remains unchanged; it is evidence used to define and test
the library contract.

### P1 design failures

1. `AsyncHyperliquid` inherits the action/order/info chain and `AsyncAPI`, while
   also owning `AsyncHyperliquidCore`. Dynamic method rebinding in
   `src/async_hyperliquid/async_hyperliquid.py:132-179` joins these incompatible
   models at runtime.
2. `_bind_compat_function` and the import-time patch loop at
   `src/async_hyperliquid/async_hyperliquid.py:88-92,184-223` add another wrapper
   layer solely to preserve monkeypatch paths.
3. The current order hot path is effectively:

   ```text
   place_order
     -> place_market_order/place_typed_order
     -> place_orders
     -> ExchangeAPI.post_action
     -> ExchangeAPI.post_action_with_sig
     -> AsyncAPI.post
   ```

4. `src/async_hyperliquid/utils/types.py` is an 880-line mixed bag of request
   commands, raw wire payloads, internal cache state and duplicated aliases.
5. The README imports a module that does not exist:
   `async_hyperliquid.async_hyper`.
6. Signing keeps unbounded global caches keyed by `id(payload_types)` while
   exposing shared mutable EIP-712 templates. Order/action code also mutates
   caller-owned mappings and stores `expires` as concurrent client-wide state.

### Baseline results

- `pytest -q tests/unit`: 70 passed, 3 warnings.
- `ruff check src tests scripts`: passed.
- `ty check` on source and tests: passed, but the result is not meaningful while
  public paths are erased by `Any`.
- Source scan: 167 public-ish functions, 59 without return annotations, 33
  occurrences of `Any`, 27 naked `dict` annotations and 26 `type: ignore`
  comments across the tree.
- `scripts/client_hotpath_benchmark.py`: fails immediately with
  `AttributeError: get_metas`; it no longer exercises the current topology.
- A warm limit-order profile observed 6 facade `__getattr__` lookups and 4
  compatibility-wrapper calls.
- Direct attribute access measured about 6 ns versus about 163 ns through the
  facade; the absolute cost is small next to signing/network I/O, but it buys no
  useful behavior and destroys static typing.
- Batch signing is the material performance win: a batch of 10 takes about
  0.20-0.24 ms to sign versus 2.28-2.64 ms for ten individual actions, with one
  HTTP request instead of ten.
- The current wheel builds successfully, but it contains no `py.typed` marker
  despite declaring `Typing :: Typed`.

## Target public API

Root exports stay intentionally small:

```python
# src/async_hyperliquid/__init__.py
from .client import AsyncHyperliquid
from .errors import HyperliquidError
from .info import InfoClient

__all__ = ["AsyncHyperliquid", "InfoClient", "HyperliquidError"]
```

Usage:

```python
from async_hyperliquid import AsyncHyperliquid, InfoClient
from async_hyperliquid.types import LimitOrder, Network, Side, TimeInForce

# Public/read-only use: no address and no signing key.
async with InfoClient(
    network=Network.MAINNET,
    info_url="https://provider.example/hyperliquid/info",
) as info:
    positions = await info.positions(account_address)

# Trading use: credentials are mandatory and both services remain explicit.
async with AsyncHyperliquid(
    account_address,
    signing_key,
    network=Network.MAINNET,
    info_url="https://provider.example/hyperliquid/info",
    exchange_url="https://provider.example/hyperliquid/exchange",
) as client:
    mids = await client.info.all_mids()
    result = await client.exchange.place_limit_order(
        LimitOrder(
            coin="ETH",
            side=Side.BUY,
            size=0.01,
            price=3_200,
            time_in_force=TimeInForce.GTC,
        )
    )
```

`AsyncHyperliquid` is only a resource owner. It does not forward `all_mids`,
`place_order` or any other endpoint.

Read-only consumers construct the root-exported `InfoClient`; it does not
require an address or signing key. `ExchangeClient` is not independently
constructible or root-exported; it exists only as `client.exchange`.

### Capability and constructor contract

```python
class InfoClient:
    def __init__(
        self,
        *,
        network: Network = Network.MAINNET,
        info_url: str | None = None,
        session: aiohttp.ClientSession | None = None,
        timeout: aiohttp.ClientTimeout | None = None,
    ) -> None: ...
```

`InfoClient` is a complete read capability, not a low-level wire stub. It owns
all raw Info endpoints plus read-only queries derived from Info responses and
the metadata snapshot:

- account state, portfolio, open orders, order status and positions;
- perp DEX discovery and metadata refresh;
- coin name/symbol, asset ID, token ID and size-decimal lookup;
- mark prices, mids and other read-only helpers.

Account-scoped methods take the account address explicitly. A standalone
`InfoClient` has no hidden default account, does not create an
`eth_account.Account`, never imports signing into the request path and exposes
no `.exchange`.

```python
class AsyncHyperliquid:
    def __init__(
        self,
        account_address: str,
        signing_key: str,
        *,
        network: Network = Network.MAINNET,
        info_url: str | None = None,
        exchange_url: str | None = None,
        session: aiohttp.ClientSession | None = None,
        timeout: aiohttp.ClientTimeout | None = None,
        perp_dexes: tuple[str, ...] = ("",),
    ) -> None: ...
```

`account_address` and `signing_key` are mandatory, non-optional constructor
arguments. `AsyncHyperliquid` always exposes both a fully initialized
`InfoClient` and `ExchangeClient`; it has no info-only or partially
authenticated state.

Rejected alternatives:

- Do not make `account_address` / `signing_key` optional. That forces
  `exchange: ExchangeClient | None` on every correctly authenticated caller or
  replaces static typing with a runtime "credentials required" exception.
- Do not generate dummy private/public keys for read-only access.
- Do not add `AsyncHyperliquid.info_only()` returning another runtime type;
  callers construct `InfoClient` directly.
- Do not duplicate read helpers on `AsyncHyperliquid`; `.info` is the one
  ownership boundary.

Rules:

- `network` is the only source for signing domain selection.
- `info_url` is an exact absolute POST endpoint, including `/info`. When it is
  omitted, `network.info_url` is used.
- `exchange_url` is an exact absolute POST endpoint, including `/exchange`.
  When it is omitted, `network.exchange_url` is used.
- Both overrides accept normal absolute HTTP(S) URLs, including provider query
  parameters. Do not add a provider adapter or endpoint-configuration class.
- A custom `info_url` affects every Info read, including metadata and price
  reads used to prepare an order. It never affects the Exchange URL or signing.
- A custom `exchange_url` receives signed Exchange action envelopes. Signing is
  still performed locally from `network`; the private key never leaves the
  process.
- The selected endpoint must implement each Info request the caller uses.
  Unsupported local-node methods fail normally; the library does not silently
  spend official API quota as a fallback.
- The public v1 client has no generic `base_url`; callers override the two
  services explicitly and may override either one without overriding the other.
- The caller must pair custom endpoints with the same logical `network`; the
  library does not guess a signing domain from hostnames or probe a provider on
  every request.
- The synchronous constructor creates no `ClientSession` or other async
  resource. `open()` / `async with` creates owned resources.
- An injected session is never closed by the library.
- A library-created session is closed by `close()` / the async context manager.
- The client is event-loop confined, matching `aiohttp.ClientSession`; it does
  not claim thread safety.
- No mutable defaults.
- URL routing is fixed at construction. `InfoClient.info_url` and
  `ExchangeClient.exchange_url` are read-only properties backed by private
  fields; mutating a legacy `base_url` after requests start is unsupported.
- A standalone `InfoClient` owns its transport. An `InfoClient` bound to
  `AsyncHyperliquid` borrows the root transport. There is exactly one closer in
  either object graph.
- Lifecycle is `NEW -> OPEN -> CLOSED`: `open()` and `close()` are idempotent,
  reopening a closed client is rejected, and endpoints never lazy-open.

## Target module layout

```text
src/async_hyperliquid/
├── __init__.py
├── client.py             # resource ownership only
├── info.py               # standalone/bound InfoClient and typed info endpoints
├── exchange.py           # ExchangeClient: orders and signed actions
├── errors.py             # four small, actionable exceptions
├── constants.py          # protocol constants only
├── types/
│   ├── __init__.py       # curated common types
│   ├── common.py         # JSON aliases, Network, Side, Cloid
│   ├── info.py           # raw response TypedDicts
│   └── exchange.py       # commands and exchange response TypedDicts
├── _http.py              # one concrete aiohttp transport
├── _metadata.py          # immutable snapshot/index
├── _signing.py           # pure encoding/signing functions
└── py.typed
```

Delete after migration:

```text
src/async_hyperliquid/async_api.py
src/async_hyperliquid/async_hyperliquid.py
src/async_hyperliquid/_async_hyperliquid/
src/async_hyperliquid/utils/decorators.py
src/async_hyperliquid/utils/miscs.py
src/async_hyperliquid/utils/signing.py
src/async_hyperliquid/utils/types.py
```

The last two move into focused modules before deletion; their proven pure
functions are not rewritten just to make the diff look new.

## Type policy

Use the type that matches ownership and runtime behavior:

| Data | Representation | Reason |
|---|---|---|
| Raw Hyperliquid JSON | `TypedDict` | Exact wire keys, zero conversion cost |
| Reusable order/cancel/modify command | frozen, slotted dataclass | Defaults, invariants, immutable batch input |
| Caller-supplied closed string choice | `StrEnum` | JSON-ready and type-safe |
| Raw response discriminator | `Literal` | The runtime value remains a JSON string |
| Fixed positional response | tuple | A list union cannot encode position |
| Internal metadata state | frozen, slotted dataclass | One atomic snapshot replacement |
| JSON transport boundary | recursive `JsonValue` alias | No naked `dict` / `Any` |
| Real injected interface | `Protocol` only after a second implementation exists | Avoid interface cosplay |

Core definitions:

```python
JsonScalar: TypeAlias = str | int | float | bool | None
JsonValue: TypeAlias = (
    JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]
)
JsonObject: TypeAlias = dict[str, JsonValue]


class Network(StrEnum):
    MAINNET = "mainnet"
    TESTNET = "testnet"

    @property
    def info_url(self) -> str:
        if self is Network.MAINNET:
            return "https://api.hyperliquid.xyz/info"
        return "https://api.hyperliquid-testnet.xyz/info"

    @property
    def exchange_url(self) -> str:
        if self is Network.MAINNET:
            return "https://api.hyperliquid.xyz/exchange"
        return "https://api.hyperliquid-testnet.xyz/exchange"

    @property
    def signature_source(self) -> Literal["a", "b"]:
        return "a" if self is Network.MAINNET else "b"


class Side(StrEnum):
    BUY = "B"
    SELL = "A"


class Cloid(str):
    """Validated 16-byte hex client order ID."""
```

`Cloid` remains a string at the JSON boundary; it must not require a `.to_raw()`
wrapper.

Example command:

```python
@dataclass(frozen=True, slots=True)
class LimitOrder:
    coin: str
    side: Side
    size: float
    price: float
    time_in_force: TimeInForce = TimeInForce.GTC
    reduce_only: bool = False
    client_order_id: Cloid | None = None
```

`BuilderFee`, `OrderGrouping` and `expires_after` belong to the whole wire
action, not to each order. One-off actions such as withdraw, transfer, leverage
update and stake keep explicit method parameters; creating a dataclass for each
would be interface cosplay.

Public limit, market and batch methods call shared private pure helpers; they
never call one another. Market order remains explicit because it performs a
quote request before submission:

```python
async def place_limit_order(
    self,
    order: LimitOrder,
    *,
    builder_fee: BuilderFee | None = None,
    expires_after: int | None = None,
) -> PlaceOrderResponse:
    action = self._encode_orders((order,), builder_fee=builder_fee)
    return await self._submit_action(action, expires_after=expires_after)


async def place_orders(
    self,
    orders: Sequence[LimitOrder | TriggerOrder],
    *,
    grouping: OrderGrouping = OrderGrouping.NA,
    builder_fee: BuilderFee | None = None,
    expires_after: int | None = None,
) -> PlaceOrderResponse:
    action = self._encode_orders(
        orders, grouping=grouping, builder_fee=builder_fee
    )
    return await self._submit_action(action, expires_after=expires_after)


async def place_market_order(
    self,
    order: MarketOrder,
    *,
    builder_fee: BuilderFee | None = None,
    expires_after: int | None = None,
) -> PlaceOrderResponse:
    action = await self._encode_market_order(
        order, builder_fee=builder_fee
    )
    return await self._submit_action(action, expires_after=expires_after)
```

This is one endpoint boundary and one network call, not public-wrapper chaining.
The encoder must not mutate a command or caller-owned mapping.

Wire `status`, `role`, `side` and abstraction-state fields use `Literal`, not
`StrEnum`, because response JSON is not converted into runtime enum instances.
Fixed meta/context pairs are
`tuple[PerpMeta, list[PerpAssetContext]]` and
`tuple[SpotMeta, list[SpotAssetContext]]`, validated for length two at the
endpoint boundary.

Validation stays narrow:

- order size and limit/trigger price must be finite and greater than zero;
- slippage must be finite and between zero and one;
- `Cloid` must be `0x` plus exactly 32 hexadecimal characters;
- account/vault addresses are normalized once before any session is opened;
- remote responses receive top-level container/discriminator checks only, while
  fields consumed by metadata/signing fail as `ProtocolError`.

Do not introduce recursive runtime validation for fields the library merely
returns to the caller.

## Transport and error contract

`_HttpTransport` is a concrete implementation, not a framework:

```python
async def post_json(
    self,
    url: str,
    payload: JsonObject,
) -> JsonValue:
    ...
```

Behavior:

- Decode JSON exactly once.
- The transport owns HTTP mechanics and session lifecycle, not a base URL.
  `InfoClient` supplies its resolved Info URL and `ExchangeClient` supplies the
  network-selected Exchange URL.
- A non-2xx status raises `HttpError`.
- A non-JSON success response raises `ProtocolError`; never return `str` from a
  JSON endpoint.
- Transport never knows about signing, nonces or action kinds.
- `info_url` receives only unsigned Info payloads.
- `exchange_url` receives signed action envelopes but never the signing key.
  Selecting a third-party Exchange endpoint is an explicit trust decision.
- Do not automatically retry signed exchange actions.
- Default timeout has a finite total, connect and socket-read budget. Initial
  proposal: total 15 s, connect 3 s, socket read 10 s; keep it constructor
  configurable and validate with integration latency.
- Log action kind, nonce, elapsed time and status at debug level. Never log
  private keys, signatures, complete payloads or an exact custom URL. URL
  userinfo, path and query values may contain provider credentials; diagnostics
  use only the endpoint role (`info` / `exchange`) and a redacted host.

Exception surface:

```python
class HyperliquidError(Exception): ...
class HttpError(HyperliquidError): ...
class ProtocolError(HyperliquidError): ...
class IndeterminateActionError(HyperliquidError): ...
```

`ExchangeClient._submit_action()` owns the nonce and action kind. It wraps a
timeout, connection failure or untrusted acknowledgement as
`IndeterminateActionError(action_type, nonce)` without including payload or
signature. It never catches, wraps or shields `asyncio.CancelledError`; local
cancellation does not prove that the remote action was not applied, so callers
reconcile with nonce/client order ID. No exception taxonomy exists beyond these
failure modes on which a caller can act.

## Metadata and concurrency contract

Replace five parallel mutable maps and empty sentinels with one snapshot:

```python
@dataclass(frozen=True, slots=True)
class _MetadataSnapshot:
    asset_by_coin: Mapping[str, int]
    size_decimals_by_coin: Mapping[str, int]
    token_by_coin: Mapping[str, SpotToken]
    perp_dex_names: tuple[str, ...]
```

Refresh:

1. Fetch required meta responses in a Python 3.11 `TaskGroup`, so failure or
   cancellation cancels and awaits siblings.
2. Build every map in local variables.
3. Construct one `_MetadataSnapshot`.
4. Replace one reference.

Use one `asyncio.Lock` with a double-check. Do not own a background refresh task:

```python
if self._snapshot is not None:
    return self._snapshot
async with self._refresh_lock:
    if self._snapshot is None:
        self._snapshot = await self._load_snapshot()
return self._snapshot
```

If the active loader is cancelled, the lock is released and the next waiter
performs the refresh. This is simpler than keeping an orphan task alive. Tests
must cover:

- 20 concurrent cold readers trigger exactly one refresh.
- Cancelling the active loader releases the lock; the next reader completes a
  new refresh and is not cancelled.
- A failed refresh is cleared and the next call can retry.
- Readers see either the old or the new snapshot, never a mixed state.

The snapshot's dictionaries are private, newly built and never leaked or
mutated after publication. `frozen=True` does not make nested dictionaries
deeply immutable; do not add `MappingProxyType` for a property the code does not
need.

Nonce generation stays a tiny event-loop-confined synchronous counter:

```python
self._last_nonce = max(time.time_ns() // 1_000_000, self._last_nonce + 1)
```

Do not add a cross-process nonce service. Document that one API wallet should
have one live client owner; multi-process coordination is the application’s
responsibility.

## Naming policy

Public names describe the domain, not wire abbreviations:

| Current | v1 |
|---|---|
| `sz`, `px`, `ro` | `size`, `price`, `reduce_only` |
| boolean `is_buy` | `side: Side` |
| `api_key` | `signing_key` |
| `address` | `account_address` |
| `is_mainnet` | `network` |
| generic/mutable `base_url` | constructor-only `info_url` / `exchange_url` |
| `place_order(..., is_market=...)` | `place_limit_order` / `place_market_order` |
| `place_typed_order` | delete; use a concrete command |
| `get_all_dex_name` | `perp_dex_names` |
| `get_coin_asset` | `asset_id` |
| `get_coin_sz_decimals` | `size_decimals` |
| `perp_dexs` | `perp_dexes` |
| raw `get_token_info(token_id)` | `token_details` |
| cached `get_token_info(coin)` | `spot_token_metadata` |

All read-only replacements above live on `InfoClient`, including the
transport-bound `client.info` instance. Account-scoped replacements require an
explicit address:

| Current root helper | v1 InfoClient |
|---|---|
| `get_perp_account_state(address, dex)` | `info.perp_account_state(address, dex)` |
| `get_spot_account_state(address)` | `info.spot_account_state(address)` |
| `get_account_state(address)` | `info.account_state(address)` |
| `get_user_open_orders(address, ...)` | `info.open_orders(address, ...)` |
| `get_order_status(order_id, address, dex)` | `info.order_status(address, order_id, dex)` |
| `get_dex_positions(address, dex)` | `info.positions(address, (dex,))` |
| `get_all_positions(address, dexs)` | `info.positions(address, dexs)` |
| `init_metas()` | `info.refresh_metadata()` |

Drop meaningless `get_` prefixes where the method is plainly an asynchronous
query in a namespaced client: `client.info.all_mids()`, `open_orders()`,
`order_status()`. Keep verbs when they distinguish actions: `place_order`,
`cancel_orders`, `modify_order`, `withdraw`.

One canonical method per behavior. Delete aliases such as:

- `get_user_token_balances -> get_spot_clearinghouse_state`
- duplicate staking/delegation calls
- `get_market_price -> get_mark_price`
- `batch_cancel_orders -> cancel_orders`
- `close_position -> close_positions -> close_all_positions`
- `get_latest_*` wrappers that only exist to narrow an `Any`

The migration guide records replacements; v1 does not carry forwarding methods.

## Dependency and runtime upgrade

Change the Python/package boundary early, but upgrade runtime dependencies only
after the new topology is green. Mixing both makes failures impossible to
attribute.

- Set package version to `1.0.0rc1` during migration, then `1.0.0` at release.
- Raise Python floor from 3.10 to 3.11, pin development to 3.12, and test
  3.11, 3.12 and 3.13.
- Remove the `<4` Python cap; unsupported future Python versions should fail
  based on evidence, not prophecy.
- Upgrade `uv_build` from `>=0.7.11,<0.8` to the current tested `0.11` range.
- Remove the stale Poetry package block.
- Add and verify `src/async_hyperliquid/py.typed` in the built wheel.
- After the root cutover, upgrade `aiohttp`, `msgpack`, `eth-account` and
  `eth-utils` one at a time. Each upgrade gets its own lockfile diff, signing
  parity run and AB/BA benchmark.
- Test `eth-utils` 6 in the signer matrix; accept it only when `eth-account` and
  parity tests pass. Do not upgrade a signing dependency merely to maximize
  version numbers.
- Update the development parity oracle to
  `hyperliquid-python-sdk` 0.24.x.
- Remove embedded EVM support and the mandatory `hl-web3` dependency. v1's
  migration guide directs EVM users to `hl-web3` directly; designing an adapter
  is a separate project.
- Remove the direct `coincurve` dependency unless a controlled benchmark shows
  an end-to-end signing win; current results are noise around zero and the
  package code does not import it.

Python 3.10 reaches security end-of-life in October 2026, so carrying it through
a new major version would spend migration budget on an almost-retired runtime.

## Performance policy and gates

Performance work must preserve the wins that matter:

1. one `ClientSession` per client;
2. one signature and one HTTP request per batch;
3. one metadata refresh for concurrent cold readers;
4. no full response-model conversion;
5. no mutation/copy of caller commands beyond building the wire action;
6. no dynamic proxy or compatibility wrapper on the hot path.

Before changing hot code, repair `scripts/client_hotpath_benchmark.py` so it
constructs the real public client. On a fixed runner, install the baseline and
candidate wheels and run alternating AB/BA rounds with warmup; record median,
MAD and p95. Stored JSON is evidence, not a portable pass/fail oracle.

Release gates:

- Framework-only order preparation should improve, but the release blocker is
  that preparation, full warm order and `sign_action` p50/p95 do not regress by
  more than 5%. The current signer dominates allocation, so a hard 10%
  preparation improvement would reward benchmark gaming.
- A batch of N orders performs exactly one signing operation and one POST.
- Batch x10 per-order signing must be at least 8x faster than ten independent
  signatures.
- A warm order path performs zero `__getattr__` dispatches and zero compatibility
  wrapper calls.
- Concurrent metadata initialization performs one set of upstream requests.
- No `ClientSession` is created per endpoint call.
- A local `aiohttp` server verifies concurrency 1/10/100, connection reuse,
  finite total timeout and cancellation. Expected `TimeoutError` and
  `CancelledError` are asserted outcomes; unexpected exceptions fail.
- Any proposed micro-optimization must beat the current implementation over at
  least seven alternating repeats. The measured `bytearray` rewrite of
  `hash_action` was slower and must not be adopted.

Do not gate CI on live-network wall time. Use operation counts in CI and run
microbench thresholds on a stable release runner. `tracemalloc` results are
reported but not hard-gated. Even with a borrowed session, each request receives
the client's finite timeout so a session default cannot reintroduce an
unbounded total.

## Rollout and rollback

- Publish a narrow `0.5.1` correctness hotfix, then work on a v1 branch with
  vertical, reviewable commits.
- Publish `1.0.0rc1`; run real consumer migrations and testnet soak before
  `1.0.0`.
- Do not publish a `0.6.x` deprecation layer and do not copy compatibility
  machinery into v1.
- Rollback is package pinning to `async-hyperliquid<1`; there is no persistent
  data migration.
- Keep the `0.5.x` tag and documentation immutable.
- A v1 release is blocked on the corrected network-signing test, cancellation
  test, package typing test, public API snapshot, testnet integration tests and
  fixed-runner performance report.

## Execution plan

### Task 0: Ship the 0.5.1 correctness hotfix

**Files**

- Modify: `src/async_hyperliquid/async_api.py:40-84`
- Modify: `src/async_hyperliquid/exchange.py:17-30`
- Modify: `src/async_hyperliquid/_async_hyperliquid/core.py:48-86,424-441`
- Modify: `tests/unit/test_http_and_nonce.py:109-153`
- Add: `tests/unit/test_metadata_cancellation.py`

**Interfaces**

- Produces: `ExchangeAPI(..., *, is_mainnet: bool | None = None)` for the
  maintenance release only.
- Preserves: every existing 0.5 public method, response and mutable
  `InfoAPI.base_url` compatibility behavior.

- [x] **Step 1:** Write a test proving default `base_url=None` resolves both
  request URL and signing flag to mainnet; run it and confirm failure on
  `b6b2844`.
- [x] **Step 2:** Resolve the URL before the signing flag and let the top-level
  core pass `is_mainnet` explicitly, so a custom 0.5 proxy URL cannot silently
  change the signing domain.
- [x] **Step 3:** Write a regression test for the existing consumer pattern
  `info.base_url = local_origin` and make the request URL derive from the
  current base URL at call time; do not add another transport wrapper or modify
  a consumer repository.
- [x] **Step 4:** Write a two-waiter cancellation test that cancels the active
  metadata loader and asserts the second waiter retries successfully.
- [x] **Step 5:** Replace `_meta_init_task` with the existing lock plus a
  double-check; keep snapshot construction local.
- [x] **Step 6:** Run:
  `/Users/yuki/.local/bin/uv run pytest -q tests/unit/test_http_and_nonce.py tests/unit/test_metadata_cancellation.py`.
- [x] **Step 7:** Commit:
  `fix: align signing network and metadata cancellation`.

### Task 1: Freeze contracts and repair performance evidence

**Files**

- Add: `tests/public_api/test_imports.py`
- Add: `tests/typing/test_public_api.py`
- Add: `tests/contracts/fixtures/`
- Modify: test factories currently annotated as `Any`
- Rewrite: `scripts/client_hotpath_benchmark.py`
- Add: `scripts/benchmarks/baseline-0.5.1.json`

**Interfaces**

- Produces: response fixtures and benchmark operations used by every later
  task.
- Consumes: tagged `0.5.1` wheel as the baseline candidate.

- [x] **Step 1:** Add import snapshots for the existing documented public
  surface and execute them against an installed 0.5.1 wheel.
- [x] **Step 2:** Replace `build_stub_hl() -> Any`-style factories with typed
  test doubles exposing only the methods each test uses.
- [x] **Step 3:** Record official JSON fixtures for every implemented info
  endpoint and order/cancel success/error shape.
- [x] **Step 4:** Rewrite the hot-path benchmark to install baseline and
  candidate wheels, alternate AB/BA rounds, warm up, and report median/MAD/p95.
- [x] **Step 5:** Make any unexpected benchmark exception fail immediately;
  do not count `gather(return_exceptions=True)` values as success.
- [x] **Step 6:** Run unit tests, Ruff, Ty and the repaired local benchmark.
- [x] **Step 7:** Commit:
  `test: freeze v1 contracts and performance baseline`.

### Task 2: Establish the Python 3.11 typed package boundary

**Files**

- Modify: `pyproject.toml`
- Add: `src/async_hyperliquid/py.typed`
- Add: `tests/package/test_wheel.py`
- Modify: CI workflow files

**Interfaces**

- Produces: Python 3.11-3.13 package/test matrix and an inline-typed wheel.
- Does not change: runtime dependency versions or endpoint behavior.

- [x] **Step 1:** Set `requires-python = ">=3.11"`, update classifiers, remove
  the stale Poetry block and move `uv_build` to the tested 0.11 range.
- [x] **Step 2:** Add `py.typed` and a wheel-content assertion.
- [x] **Step 3:** Add Python 3.11, 3.12 and 3.13 CI jobs.
- [x] **Step 4:** Run `uv build --no-sources`, install the wheel in a clean
  environment and execute import/type smoke tests.
- [x] **Step 5:** Commit:
  `build: establish the typed Python 3.11 package boundary`.

### Task 3: Define exact wire and command types

**Files**

- Add: `src/async_hyperliquid/types/common.py`
- Add: `src/async_hyperliquid/types/info.py`
- Add: `src/async_hyperliquid/types/exchange.py`
- Add: `src/async_hyperliquid/types/__init__.py`
- Add: `tests/unit/types/`
- Modify: `tests/typing/test_public_api.py`

**Interfaces**

- Produces: `Network`, `Side`, `TimeInForce`, `TriggerKind`,
  `OrderGrouping`, `Cloid`, response `TypedDict`s and reusable command
  dataclasses.
- Consumes: Task 1 wire fixtures.

- [x] **Step 1:** Define Python 3.11-compatible recursive `TypeAlias` values and
  a `Network` enum that owns both exact official endpoint URLs and the signing
  source.
- [x] **Step 2:** Define response `TypedDict`s with `Literal` discriminators;
  correct candle intervals, all-mids strings, L2 book, rate-limit and order
  status contracts.
- [x] **Step 3:** Define frozen slotted `LimitOrder`, `TriggerOrder`,
  `MarketOrder`, `CancelOrder`, `CancelByCloid`, `ModifyOrder` and
  `BuilderFee` without inheritance.
- [x] **Step 4:** Represent meta/context pairs as exact two-tuples and validate
  only their top-level length/shape at the endpoint boundary.
- [x] **Step 5:** Add an AST test rejecting `Any` and naked containers only in
  public signatures; allow exact forms such as `list[Order]`.
- [x] **Step 6:** Run unit and typing tests on Python 3.11.
- [x] **Step 7:** Commit:
  `feat(types): add exact v1 wire and command contracts`.

### Task 4: Add one strict HTTP transport and lifecycle state machine

**Files**

- Add: `src/async_hyperliquid/_http.py`
- Add: `src/async_hyperliquid/errors.py`
- Add: `tests/unit/test_transport.py`
- Add: `tests/unit/test_lifecycle.py`

**Interfaces**

- Produces:
  `_HttpTransport(session=None, timeout=None)`,
  `post_json(url, payload) -> JsonValue`,
  `HttpError`, and `ProtocolError`.
- Does not produce: retry policy, signing errors or background tasks.

- [x] **Step 1:** Write lifecycle tests for `NEW -> OPEN -> CLOSED`, idempotent
  `open/close`, forbidden reopen, and endpoint rejection before `open()`.
- [x] **Step 2:** Implement synchronous transport configuration only; allocate
  no async resource in the constructor.
- [x] **Step 3:** Create an owned session only in `open()`; validate but never
  close a borrowed session. Remove connector injection.
- [x] **Step 4:** Accept an exact URL per request, set finite total/connect/read
  request timeouts, and apply them even with a borrowed session. Transport must
  neither store a generic base URL nor infer a signing network from a URL.
- [x] **Step 5:** Decode JSON once; raise `HttpError` for status failure and
  `ProtocolError` for an invalid JSON contract. Never return raw text.
- [x] **Step 6:** Add redaction tests proving logs/exceptions exclude signing
  keys, signatures, full payloads and exact third-party URLs containing
  credentials in userinfo, path or query values.
- [x] **Step 7:** Run transport/lifecycle tests against a local aiohttp server.
- [x] **Step 8:** Commit:
  `refactor: add strict transport and explicit lifecycle`.

### Task 5: Build standalone and bound InfoClient modes

**Files**

- Rewrite: `src/async_hyperliquid/info.py`
- Add: `src/async_hyperliquid/_metadata.py`
- Add: `tests/unit/test_info_client.py`
- Add: `tests/unit/test_metadata.py`
- Modify: `tests/contracts/`

**Interfaces**

- Produces:
  `InfoClient(network=..., info_url=None, session=None, timeout=None)` for
  standalone use and private
  `InfoClient._from_transport(transport, info_url=...)` for root composition.
- Produces: one private `_MetadataSnapshot` published by reference replacement.
- Produces all read-only derived helpers currently stranded on the root facade;
  neither mode requires or fabricates an address/signing key.

- [x] **Step 1:** Write tests for standalone ownership and bound transport
  borrowing; assert exactly one closer per object graph. Assert construction
  and every public read path work without importing or creating a signer.
- [x] **Step 2:** Test official mainnet/testnet defaults plus an HTTP
  self-hosted `/info` endpoint. Assert the self-host receives Info payloads and
  never receives a signed action or signature; assert `info_url` is readable
  but cannot be reassigned.
- [x] **Step 3:** Implement info endpoints directly on `InfoClient`, with one
  transport call and endpoint-boundary top-level shape checks.
- [x] **Step 4:** Move account state, positions, open-order/status and metadata
  lookup helpers to `InfoClient`. Require explicit account addresses and add no
  root forwarding aliases.
- [x] **Step 5:** Fetch metadata branches with `TaskGroup`, build private
  dictionaries locally, then replace one snapshot reference.
- [x] **Step 6:** Use one lock with double-check. Test normal 20-reader cold
  start as one fetch set, waiting-reader cancellation, active-loader
  cancellation/retry and failed-refresh recovery.
- [x] **Step 7:** Add API/type tests proving `InfoClient` has no signing
  parameters or `.exchange`, while `AsyncHyperliquid` rejects missing or empty
  credentials before opening a session.
- [x] **Step 8:** Run info, contract, concurrency and type tests.
- [x] **Step 9:** Commit:
  `refactor(info): add typed info client and atomic metadata`.

### Task 6: Flatten signing and ExchangeClient

**Files**

- Add: `src/async_hyperliquid/_signing.py`
- Rewrite: `src/async_hyperliquid/exchange.py`
- Add: `tests/unit/test_exchange_client.py`
- Add: `tests/unit/test_order_encoding.py`
- Add: `tests/unit/test_action_failures.py`
- Modify: `scripts/client_hotpath_benchmark.py`

**Interfaces**

- Produces: transport-bound `ExchangeClient`; explicit limit, market and batch
  order methods; `IndeterminateActionError(action_type, nonce)`.
- Consumes: Task 3 command/wire types, Task 4 transport and Task 5 metadata.

- [x] **Step 1:** Freeze golden signing vectors and bit-for-bit parity with the
  0.5.1 wheel before moving functions.
- [x] **Step 2:** Move pure signing functions, replace `id(payload_types)`
  caches with fixed module constants, and never mutate caller mappings.
- [x] **Step 3:** Implement explicit order methods; each calls private encoding
  plus `_submit_action` directly, and batch performs one hash/sign/POST.
- [x] **Step 4:** Bind `_submit_action` to the resolved `exchange_url`; prove
  with a split-endpoint test that `info_url` never receives signed payloads and
  that a custom `exchange_url` cannot change `signature_source`.
- [x] **Step 5:** Put `builder_fee`, `grouping` and `expires_after` at action
  level; remove mutable client expiry and `SignType`.
- [x] **Step 6:** Keep one-off admin actions as typed method parameters; do not
  create command classes without reuse or invariants.
- [x] **Step 7:** Wrap timeout/connection/untrusted acknowledgement in
  `IndeterminateActionError` inside `_submit_action`; preserve
  `CancelledError` and never retry or shield.
- [x] **Step 8:** Verify no caller input mutation, nonce uniqueness, one
  sign/POST per batch and exact exchange response types. Cover official
  defaults, custom Info only, custom Exchange only and both custom endpoints on
  both `Network` values.
- [x] **Step 9:** Run signing parity and AB/BA hot-path benchmarks.
- [x] **Step 10:** Commit:
  `refactor(exchange): flatten signed action hot paths`.

### Task 7: Atomically cut over the root API and delete legacy topology

**Files**

- Add: `src/async_hyperliquid/client.py`
- Rewrite: `src/async_hyperliquid/__init__.py`
- Delete: legacy files listed in the target layout section
- Rewrite: unit/integration imports
- Add: `tests/public_api/test_surface.py`

**Interfaces**

- Produces root exports:
  `AsyncHyperliquid`, `InfoClient`, `HyperliquidError`.
- Produces concrete `client.info: InfoClient` and
  `client.exchange: ExchangeClient`.

- [x] **Step 1:** Implement `AsyncHyperliquid` as lifecycle/resource owner with
  explicit `account_address`, `signing_key`, `network` and optional
  constructor-only `info_url` / `exchange_url`; validate/parse signer inputs
  before `open()` can allocate a session.
- [x] **Step 2:** Bind info/exchange components to the same transport but
  independently resolved exact URLs; expose no flat endpoint forwarding.
- [x] **Step 3:** Delete `AsyncAPI`, dynamic proxying, capability mixins,
  monkeypatch propagation, `AsyncHyper`, aliases, decorators and deep shims.
- [x] **Step 4:** Remove embedded EVM support and `hl-web3` from the core
  dependency set.
- [x] **Step 5:** Assert exact root exports, no `__getattr__`, no public
  `ExchangeClient` constructor, exact `info_url` / `exchange_url` constructor
  parameters and no legacy import success.
- [x] **Step 6:** Run unit, integration, public API, typing and benchmark gates.
- [x] **Step 7:** Commit:
  `refactor!: replace facade with explicit v1 clients`.

### Task 8: Upgrade dependencies one at a time

**Files**

- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Add: dependency parity/benchmark artifacts

**Interfaces**

- Preserves: Task 7 public API, signing bytes and performance gates.

- [x] **Step 1:** Upgrade `aiohttp`; run transport, lifecycle and full unit
  suites before committing its lockfile diff.
- [x] **Step 2:** Upgrade `msgpack`; run golden hash/signing vectors and AB/BA
  benchmark before committing.
- [x] **Step 3:** Upgrade `eth-account` and test `eth-utils` 6 compatibility;
  accept only a resolver-clean set with signing parity.
- [x] **Step 4:** Update the dev parity oracle to official SDK 0.24.x.
- [x] **Step 5:** Remove direct `coincurve` unless the controlled benchmark
  proves an end-to-end win.
- [x] **Step 6:** Commit each accepted dependency independently; never combine
  all lockfile changes into one opaque commit.

### Task 9: Document, soak and release

**Files**

- Rewrite: `README.md`
- Rewrite: `CHANGELOG.md`
- Add: `docs/migration-0.5-to-1.0.md`
- Modify: `pyproject.toml`
- Add: release benchmark artifact

**Interfaces**

- Produces: `1.0.0rc1`, then `1.0.0`.

- [x] **Step 1:** Document the two entry points, lifecycle, typed commands,
  batching, self-hosted/third-party endpoint routing, cancellation and
  indeterminate-action reconciliation.
- [x] **Step 2:** Provide a mechanical old-to-new import/method mapping without
  a runtime compatibility wrapper; document constructor-time endpoint
  injection and direct EVM users to `hl-web3`. Do not edit consumer
  repositories.
- [ ] **Step 3:** Run testnet place/cancel/modify/close and metadata soak tests,
  plus read/write staging soaks through independently configured
  protocol-compatible endpoint URLs.
- [x] **Step 4:** Build wheel/sdist with `--no-sources`, inspect contents,
  install both into clean environments and run README snippets.
- [ ] **Step 5:** Publish `1.0.0rc1`, let consumer owners validate their
  migrations against the separate Copycat workstream below, then publish
  `1.0.0` only after all release gates remain green.
- [x] **Step 6:** Commit the locally verified RC preparation:
  `release: prepare async-hyperliquid 1.0.0rc1`.

## Separate consumer workstream: Copycat

This section is a cross-repository handoff, not part of the
`async-hyperliquid` implementation diff. Execute it in a separate Copycat
branch, commit and review after `1.0.0rc1` is available.

### Compatibility guard before the v1 release

Copycat currently declares `async-hyperliquid>=0.4.8`, which permits an
unreviewed major-version upgrade on a fresh dependency resolution. Before
publishing stable v1, the Copycat owner should independently:

- update `pyproject.toml` to constrain the existing integration to
  `async-hyperliquid>=0.4.8,<1`;
- update `uv.lock`;
- run Copycat's Hyperliquid contract and bot test suites;
- merge this guard independently from both the SDK release and the later v1
  migration.

### Copycat v1 migration after `1.0.0rc1`

Expected Copycat paths and responsibilities:

| Copycat path | Separate-repository adjustment |
|---|---|
| `pyproject.toml`, `uv.lock` | Move the guarded dependency to the reviewed v1 RC/stable range only after compatibility tests pass. |
| `copycat/core/bots/base/hyperliquid.py` | Construct with `network=Network.*`; pass endpoint URLs at construction; remove post-construction `info.base_url` and session reassignment; update the runtime contract check to concrete v1 components. |
| `copycat/core/bots/base/hyperliquid.py` local-read path | Use standalone `InfoClient(info_url=...)` for `HL_INFO`; do not create ephemeral/dummy keys or a signing-capable client solely for reads. Keep the supported-request whitelist and fallback policy application-owned. |
| `copycat/portfolio/executor.py` | Pass the normalized Info endpoint during construction; remove `hl.info.base_url = ...`. Add an Exchange override only if Copycat has an explicit provider configuration for it. |
| `copycat/core/bots/walle/preflight.py` and bot query modules | Retain local-first/public-fallback behavior; call the standalone local `InfoClient` directly and pass account addresses explicitly. Use `.info` / `.exchange` only on the authenticated trading client. |
| `tests/unit/test_async_hyperliquid_contract.py` | Replace the legacy flat-method/base-url contract with the exact v1 constructor, component and read-only endpoint contract. |
| `tests/unit/test_bot_hl_local_proxy.py`, mocks and affected bot tests | Update local Info construction, lifecycle ownership, whitelisting and fallback assertions without weakening the supported-request boundary. |

Copycat migration constraints:

- It is a separate PR with its own base revision, review ledger and rollback.
- Do not combine the Copycat dependency pin, v1 API migration and unrelated bot
  refactors in one commit.
- Preserve current `HL_INFO` / `HL_LOCAL_NODE` normalization to an exact
  `/info` URL.
- Remove the read-only path's dependency on
  `COPYCAT_HL_SOURCE_ONLY_API_KEY`/ephemeral key generation only after proving
  no remaining local-read call requires Exchange capability.
- Do not silently route signed Exchange actions through the local Info node.
- Do not add `HL_EXCHANGE` or another Copycat configuration field unless
  Copycat explicitly chooses to consume a third-party Exchange endpoint.
- Validate at minimum: local Info success, official Info fallback, unsupported
  local request rejection, mainnet/testnet signing parity, order/cancel smoke,
  client reinitialization and deterministic session closure.

## Mandatory review gates per task

For each non-trivial task:

1. semantic diff analysis;
2. risk routing;
3. Linus correctness/simplicity review;
4. adversarial trust-boundary review;
5. rollback review;
6. only the additional specialist checks selected by the risk router; the full
   v1 cutover selects architecture, blast radius, observability, performance,
   concurrency, input validation, API contract, data integrity and operations,
   but a focused task does not run irrelevant reviewers;
7. merged, deduplicated finding list;
8. consensus pass only when reviewers disagree.

No task merges with an open P0/P1 finding.

## Explicit non-goals

- No Pydantic, attrs or response-model framework.
- No repository/service/controller layers.
- No command bus or generic request registry.
- No runtime conversion of every response.
- No automatic retry of signed actions.
- No optional-credential or partially authenticated `AsyncHyperliquid` state;
  read-only callers use `InfoClient`.
- No built-in endpoint fallback, health checker, provider authentication
  framework or load balancer; applications own routing policy.
- No WebSocket rewrite in the v1 REST topology project.
- No EVM adapter; embedded EVM support is removed and `hl-web3` remains a
  separate client.
- No compatibility wrappers in the v1 core.
- No Rust/C extension before profiling proves Python signing/encoding is the
  release bottleneck.
- No broad input-schema engine; validate finite/positive values and protocol
  discriminants only where the library depends on them.

## Final acceptance checklist

- [x] Default network and signing domain cannot disagree.
- [x] `InfoClient` requires no address/key, exposes every supported read-only
  query needed by metadata consumers and has no Exchange capability.
- [x] `AsyncHyperliquid` requires valid account/signing credentials and always
  exposes a concrete `ExchangeClient`, never `None`.
- [x] `info_url` and `exchange_url` independently route their own service
  without changing the signing source.
- [x] Custom Exchange requests are signed for `network`, never inferred from
  the provider URL, and the private key never leaves the client.
- [x] Endpoint URLs are fixed at construction; no stale cached URL remains
  after a supported configuration change because there is no supported
  mutation path.
- [x] Public return types match recorded wire fixtures.
- [x] Public signatures contain no `Any`, naked `dict` or naked `list`.
- [x] Built wheel contains `py.typed`.
- [x] No dynamic proxy, monkeypatch propagation or public forwarding chain.
- [x] One owned session, finite total timeout, explicit session ownership.
- [x] Metadata cancellation cannot poison the cache or cancel unrelated
  waiters; active-loader cancellation may cause one controlled retry.
- [x] Batch N means one signature and one POST.
- [ ] Signing/encoding p50 and p95 regression is at most 5% on the fixed runner.
- [x] README imports execute from the installed wheel.
- [ ] Python 3.11-3.13 unit, type and package tests pass.
- [ ] Testnet integration suite passes.
- [x] Migration and rollback documentation is complete.

RC-local evidence does not close the three remaining release gates:

- The median AB/BA deltas are within 1.55%, but this runner's identical-wheel
  control itself produced signing p95 deltas above 5%; rerun the p95 gate on a
  controlled runner before stable release.
- Python 3.11 clean wheel/sdist installs pass and local tests pass on 3.12; the
  configured 3.11-3.13 CI matrix still needs to run on the committed branch.
- Signed testnet and independent-provider staging soaks require operator
  credentials/providers and remain intentionally unexecuted.
