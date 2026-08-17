# Async Hyperliquid

[![CI](https://github.com/owlyfi/async-hyperliquid/actions/workflows/ci.yml/badge.svg)](https://github.com/owlyfi/async-hyperliquid/actions/workflows/ci.yml)
[![Documentation Status](https://readthedocs.org/projects/async-hyperliquid/badge/?version=latest)](https://async-hyperliquid.readthedocs.io/en/latest/)
[![PyPI](https://img.shields.io/pypi/v/async-hyperliquid.svg?v=1.0.0)](https://pypi.org/project/async-hyperliquid/)

`async-hyperliquid` is a typed, asynchronous Python client for the Hyperliquid
REST API. It provides credential-free market and account queries through
`InfoClient`, plus authenticated order workflows through `AsyncHyperliquid`.
The client uses `aiohttp`, keeps protocol-shaped responses as `TypedDict`, and
supports explicit mainnet and testnet routing.

## Installation

```bash
pip install async-hyperliquid
```

## Read market data

```python
import asyncio

from async_hyperliquid import InfoClient
from async_hyperliquid.types import Network


async def main() -> None:
    async with InfoClient(network=Network.MAINNET) as client:
        print(await client.mid_price("BTC"))


asyncio.run(main())
```

## Place a testnet order

Use a dedicated API-wallet key and start on testnet. This submits a signed
market order.

```python
import asyncio
import os

from async_hyperliquid import AsyncHyperliquid
from async_hyperliquid.types import Network


async def main() -> None:
    async with AsyncHyperliquid(
        os.environ["HL_ACCOUNT_ADDRESS"],
        os.environ["HL_SIGNING_KEY"],
        network=Network.TESTNET,
    ) as client:
        result = await client.place_order("BTC", True, 0.001, 0, is_market=True)
        print(result)


asyncio.run(main())
```

Learn more in the [Read the Docs documentation](https://async-hyperliquid.readthedocs.io/en/latest/),
[API reference](https://async-hyperliquid.readthedocs.io/en/latest/reference/index.html),
[migration guide](https://async-hyperliquid.readthedocs.io/en/latest/migration-0.5-to-1.0.html),
[changelog](CHANGELOG.md), and [license](LICENSE).
