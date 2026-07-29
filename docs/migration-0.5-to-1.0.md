# Migrating async-hyperliquid 0.5 to 1.0

Version 1 is a deliberate API break. It removes the dynamic facade and replaces
implicit state with two explicit clients:

- use `InfoClient` for every credential-free read;
- use `AsyncHyperliquid` when signed Exchange actions are required, then call
  `.info` or `.exchange` directly.

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
from async_hyperliquid.types import Network, TimeInForce
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
    network=Network.MAINNET,
    perp_dexes=("", "xyz"),
)
```

| 0.5 argument or state | 1.0 replacement |
|---|---|
| `address` | `account_address` |
| `api_key` | `signing_key` |
| `is_mainnet=True` | `network=Network.MAINNET` |
| `is_mainnet=False` | `network=Network.TESTNET` |
| mutable `base_url` | immutable constructor-time `info_url` and/or `exchange_url` |
| `perp_dexs: list[str]` | `perp_dexes: tuple[str, ...]` |
| `connector` | construct an `aiohttp.ClientSession` with that connector and pass `session=` |
| `enable_evm`, `evm_rpc_url`, `private_key` | use `hl-web3` directly |
| client-wide `vault` / mutable `expires` | pass supported action-scoped arguments explicitly |

`Network` selects the signing domain and the official URL defaults. Neither
custom URL can change the signing domain.

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

`AsyncHyperliquid` is now only the lifecycle owner. It has no `__getattr__` and
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

## Typed commands replace request dictionaries

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

After:

```python
await client.exchange.place_limit_order(
    LimitOrder(
        coin="BTC",
        side=Side.BUY,
        size=0.001,
        price=50_000,
        time_in_force=TimeInForce.GTC,
    )
)
```

Commands are frozen, slotted dataclasses and are never mutated during
encoding.

Common write mappings:

| 0.5 | 1.0 |
|---|---|
| `place_order(...)`, `place_typed_order(...)` | `exchange.place_limit_order(LimitOrder(...))` or `exchange.place_market_order(MarketOrder(...))` |
| `batch_place_orders(items)` | `exchange.place_orders(tuple_of_commands)` |
| `cancel_order`, `batch_cancel_orders` | `exchange.cancel_orders(tuple_of_CancelOrder)` |
| `cancel_by_cloid`, `batch_cancel_by_cloid` | `exchange.cancel_orders_by_cloid(tuple_of_CancelByCloid)` |
| `modify_order`, `batch_modify_orders` | `exchange.modify_orders(tuple_of_ModifyOrder)` |
| `close_position(coin)` | `exchange.close_positions((coin,))` |
| `close_all_positions()` | `exchange.close_positions()` |
| `close_dex_positions(dex)` | `exchange.close_positions(perp_dexes=(dex,))` |
| `initiate_withdrawal(amount)` | `exchange.withdraw(amount)` |
| `use_big_block(enabled)` | `exchange.use_big_blocks(enabled)` |

Action methods such as `usd_transfer`, `spot_transfer`, `vault_transfer`,
`approve_agent`, `approve_builder_fee`, staking, delegation, abstraction, TWAP,
leverage, and margin updates remain available on `.exchange` with explicit,
typed parameter names.

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

## Embedded EVM removal

The REST client no longer imports or initializes `hl-web3`. Existing EVM users
should depend on and construct `hl-web3` directly. There is no adapter in the
v1 core.

## Copycat is a separate repository migration

No Copycat file is changed by the async-hyperliquid v1 branch. Its migration
must be reviewed and committed in the Copycat repository.

Before stable v1 is allowed into the existing integration, Copycat should first
pin its legacy dependency to `async-hyperliquid>=0.4.8,<1`.

The later Copycat v1 migration should:

1. use a standalone `InfoClient(info_url=HL_INFO)` for local/self-hosted reads;
2. remove ephemeral or dummy key generation from that read-only path after
   proving no remaining call needs Exchange capability;
3. pass all endpoints at construction and remove `info.base_url` mutation and
   session reassignment;
4. construct its authenticated trading client with `network=Network.*` and use
   `.info` / `.exchange` explicitly;
5. preserve local-first, official-Info fallback and supported-request
   whitelisting in Copycat, not in this library;
6. add an Exchange override only if Copycat explicitly configures a compatible
   third-party Exchange provider;
7. validate local Info success, official fallback, unsupported local request
   rejection, signing parity, testnet order/cancel, reinitialization, and
   deterministic session closure.

Keep the dependency guard, v1 API migration, and unrelated bot changes in
separate Copycat commits.

## Rollback

The v1 package contains no legacy execution path. Roll back an application by:

1. reverting its v1 call-site migration;
2. pinning `async-hyperliquid<1`;
3. restoring the previously reviewed lock file.

Do not attempt to make one process support both object topologies through
runtime method detection or forwarding wrappers.
