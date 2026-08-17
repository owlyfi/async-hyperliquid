# Migrating async-hyperliquid 0.5 to 1.0

Version 1 is a deliberate API break. It removes the dynamic facade and replaces
implicit state with two explicit clients:

- use `InfoClient` for every credential-free read;
- use `AsyncHyperliquid` when signed Exchange actions are required; call root
  trading workflows when Info resolution is needed and `.exchange` only for
  Info-independent actions.

There is no runtime compatibility wrapper. Migrate call sites mechanically and
pin existing consumers to `<1` until their migration is reviewed.

## Imports

Before:

```python
from async_hyperliquid.async_hyperliquid import AsyncHyper, AsyncHyperliquid
from async_hyperliquid.info import InfoAPI
from async_hyperliquid.utils.types import LimitTif
```

After:

```python
from async_hyperliquid import AsyncHyperliquid, InfoClient
from async_hyperliquid.types import (
    Network,
    PlaceOrderRequest,
    TimeInForce,
    limit_order_type,
)
```

The package root exports exactly `AsyncHyperliquid`, `InfoClient`, and
`HyperliquidError`. Commands and enums live in `async_hyperliquid.types`.
Detailed response types live in `async_hyperliquid.types.info` and
`async_hyperliquid.types.exchange`.

Removed imports fail immediately. They do not resolve to deprecated aliases.

## Constructor

Before:

```python
client = AsyncHyperliquid(
    address,
    api_key,
    is_mainnet=True,
    enable_evm=False,
    vault=None,
    perp_dexs=["", "xyz"],
)
```

After:

```python
client = AsyncHyperliquid(
    account_address=address,
    signing_key=api_key,
    vault_address=vault,
    network=Network.MAINNET,
    dexs=("", "xyz"),
)
```

| 0.5 argument or state | 1.0 replacement |
|---|---|
| `address` | `account_address` |
| `api_key` | `signing_key` |
| `is_mainnet=True` | `network=Network.MAINNET` |
| `is_mainnet=False` | `network=Network.TESTNET` |
| mutable `base_url` | immutable constructor-time `info_url` and/or `exchange_url` |
| `perp_dexs: list[str]` | `dexs: tuple[str, ...]` |
| `connector` | construct an `aiohttp.ClientSession` with that connector and pass `session=` |
| `enable_evm`, `evm_rpc_url`, `private_key` | use `hl-web3` directly |
| client-wide `vault` | immutable constructor-time `vault_address` |
| mutable `expires` | pass `expires_after=` to each supported action |

`Network` selects the signing domain and the official URL defaults. Neither
custom URL can change the signing domain.

`vault_address` is the immutable execution target for the client. It is
carried through execution-scoped L1 signing/envelopes and position lookup, and
through the protocol-specific subaccount fields used by USD class and asset
transfers. Root-scoped administration actions still sign as the main account.
Omitting it targets the main account everywhere.

## Read-only clients no longer need fake credentials

Do not generate an ephemeral private key or placeholder address to read Info:

```python
async with InfoClient(
    network=Network.MAINNET,
    info_url="http://127.0.0.1:3001/info",
) as info:
    positions = await info.positions(account_address)
```

Every account-specific Info method accepts the queried address explicitly. An
`InfoClient` has no signer and no Exchange capability.

## Flat facade methods

`AsyncHyperliquid` is the lifecycle and cross-client orchestration owner. It has no `__getattr__` and
does not forward endpoint calls.

Common read mappings:

| 0.5 | 1.0 |
|---|---|
| `client.init_metas()` | `client.info.refresh_metadata()` |
| `client.get_all_dex_name()` | `client.info.perp_dex_names()` |
| `client.get_coin_name(coin)` | `client.info.coin_name(coin)` |
| `client.get_coin_symbol(coin)` | `client.info.coin_symbol(coin)` |
| `client.get_coin_asset(coin)` | `client.info.asset_id(coin)` |
| `client.get_coin_sz_decimals(coin)` | `client.info.size_decimals(coin)` |
| `client.get_token_info(coin)` | `client.info.spot_token_metadata(coin)` |
| `client.get_token_id(coin)` | `client.info.token_id(coin)` |
| `client.get_mark_price(coin)` | `client.info.mark_price(coin)` |
| `client.get_mid_price(coin)` | `client.info.mid_price(coin)` |
| `client.get_account_state()` | `client.info.account_state(account_address)` |
| `client.get_user_open_orders()` | `client.info.open_orders(account_address)` |
| `client.get_order_status(oid)` | `client.info.order_status(account_address, oid)` |
| `client.get_all_positions()` | `client.info.positions(account_address)` |
| `client.get_user_abstraction()` | `client.info.user_abstraction(account_address)` |

Raw `InfoAPI.get_*` methods use the same direct naming rule:

| 0.5 | 1.0 |
|---|---|
| `get_all_mids` | `all_mids` |
| `get_user_fills` | `user_fills` |
| `get_user_rate_limit` | `user_rate_limit` |
| `get_depth` | `l2_book` |
| `get_candles` | `candles` |
| `get_perp_meta` | `perp_meta` |
| `get_perp_meta_ctx` | `perp_meta_and_contexts` |
| `get_all_perp_metas` | `all_perp_metas` |
| `get_perp_dexs` | `perp_dexes` |
| `get_perp_clearinghouse_state` | `perp_account_state` |
| `get_spot_meta` | `spot_meta` |
| `get_spot_meta_ctx` | `spot_meta_and_contexts` |
| `get_spot_clearinghouse_state` | `spot_account_state` |

## One typed order-request vocabulary

Before:

```python
await client.place_order(
    coin="BTC",
    is_buy=True,
    sz=0.001,
    px=50_000,
    order_type={"limit": {"tif": "Gtc"}},
)
```

After, the compatibility root call remains expanded:

```python
await client.place_order(
    coin="BTC",
    is_buy=True,
    sz=0.001,
    px=50_000,
    is_market=False,
    order_type=limit_order_type(TimeInForce.GTC),
)
```

Direct and batch root workflows use the same JSON-shaped `TypedDict` request:

```python
order: PlaceOrderRequest = {
    "coin": "BTC",
    "is_buy": True,
    "sz": 0.001,
    "px": 50_000,
    "is_market": False,
    "order_type": limit_order_type(TimeInForce.GTC),
}
await client.place_limit_order(order)
await client.place_orders((order,))
```

`LimitOrderOption` and `TriggerOrderOption` are singular because each order has
one option object. `TimeInForce` is nested under `limit.tif`; it is not an order
type. Use `is_buy: bool` for commands and `cloid` everywhere. Builder
attribution is passed separately as `builder=Builder(...)`.

`place_orders` now owns every batch placement path, including market orders;
the provisional RC1 `place_market_orders` helper was removed. A batch may mix
outer market and non-market requests, and a perpetual batch may span the base
and HIP-3 DEXes. It cannot mix perpetual markets with spot or outcome markets.
Builder fees are capped at `100` tenths of a basis point for perpetuals and
`1000` for spot/outcome after metadata resolution. Outcome prices use a
`0.00001` USDC tick in the `0.00001..0.99999` range. The Exchange, not the SDK,
validates minimum order notional.

Common write mappings:

| 0.5 | 1.0 |
|---|---|
| `place_order(...)`, `place_typed_order(...)` | root `place_order(...)` or root `place_*_order(request)` |
| `batch_place_orders(items)` | root `place_orders(requests)` / identical `batch_place_orders` alias |
| `cancel_order`, `batch_cancel_orders` | root `cancel_order(...)` / `cancel_orders(...)` |
| `cancel_by_cloid`, `batch_cancel_by_cloid` | root `cancel_orders_by_cloid(tuple_of_CancelByCloid)` |
| `modify_order`, `batch_modify_orders` | root `modify_order(request)` / `modify_orders(requests)` |
| `close_position(coin)` | root `close_position(coin)` |
| `close_all_positions()` | root `close_all_positions()` |
| `close_dex_positions(dex)` | root `close_all_positions(dexs=(dex,))` |
| `initiate_withdrawal(amount)` | `exchange.withdraw(amount)` |
| `use_big_block(enabled)` | `exchange.use_big_blocks(enabled)` |

`modify_order(request)` returns the Exchange's default acknowledgement.
`modify_orders(requests)` returns per-order statuses because `batchModify`
uses the order response envelope.

Info-independent actions such as `usd_transfer`, `vault_transfer`,
`approve_agent`, `approve_builder_fee`, staking, delegation, and abstraction
remain on `.exchange`. Coin-resolving token transfers, TWAP, leverage, and
margin workflows live on the root client.

Close workflows always read the current full position size and submit one
reduce-only market batch. The removed `size` and `slippage` parameters are not
replaced; use `place_order(..., ro=True)` for a partial reduction.

Public request parameters use `dex`/`dexs`. The method
`InfoClient.perp_dexes()` keeps its name only because it calls the official
`perpDexs` Info endpoint.

## Endpoint routing

Post-construction mutation is removed:

```python
# Removed: this could leave a cached request URL unchanged.
client.info.base_url = local_info_url
```

Construct the endpoint you intend to use:

```python
info = InfoClient(info_url=local_info_url)

client = AsyncHyperliquid(
    account_address,
    signing_key,
    network=Network.MAINNET,
    info_url=local_info_url,
    exchange_url=provider_exchange_url,
)
```

URLs are independent and exact:

- `info_url` receives unsigned Info payloads only;
- `exchange_url` receives signed action envelopes only;
- the signing key never leaves the process;
- `network` remains the signing source even when either URL is custom.

The application remains responsible for provider headers, fallback, health
checks, and routing policy.

A custom Exchange URL is a trusted execution boundary: the provider sees
replayable signed envelopes and can delay, censor, or fabricate a well-shaped
acknowledgement. A custom Info endpoint attached to `AsyncHyperliquid` is also
trusted order-construction input because its metadata and prices determine the
asset ids, precision, and limit prices used in signed actions. Reconcile signed
outcomes through an independently trusted Info endpoint. `expires_after`
applies only to L1 methods that expose it; it does not add expiry semantics to
user-signed fund actions.

Because `.info` and `.exchange` share the supplied session, never use
session-wide authorization headers or cookies across different origins.
Authenticate with host-scoped aiohttp middleware, or use separately owned
clients and sessions.

## Lifecycle

0.5 could create `ClientSession` during synchronous construction. Version 1
does not allocate asynchronous resources until `open()` or `async with`.

```python
async with AsyncHyperliquid(address, key, network=Network.TESTNET) as client:
    ...
```

An internally created session is owned and closed by the client. A supplied
session is borrowed and remains the caller's responsibility. Closing is
idempotent; reopening a closed client is an error.

## Signed-action failures

Version 1 never retries signed actions automatically. If the request may have
reached the Exchange but no trusted acknowledgement was received,
`IndeterminateActionError` includes the action type and nonce.

Reconcile the outcome through Info before submitting a replacement. Depending
on the action, use `order_status`, `open_orders`, `user_fills`, account state,
or the corresponding action-specific Info query.

Nonce monotonicity is guaranteed only within one `ExchangeClient`. Keep exactly
one live Exchange owner per API wallet private key. If several processes or
services must share a key, the application must serialize submissions and
coordinate the nonce stream; version 1 does not add a distributed nonce
service.

## Embedded EVM removal

The REST client no longer imports or initializes `hl-web3`. Existing EVM users
should depend on and construct `hl-web3` directly. There is no adapter in the
v1 core.

## Rollback

The v1 package contains no legacy execution path. Roll back an application by:

1. reverting its v1 call-site migration;
2. pinning `async-hyperliquid<1`;
3. restoring the previously reviewed lock file.

Do not attempt to make one process support both object topologies through
runtime method detection or forwarding wrappers.
