# Coin and asset mapping

`InfoClient` builds one immutable metadata snapshot from `perpDexs`,
`allPerpMetas`, and `spotMeta`. Public helpers read that snapshot directly:

- `coin_name(coin)` returns the canonical market name used by Hyperliquid.
- `coin_symbol(coin)` returns the display symbol.
- `asset_id(coin)` returns the integer encoded in Exchange actions.
- `size_decimals(coin)` returns the market size precision.
- `spot_token_metadata(coin)` returns the base-token metadata for a spot pair.

The first lookup loads metadata. Concurrent cold lookups share one load;
`refresh_metadata()` explicitly replaces the last complete snapshot. A partial
or inconsistent response is rejected without publishing partial state.

## Asset spaces

| Market | Asset ID |
|---|---|
| Base perpetual | index in the base perpetual universe |
| Spot | `10_000 + spotMeta.universe[].index` |
| HIP-3 perpetual | `110_000 + (dex position - 1) * 10_000 + universe index` |

The DEX position comes from `perpDexs`, whose first entry must be the base DEX.
Every declared DEX must have exactly one matching `allPerpMetas` object.

## Perpetual markets

Perpetual names are already canonical:

| Input | Canonical name | Example asset ID |
|---|---|---|
| `BTC` | `BTC` | base universe index, commonly `0` |
| `xyz:NVDA` | `xyz:NVDA` | first HIP-3 offset plus its universe index |

The prefix before `:` identifies an HIP-3 DEX.

## Spot markets

`spotMeta.universe[].name` is the canonical market name. It may be an internal
name such as `@107` or an already readable pair name. The token indexes in the
same entry provide a `BASE/QUOTE` alias:

| Input | Canonical name | Display symbol |
|---|---|---|
| `@107` | `@107` | `HYPE/USDC` |
| `HYPE/USDC` | `@107` | `HYPE/USDC` |
| `PURR/USDC` | `PURR/USDC` when that is the wire name | `PURR/USDC` |

Some spot tokens retain a protocol-facing `U` prefix while the Hyperliquid UI
omits it. The client accepts the UI spelling without changing the canonical
wire name:

| Metadata symbol | Accepted UI alias |
|---|---|
| `UBTC/USDC` | `BTC/USDC` |
| `UETH/USDC` | `ETH/USDC` |
| `USOL/USDC` | `SOL/USDC` |
| `USDT0/USDC` | `USDT/USDC` |
| `UPUMP/USDC` | `PUMP/USDC` |

The UI alias takes precedence when it collides with an older metadata symbol.
On current mainnet metadata, `PUMP/USDC` therefore resolves to the UPUMP market
(`@188`). The legacy PUMP market remains addressable by its canonical wire name
`@20`.

Only pairs present in `spotMeta.universe` resolve. A quote token alias such as
`USDC` can resolve token metadata without representing a tradable market.

Do not derive `@...` names or asset IDs in application code; they are runtime
metadata and can change.

## Usage

```python
from async_hyperliquid import InfoClient


async def inspect_markets() -> None:
    async with InfoClient() as info:
        await info.refresh_metadata()

        assert await info.coin_name("BTC") == "BTC"
        btc_asset = await info.asset_id("BTC")

        spot_name = await info.coin_name("HYPE/USDC")
        spot_symbol = await info.coin_symbol(spot_name)
        spot_asset = await info.asset_id(spot_name)

        print(btc_asset, spot_name, spot_symbol, spot_asset)
```

The same helpers are available as `client.info.*` when using an authenticated
`AsyncHyperliquid` client. Exchange order and cancel methods resolve these IDs
internally; callers pass typed commands with market names, not integer asset
IDs.
