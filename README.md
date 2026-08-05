# Async Hyperliquid

Typed, asynchronous Hyperliquid REST client for Python.

Version 1 has two explicit entry points:

- `InfoClient` is credential-free and only calls the Info API.
- `AsyncHyperliquid` owns one shared HTTP transport and exposes concrete
  `.info` and `.exchange` clients. It always requires an account address and
  signing key.

The client uses `aiohttp` and preserves Hyperliquid's JSON-shaped requests and
responses as `TypedDict`. Small value inputs such as `Builder` remain frozen,
slotted dataclasses; responses are not wrapped in runtime model layers.

## Installation

```bash
pip install async-hyperliquid
```

With uv:

```bash
uv add async-hyperliquid
```

## Read-only use

Read-only callers do not need an address, API wallet, or generated private key.
`info_url` may be an official endpoint, a self-hosted node, or a compatible
third-party provider. The URL is used exactly as supplied, so include the
provider's complete `/info` path.

```python
import asyncio

from async_hyperliquid import InfoClient
from async_hyperliquid.types import Network


async def main() -> None:
    async with InfoClient(
        network=Network.MAINNET,
        info_url="https://provider.example/hyperliquid/info",
    ) as info:
        mids = await info.all_mids()
        positions = await info.positions(
            "0x0000000000000000000000000000000000000000"
        )
        print(mids.get("BTC"), positions)


asyncio.run(main())
```

Omit `info_url` to use `Network.MAINNET.info_url` or
`Network.TESTNET.info_url`.

## Trading

Trading is deliberately separate from read-only access. `AsyncHyperliquid`
requires both credentials. Read from `client.info`, call `client.exchange` for
Info-independent signed actions, and use root workflows when a request needs
both market data and signed execution.

```python
import asyncio
import os

from async_hyperliquid import AsyncHyperliquid
from async_hyperliquid.types import Network, PlaceOrderRequest, TimeInForce, limit_order_type


async def main() -> None:
    async with AsyncHyperliquid(
        os.environ["HL_ADDR"],
        os.environ["HL_SK"],
        vault_address=os.environ["HL_SUB"],
        network=Network.TESTNET,
    ) as client:
        order: PlaceOrderRequest = {
            "coin": "BTC",
            "is_buy": True,
            "sz": 0.001,
            "px": 50_000,
            "is_market": False,
            "order_type": limit_order_type(TimeInForce.ALO),
        }
        result = await client.place_limit_order(order)
        print(result)


asyncio.run(main())
```

`HL_SK` is the API-wallet private key. It is parsed locally and is never sent
to an Info or Exchange provider. `HL_AK` is the corresponding public API-wallet
address; it is not a signing key and it is not a portfolio address.

Set `vault_address=` when the signer trades on behalf of a Hyperliquid vault or
subaccount:

```python
client = AsyncHyperliquid(
    os.environ["HL_ADDR"],
    os.environ["HL_SK"],
    vault_address=os.environ["HL_SUB"],
    network=Network.MAINNET,
)
```

The address is normalized once and becomes the client's execution target.
Execution-scoped L1 actions such as orders and cancels sign and post with that
target, and account-dependent helpers such as `close_positions` query it.
Root-scoped administration actions sign as the main account; protocol-specific
transfers encode the vault/subaccount in their own action fields. Omit
`vault_address` to trade the main account. A client cannot be retargeted after
construction; concurrent targets should use separately owned API wallet/client
pairs.

### Batch actions

One `place_orders` call creates one action, one signature, and one HTTP POST.
Use it instead of looping when the orders belong in one atomic Hyperliquid
batch.

```python
import asyncio
import os

from async_hyperliquid import AsyncHyperliquid
from async_hyperliquid.types import Network, PlaceOrderRequest, TimeInForce, limit_order_type


async def main() -> None:
    orders: tuple[PlaceOrderRequest, ...] = (
        {
            "coin": "BTC",
            "is_buy": True,
            "sz": 0.001,
            "px": 50_000,
            "is_market": False,
            "order_type": limit_order_type(TimeInForce.GTC),
        },
        {
            "coin": "ETH",
            "is_buy": False,
            "sz": 0.01,
            "px": 4_000,
            "is_market": False,
            "order_type": limit_order_type(TimeInForce.GTC),
        },
    )
    async with AsyncHyperliquid(
        os.environ["HL_ADDR"],
        os.environ["HL_SK"],
        vault_address=os.environ["HL_SUB"],
        network=Network.TESTNET,
    ) as client:
        result = await client.place_orders(orders)
        print(result)


asyncio.run(main())
```

`PlaceOrderRequest` is the one placement vocabulary for direct and batch order
methods, and `is_market` is explicit on every request. `ModifyOrderRequest`
adds `oid` to the same shared order fields.
`LimitOrderOption` and `TriggerOrderOption` mirror the protocol's nested order
type, `cloid` is the only client-order-ID spelling, and order attribution uses
`Builder`.

`place_orders` is the only batch placement pipeline. It accepts market and
non-market requests together when they resolve to the same venue, normalizes
only the market subset in one batched mid-price phase (one `allMids` call per
distinct DEX), and rejects a spot/perpetual mixture before signing. Use
`place_market_order` for one market request and `place_orders` for a market
batch.

Builder fees are expressed in tenths of a basis point and are capped at `100`
for perpetual batches and `1000` for spot or outcome batches. The venue is
selected from resolved metadata; a spot buy with builder attribution is not
rejected locally. Outcome order prices use the `0.00001` USDC tick and must be
between `0.00001` and `0.99999` USDC. Minimum order notional is validated by
the Exchange, not by this SDK.

### Root trading workflows

`AsyncHyperliquid.place_order(...)` deliberately keeps the expanded 0.5 call
shape. `is_market=True` selects market-price discovery; otherwise the nested
`order_type` selects limit or trigger placement. `place_orders` consumes typed
requests, and `batch_place_orders` is the same function—not a forwarding
wrapper.

Order placement, cancellation, modification, TWAP, leverage, margin, and token
actions that resolve coin metadata live on `AsyncHyperliquid`. The concrete
`ExchangeClient` owns only Info-independent action construction, nonce/signing,
vault targeting, and submission; it never holds an `InfoClient`.

`close_position`, `close_positions`, and `close_all_positions` close the full
live size. They expose no size or slippage override. One workflow performs one
position query and submits all required reduce-only market orders in one
Exchange batch.

## Network and endpoint routing

`Network` is the only signing-domain selector. URLs never decide whether an
action is signed for mainnet or testnet.

| Setting | Responsibility |
|---|---|
| `network` | Signing domain and official endpoint defaults |
| `info_url` | Exact URL used only by `InfoClient` |
| `exchange_url` | Exact URL used only by `ExchangeClient` |

This supports independently routing reads and writes:

```python
import asyncio
import os

from async_hyperliquid import AsyncHyperliquid
from async_hyperliquid.types import Network


async def main() -> None:
    async with AsyncHyperliquid(
        os.environ["HL_ADDR"],
        os.environ["HL_SK"],
        vault_address=os.environ["HL_SUB"],
        network=Network.MAINNET,
        info_url="http://127.0.0.1:3001/info",
        exchange_url="https://trading-provider.example/exchange",
    ) as client:
        print(await client.info.mid_price("BTC"))


asyncio.run(main())
```

The example still signs for mainnet. The self-hosted Info node receives
unsigned Info requests. Its metadata and prices nevertheless determine the
asset ids, precision, and limit prices used to build signed actions, so an Info
provider attached to an authenticated client is trusted order-construction
input. The Exchange provider receives the signed action envelope, never the
signing key. Redirects are rejected; each configured URL is the exact request
destination.

The library does not add endpoint fallback, provider authentication, health
checks, or load balancing. Applications own those policies.

A custom Exchange provider is a trusted execution boundary. It can observe
replayable signed envelopes, delay or censor them, and fabricate a well-shaped
acknowledgement. A custom Info provider used only through standalone
`InfoClient` remains read-only, but one used by `AsyncHyperliquid` must also be
independently trusted because its data shapes signing intent. `expires_after`
limits only L1 actions that expose that parameter; it does not add an expiry to
user-signed fund actions. Reconcile through an independently trusted
`InfoClient` endpoint before resubmitting an indeterminate action.

## Lifecycle and sessions

Constructors do not create asynchronous resources. Prefer `async with`, or call
`open()` and `close()` explicitly.

When no session is supplied, the client owns and closes one session. When an
`aiohttp.ClientSession` is supplied, the client borrows it and never closes it.
`AsyncHyperliquid.info` and `.exchange` share exactly one transport.

Do not place an `Authorization` header or provider cookie on that shared
session when Info and Exchange use different origins: session-wide credentials
would be sent to both. Attach credentials with host-scoped aiohttp middleware,
or use separate clients/sessions for separately authenticated providers.

```python
import os

from aiohttp import ClientHandlerType, ClientRequest, ClientResponse, ClientSession

from async_hyperliquid import AsyncHyperliquid


async def provider_auth(
    request: ClientRequest, handler: ClientHandlerType
) -> ClientResponse:
    if request.url.host == "trading-provider.example":
        request.headers["Authorization"] = f"Bearer {os.environ['PROVIDER_TOKEN']}"
    return await handler(request)


async def main() -> None:
    async with ClientSession(middlewares=(provider_auth,)) as session:
        async with AsyncHyperliquid(
            os.environ["HL_ADDR"],
            os.environ["HL_SK"],
            vault_address=os.environ["HL_SUB"],
            info_url="http://127.0.0.1:3001/info",
            exchange_url="https://trading-provider.example/exchange",
            session=session,
        ):
            ...
```

The default timeout has finite total, connect, and socket-read budgets. A
custom `aiohttp.ClientTimeout` must keep its total budget finite and positive;
optional phase budgets are validated when provided.

## Errors and signed-action reconciliation

All library errors derive from `HyperliquidError`. Import detailed error types
from `async_hyperliquid.errors`.

A timeout, connection failure, non-success HTTP response, or untrusted JSON
response after submitting a signed action raises `IndeterminateActionError`.
The client does not retry signed actions automatically: the server may already
have accepted the nonce. Reconcile using Info calls such as `order_status`,
`open_orders`, or `user_fills` before deciding whether to submit another
action.

Nonce ordering is local to one `ExchangeClient`. One API wallet private key
must therefore have exactly one live owner submitting Exchange actions.
Multiple processes or services sharing the same API wallet must serialize and
coordinate nonces at the application boundary; this library deliberately does
not provide a distributed nonce service. This restriction does not apply to
credential-free `InfoClient` instances.

## Typing

The package includes `py.typed`.

- Info and Exchange wire responses use exact `TypedDict` contracts.
- JSON-shaped order commands use `TypedDict`; value objects use frozen,
  slotted dataclasses.
- Public signatures contain no `Any` or unparameterized containers.
- Response dictionaries are not copied into runtime model objects.

## Testing

The default deterministic suite performs no network API calls. Run it
separately from the live integration suites:

```bash
uv run pytest -q tests/unit tests/contracts tests/oracle tests/public_api tests/package
uv run ruff check src tests benchmarks
uv run ty check src
uv run ty check tests/contracts
uv run ty check tests/integration
uv run ty check tests/oracle
uv run ty check tests/package
uv run ty check tests/public_api
uv run ty check tests/typing
uv run ty check tests/unit
uv run ty check benchmarks
```

### Signing benchmark

The repository includes a parity-gated CPU benchmark of the real CCXT,
official SDK, and async-hyperliquid signing implementations. It reports action
hashing, signing-only, and order-to-payload construction separately; imports,
initialization, metadata, HTTP, and subprocess startup are outside the timed
loops.

```bash
uv run --frozen --group benchmark python benchmarks/signing.py --rounds 7 --warmups 1 --iterations 5000
```

See the
[reproducible benchmark manual](https://github.com/traderfiapp/async-hyperliquid/blob/master/benchmarks/README.md)
for environment setup, fairness gates, exact measurement semantics, JSON
output, and result interpretation.

#### Local overall result

On an Apple M5 with Python 3.12.13 and CoinCurve 21.0.0, three independent
complete runs produced this equal-weight, geometric-mean throughput across all
five measured operations:

| Library | Overall throughput | Relative to SDK |
|---|---:|---:|
| async-hyperliquid 1.0.0rc1 | 24,641 ops/s | 1.460x |
| hyperliquid-python-sdk 0.24.0 | 16,874 ops/s | 1.000x |
| CCXT 4.5.71 | 803 ops/s | 0.0476x |

Higher is better. This is a synthetic signing/payload-construction score, not
end-to-end order latency. Every report used seven measured rounds after one
warmup, and CCXT's CoinCurve signer was verified before timing. The detailed
manual contains the machine specification, per-operation median/MAD/p95,
throughput, aggregation formula, and exact reproduction command.

### Live Exchange benchmark

The repository also includes a rate-controlled BTC perpetual testnet benchmark
for concurrent async-hyperliquid cancellation by order ID (OID) and client
order ID (CLOID). Each logical round places 20 ALO orders in one batch: ten
buys at 90% of mid and ten sells at 110%, approximately 11 USDC each. It then
releases ten OID and ten CLOID independent single-order cancellations through a
shared start gate. See the
[live benchmark safety and reproduction manual](https://github.com/traderfiapp/async-hyperliquid/blob/master/benchmarks/README.md#live-exchange-benchmark)
before running it because it submits real testnet orders.

<!-- live-exchange-benchmark:overall:start -->
#### Published live Exchange result

The validated testnet run uses concurrency=20 (10 OID + 10 CLOID) single-order cancellation requests per measured round.

| Identifier | Individual median (ms) | Individual p95 (ms) | Round-max median (ms) | Round-max p95 (ms) |
|---|---:|---:|---:|---:|
| OID | 916.78 | 1003.99 | 948.75 | 1131.51 |
| CLOID | 913.98 | 1001.03 | 945.31 | 1026.93 |

See the [detailed methodology, distributions, and artifacts](benchmarks/README.md#published-live-exchange-benchmark).
<!-- live-exchange-benchmark:overall:end -->

The credential-free Info command always runs the complete suite against both
MAINNET and TESTNET:

```bash
uv run pytest -q tests/integration/test_info.py
```

On the first HTTP 429 response, the Info integration client waits 60 seconds
and retries the request once; a second 429 skips the affected case. A TESTNET
5xx response emits a warning and skips the affected case, while the same
MAINNET failure remains a test failure.

Signed Exchange integration is testnet-only and uses `IS_MAINNET` as its only
network safety gate. Set it explicitly to `false` when running the suite;
missing, empty, `true`, or malformed values hard-fail before credentials or
clients are used:

```bash
IS_MAINNET=false uv run pytest -q tests/integration/exchange
```

Pytest and VS Code always collect the Info and Exchange cases. There are no
additional integration-suite execution flags.

The local `.env.local` roles are:

| Variable | Role |
|---|---|
| `HL_ADDR` | master account address and portfolio identity |
| `HL_PK` | master account private key for master-only actions |
| `HL_AK` | API-wallet public address used only for role/key validation |
| `HL_SK` | API-wallet private key used for signed trading |
| `HL_SUB` | subaccount execution and portfolio address |

Tests validate that each private key derives the declared public address, that
local SDK and async-hyperliquid payloads match exactly, that `HL_AK` is an API
wallet for `HL_ADDR`, and that `HL_SUB` belongs to `HL_ADDR`. Private keys,
real signatures, and real payloads are never included in assertion messages,
logs, or fixtures.

## Migrating from 0.5

Version 1 intentionally removes the dynamic facade, flat forwarding methods,
legacy aliases, mutable endpoint reassignment, and embedded EVM client. See
[the 0.5 to 1.0 migration guide](https://github.com/traderfiapp/async-hyperliquid/blob/master/docs/migration-0.5-to-1.0.md).

## License

MIT. This community project is not affiliated with Hyperliquid.
