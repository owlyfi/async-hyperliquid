# Async Hyperliquid

Typed, asynchronous Hyperliquid REST client for Python.

Version 1 has two explicit entry points:

- `InfoClient` is credential-free and only calls the Info API.
- `AsyncHyperliquid` owns one shared HTTP transport and exposes concrete
  `.info` and `.exchange` clients. It always requires an account address and
  signing key.

The client uses `aiohttp`, preserves Hyperliquid's raw JSON response shapes as
`TypedDict`, and represents caller-created commands as immutable, slotted
dataclasses.

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
requires both credentials and exposes no forwarded endpoint methods: read from
`client.info` and submit signed actions through `client.exchange`.

```python
import asyncio
import os

from async_hyperliquid import AsyncHyperliquid
from async_hyperliquid.types import LimitOrder, Network, Side, TimeInForce


async def main() -> None:
    async with AsyncHyperliquid(
        os.environ["HL_ADDR"],
        os.environ["HL_AK"],
        network=Network.TESTNET,
    ) as client:
        result = await client.exchange.place_limit_order(
            LimitOrder(
                coin="BTC",
                side=Side.BUY,
                size=0.001,
                price=50_000,
                time_in_force=TimeInForce.ALO,
            )
        )
        print(result)


asyncio.run(main())
```

`HL_AK` is a 32-byte private key. It is parsed locally and is never sent to an
Info or Exchange provider.

Set `vault_address=` when the signer trades on behalf of a Hyperliquid vault or
subaccount:

```python
client = AsyncHyperliquid(
    os.environ["HL_ADDR"],
    os.environ["HL_AK"],
    vault_address=os.environ["HL_VAULT_ADDR"],
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
from async_hyperliquid.types import LimitOrder, Network, Side


async def main() -> None:
    orders = (
        LimitOrder("BTC", Side.BUY, size=0.001, price=50_000),
        LimitOrder("ETH", Side.SELL, size=0.01, price=4_000),
    )
    async with AsyncHyperliquid(
        os.environ["HL_ADDR"],
        os.environ["HL_AK"],
        network=Network.TESTNET,
    ) as client:
        result = await client.exchange.place_orders(orders)
        print(result)


asyncio.run(main())
```

The command types exported from `async_hyperliquid.types` include
`LimitOrder`, `TriggerOrder`, `MarketOrder`, `ModifyOrder`, `CancelOrder`,
`CancelByCloid`, `BuilderFee`, and `Cloid`.

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
        os.environ["HL_AK"],
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
            os.environ["HL_AK"],
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
- Commands use frozen, slotted dataclasses.
- Public signatures contain no `Any` or unparameterized containers.
- Response dictionaries are not copied into runtime model objects.

## Testing

The default suite performs no live API calls:

```bash
uv run pytest -q tests/unit tests/contracts tests/public_api tests/package
uv run ruff check src tests scripts
uv run ty check src
uv run ty check tests
uv run ty check scripts
```

Read-only live tests require `RUN_LIVE_INFO_TESTS=true`. Signed integration is
restricted to testnet and additionally requires
`RUN_LIVE_EXCHANGE_TESTS=true`, `IS_MAINNET=false`, `HL_ADDR`, and `HL_AK`.

## Migrating from 0.5

Version 1 intentionally removes the dynamic facade, flat forwarding methods,
legacy aliases, mutable endpoint reassignment, and embedded EVM client. See
[the 0.5 to 1.0 migration guide](https://github.com/traderfiapp/async-hyperliquid/blob/master/docs/migration-0.5-to-1.0.md).

## License

MIT. This community project is not affiliated with Hyperliquid.
