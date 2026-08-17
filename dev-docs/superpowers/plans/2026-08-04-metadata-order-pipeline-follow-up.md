# Metadata and Order Pipeline Follow-up Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Finish the unpublished 1.0 RC1 by splitting metadata construction by domain, making `place_orders` the single order pipeline, enforcing valid grouping, venue, builder-fee, and outcome-price boundaries, resolving canonical spot/outcome coin names before price lookup, and pinning Hyperliquid tick/lot behavior with unit and testnet integration coverage.

**Architecture:** `InfoClient` continues to own metadata and publishes one validated `_MetadataSnapshot`; `_metadata.py` gains small indexing functions for perp, spot token, and spot market data plus a typed `_MarketInfo` result containing the canonical protocol coin. `AsyncHyperliquid.place_orders` becomes the only batch orchestrator: validate input, resolve market information once, reject spot/perp mixtures, enforce the venue-specific builder cap, normalize only outer-market orders using canonical `allMids` keys, encode once, and submit one signed action. Outcome `#<encoding>` markets use the documented spot-like asset formula and fixed price domain without a second metadata framework; minimum notional remains an Exchange rule and is never duplicated locally.

**Tech Stack:** Python 3.12, asyncio, aiohttp, TypedDict/dataclasses, pytest, pytest-asyncio, uv, Ruff, ty, Hyperliquid testnet.

**Implementation status:** Completed on 2026-08-04. The final live gate passed
34 Exchange cases with 26 capability-gated skips and left no open orders or
nonzero perpetual positions on the configured testnet subaccount.
The unchecked boxes below preserve the original executable TDD sequence; they
are plan notation, not outstanding work.

## Protocol References

- [Builder codes](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/builder-codes): fee units, perp/spot maxima, and the spot-buy exception.
- [Asset IDs](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/asset-ids): perp, HIP-3, spot, and outcome action-asset/name encodings.
- [Info endpoint](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint): canonical spot coin names used by Info requests and `allMids`.
- [Spot Info endpoint](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint/spot): `spotMeta`, `spotMetaAndAssetCtxs`, and `outcomeMeta` response families.
- [Tick and lot size](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/tick-and-lot-size): price significant figures and `szDecimals` rules.
- [Outcome order types](https://docs.outcome.xyz/order-types#tick-size-and-minimum-order): outcome price range, tick size, and the Exchange-enforced `10 USDC` minimum order value.
- [Hyperliquid error responses](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/error-responses): `Tick`, `MinTradeNtl`, and `MinTradeSpotNtl` server errors.

## Global Constraints

- Keep Python pinned to 3.12 through the existing uv Python pin; do not add a restrictive package `requires-python` upper bound.
- RC1 is unpublished, so remove the provisional `place_market_orders` API instead of preserving a misleading compatibility wrapper.
- Preserve the expanded `place_order` signature and the exact `batch_place_orders = place_orders` alias.
- Keep `ExchangeClient` independent of `InfoClient`; orchestration that needs both stays in `AsyncHyperliquid`.
- One `place_orders` call must produce at most one Exchange action, one signature, and one HTTP POST.
- Never split a mixed spot/perp call into multiple signed requests.
- Resolve every user-facing spot alias to its protocol coin before `allMids`: `HYPE/USDC` maps to environment-specific `@<spot index>`, while `PURR/USDC` remains `PURR/USDC`.
- Treat outcome `#<encoding>` and token alias `+<encoding>` as spot-like; derive the action asset as `100_000_000 + encoding` and accept only side suffix `0` or `1`.
- Outcome prices are quoted by Outcome in cents. On the Exchange wire, accept `0.00001 <= px <= 0.99999` USDC and normalize to a `0.00001` USDC tick (five decimal places).
- Clamp only SDK-generated outcome IOC limit prices to that range. Explicit user-supplied order `px` values outside the range fail before signing.
- Do not gate minimum order notional (`px * sz`) in the SDK. Submit validly encoded orders and preserve the Exchange `MinTradeNtl`/`MinTradeSpotNtl` error response.
- Builder fee units are tenths of a basis point. Gate perps at `100` (0.1%) and spot/outcome orders at `1000` (1%) after market resolution and before price lookup or signing.
- Do not reject spot buy orders merely because a builder is present; the protocol documents that builder fees do not apply to the buy side, not that the payload is invalid.
- Outer `PlaceOrderRequest.is_market` means client-side IOC price preparation; nested `trigger.isMarket` means execution mode after a trigger fires.
- `normalTpsl` requires a parent and at least one trigger child; do not impose a maximum order count without protocol evidence.
- Exchange integration tests remain testnet-only, explicitly opted in, destructive-marked, and cleanup-safe.
- Do not delete existing integration tests. Replace only assertions or fixtures that encode invalid protocol semantics.
- Do not modify the separate copycat repository. Document any later copycat compatibility work separately.
- Do not add strategy classes, facade layers, generic builders, protocols, or wrapper-in-wrapper call chains.

---

## File Map

| Path | Responsibility after this plan |
| --- | --- |
| `src/async_hyperliquid/constants.py` | Perp, spot, HIP-3, and outcome action-asset/price constants. |
| `src/async_hyperliquid/_metadata.py` | Validate/index metadata and return typed canonical `_MarketInfo` values. |
| `src/async_hyperliquid/info.py` | Load metadata, atomically publish `_build_metadata(...)`, and fetch mids by canonical market coin. |
| `src/async_hyperliquid/_encoding.py` | Independent price, size, and wire-number normalization using explicit venue information. |
| `src/async_hyperliquid/client.py` | Validate, normalize, encode, and submit orders through one `place_orders` pipeline. |
| `tests/unit/test_metadata.py` | Metadata assembly, canonical spot/outcome names, and malformed-source invariants. |
| `tests/unit/test_order_encoding.py` | Official tick/lot matrix, outcome price domain, no-local-notional-gate contract, and exact wire values. |
| `tests/unit/test_place_order.py` | Delegation, grouping, mixed market modes, and spot/perp rejection. |
| `tests/unit/test_close_positions.py` | Closing workflows delegate directly to `place_orders`. |
| `tests/unit/test_exchange_client.py` | Exchange action receives one already-encoded order batch. |
| `tests/public_api/test_surface.py` | RC1 public surface excludes `place_market_orders`. |
| `tests/integration/exchange/test_orders.py` | Testnet price readback, Exchange-owned minimum-notional rejection, valid `normalTpsl`, mixed-venue rejection, and cleanup. |
| `tests/integration/test_info.py` | Testnet HYPE/PURR canonical coin and `allMids` lookup behavior. |
| `README.md` | Explain the canonical order path and market/trigger flags. |
| `docs/migration-0.5-to-1.0.md` | Record RC1 helper removal and replacement calls. |
| `CHANGELOG.md` | Record the corrected order pipeline, rounding, and testnet coverage. |

---

### Task 1: Split Metadata Construction by Input Domain

**Files:**
- Modify: `src/async_hyperliquid/constants.py:1-4`
- Modify: `src/async_hyperliquid/_metadata.py:1-214`
- Modify: `src/async_hyperliquid/info.py:1-10,120-129,558-601,629-659`
- Modify: `src/async_hyperliquid/_encoding.py:38-47`
- Modify: `src/async_hyperliquid/client.py:105-138,265-353,378-405`
- Test: `tests/unit/test_metadata.py`
- Test: `tests/unit/test_exchange_client.py`
- Test: `tests/unit/test_order_encoding.py`
- Test: `tests/oracle/test_signing_payload_parity.py`

**Interfaces:**
- Consumes: `tuple[str, ...]`, `AllPerpMetas`, and `SpotMeta` returned by the three existing Info calls.
- Produces: `_build_metadata(dex_names, all_perp_metas, spot_meta) -> _MetadataSnapshot`.
- Produces: `_market_info(snapshot, coin) -> _MarketInfo`, where the result carries the canonical protocol coin, action asset, lot precision, venue, and dex needed by downstream consumers.

- [ ] **Step 1: Rename the assembly function in the unit test and add a direct assembly assertion**

Add the private import and a focused test without deleting the existing InfoClient metadata tests:

```python
from async_hyperliquid._metadata import _build_metadata, _market_info
from async_hyperliquid.types.info import AllPerpMetas, SpotMeta


def test_build_metadata_assembles_perp_and_spot_indexes() -> None:
    snapshot = _build_metadata(
        ("", "xyz"),
        cast(AllPerpMetas, ALL_PERP_METAS),
        cast(SpotMeta, SPOT_META),
    )

    assert snapshot.asset_by_coin["BTC"] == 0
    assert snapshot.size_decimals_by_asset[0] == 5
    assert snapshot.asset_by_coin["@0"] == 10_000
    assert snapshot.symbol_by_coin["@0"] == "PURR/USDC"
    assert snapshot.spot_market_coins == frozenset({"@0"})
    assert snapshot.perp_context_by_coin["xyz:NVDA"] == ("xyz", 0)

    btc = _market_info(snapshot, "BTC")
    assert (btc.coin, btc.asset, btc.size_decimals, btc.is_spot, btc.dex) == (
        "BTC",
        0,
        5,
        False,
        "",
    )
    purr = _market_info(snapshot, "PURR/USDC")
    assert (purr.coin, purr.asset, purr.is_spot, purr.dex) == (
        "@0",
        10_000,
        True,
        "",
    )
```

- [ ] **Step 2: Run the focused test and verify the rename is not implemented yet**

Run:

```bash
uv run pytest -q tests/unit/test_metadata.py::test_build_metadata_assembles_perp_and_spot_indexes
```

Expected: collection fails because `_build_metadata` is not defined.

- [ ] **Step 3: Introduce one construction-only index and domain functions**

In `constants.py`, add the documented outcome action-asset offset:

```python
OUTCOME_ASSET_OFFSET = 100_000_000
```

In `_metadata.py`, import `field` and add one immutable lookup result plus one mutable construction record next to `_MetadataSnapshot`:

```python
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class _MarketInfo:
    coin: str
    asset: int
    size_decimals: int
    is_spot: bool
    dex: str


@dataclass(slots=True)
class _MetadataIndex:
    coin_by_alias: dict[str, str] = field(default_factory=dict)
    asset_by_coin: dict[str, int] = field(default_factory=dict)
    symbol_by_coin: dict[str, str] = field(default_factory=dict)
    size_decimals_by_asset: dict[int, int] = field(default_factory=dict)
    spot_token_by_coin: dict[str, SpotToken] = field(default_factory=dict)
    perp_context_by_coin: dict[str, tuple[str, int]] = field(default_factory=dict)
    spot_market_coins: set[str] = field(default_factory=set)
```

Extract the current perp loop into:

```python
def _index_perp_metadata(
    index: _MetadataIndex,
    dex_names: tuple[str, ...],
    all_perp_metas: AllPerpMetas,
) -> None:
    offsets = _dex_offsets(dex_names)
    seen_perp_dexes: set[str] = set()

    for meta in all_perp_metas:
        meta_object = cast(JsonObject, meta)
        universe = _require_list(meta_object.get("universe"), "allPerpMetas[].universe")
        if not universe:
            continue
        first_asset = _require_object(universe[0], "allPerpMetas[].universe[]")
        dex = _perp_dex(
            _require_str(first_asset.get("name"), "allPerpMetas[].universe[].name")
        )
        if dex in seen_perp_dexes:
            raise ProtocolError("allPerpMetas contains duplicate dex metadata")
        seen_perp_dexes.add(dex)
        offset = offsets.get(dex)
        if offset is None:
            raise ProtocolError("allPerpMetas contains an unknown dex")

        for asset_index, asset_value in enumerate(universe):
            asset = _require_object(asset_value, "allPerpMetas[].universe[]")
            name = _require_str(asset.get("name"), "allPerpMetas[].universe[].name")
            decimals = _require_int(
                asset.get("szDecimals"), "allPerpMetas[].universe[].szDecimals"
            )
            if _perp_dex(name) != dex:
                raise ProtocolError("allPerpMetas contains mixed dex asset metadata")
            if name in index.asset_by_coin:
                raise ProtocolError("allPerpMetas contains duplicate asset metadata")
            asset_id = offset + asset_index
            index.coin_by_alias[name] = name
            index.asset_by_coin[name] = asset_id
            index.symbol_by_coin[name] = name
            index.size_decimals_by_asset[asset_id] = decimals
            index.perp_context_by_coin[name] = (dex, asset_index)

    if seen_perp_dexes != offsets.keys():
        raise ProtocolError("allPerpMetas is missing dex metadata")
```

Extract spot token parsing into a pure result function:

```python
def _index_spot_tokens(spot_object: JsonObject) -> dict[int, SpotToken]:
    token_objects = _require_list(spot_object.get("tokens"), "spotMeta.tokens")
    tokens_by_index: dict[int, SpotToken] = {}
    for token_value in token_objects:
        token = _require_object(token_value, "spotMeta.tokens[]")
        token_index = _require_non_negative_int(
            token.get("index"), "spotMeta.tokens[].index"
        )
        _require_str(token.get("name"), "spotMeta.tokens[].name")
        _require_bool(token.get("isCanonical"), "spotMeta.tokens[].isCanonical")
        _require_non_negative_int(
            token.get("szDecimals"), "spotMeta.tokens[].szDecimals"
        )
        _require_non_negative_int(
            token.get("weiDecimals"), "spotMeta.tokens[].weiDecimals"
        )
        _require_str(token.get("tokenId"), "spotMeta.tokens[].tokenId")
        for field_name in ("evmContract", "fullName"):
            if field_name not in token:
                raise ProtocolError(
                    f"metadata field spotMeta.tokens[].{field_name} is required"
                )
        _require_optional_evm_contract(
            token["evmContract"], "spotMeta.tokens[].evmContract"
        )
        _require_optional_str(token["fullName"], "spotMeta.tokens[].fullName")
        if token_index in tokens_by_index:
            raise ProtocolError("spotMeta contains duplicate token indexes")
        tokens_by_index[token_index] = cast(SpotToken, token)
    return tokens_by_index
```

Extract spot market validation and indexing into:

```python
def _index_spot_metadata(
    index: _MetadataIndex,
    spot_object: JsonObject,
    tokens_by_index: dict[int, SpotToken],
) -> None:
    pair_objects = _require_list(spot_object.get("universe"), "spotMeta.universe")
    spot_pair_indexes: set[int] = set()
    for pair_value in pair_objects:
        pair = _require_object(pair_value, "spotMeta.universe[]")
        coin = _require_str(pair.get("name"), "spotMeta.universe[].name")
        pair_index = _require_int(pair.get("index"), "spotMeta.universe[].index")
        token_indexes = _require_list(pair.get("tokens"), "spotMeta.universe[].tokens")
        if len(token_indexes) != 2:
            raise ProtocolError("spotMeta pair must contain two token indexes")
        base_index = _require_int(
            token_indexes[0], "spotMeta.universe[].tokens[0]"
        )
        quote_index = _require_int(
            token_indexes[1], "spotMeta.universe[].tokens[1]"
        )
        base = tokens_by_index.get(base_index)
        quote = tokens_by_index.get(quote_index)
        if base is None or quote is None:
            raise ProtocolError("spotMeta pair references an unknown token")
        if coin in index.asset_by_coin or pair_index in spot_pair_indexes:
            raise ProtocolError("spotMeta contains duplicate pair metadata")
        spot_pair_indexes.add(pair_index)

        base_name = base["name"]
        quote_name = quote["name"]
        display_name = f"{base_name}/{quote_name}"
        asset_id = SPOT_ASSET_OFFSET + pair_index

        index.coin_by_alias[coin] = coin
        index.coin_by_alias.setdefault(display_name, coin)
        index.coin_by_alias.setdefault(quote_name, quote_name)
        index.asset_by_coin[coin] = asset_id
        index.symbol_by_coin[coin] = display_name
        index.size_decimals_by_asset[asset_id] = base["szDecimals"]
        index.spot_token_by_coin[coin] = base
        index.spot_token_by_coin.setdefault(quote_name, quote)
        index.spot_market_coins.add(coin)
```

- [ ] **Step 4: Replace the god function with the small assembly owner**

Use the exact new entry point:

```python
def _build_metadata(
    dex_names: tuple[str, ...],
    all_perp_metas: AllPerpMetas,
    spot_meta: SpotMeta,
) -> _MetadataSnapshot:
    index = _MetadataIndex()
    _index_perp_metadata(index, dex_names, all_perp_metas)
    spot_object = cast(JsonObject, spot_meta)
    tokens_by_index = _index_spot_tokens(spot_object)
    _index_spot_metadata(index, spot_object, tokens_by_index)
    return _MetadataSnapshot(
        coin_by_alias=index.coin_by_alias,
        asset_by_coin=index.asset_by_coin,
        symbol_by_coin=index.symbol_by_coin,
        size_decimals_by_asset=index.size_decimals_by_asset,
        spot_token_by_coin=index.spot_token_by_coin,
        perp_context_by_coin=index.perp_context_by_coin,
        spot_market_coins=frozenset(index.spot_market_coins),
        perp_dex_names=dex_names,
    )
```

- [ ] **Step 5: Resolve aliases and outcomes to one canonical market value**

Keep ordinary perp/spot lookup table-driven. Add only the deterministic outcome formula documented by Hyperliquid; do not fetch or cache the large `outcomeMeta` response and do not add human-readable outcome aliases:

```python
def _outcome_market_info(coin: str) -> _MarketInfo | None:
    if not coin.startswith(("#", "+")):
        return None
    raw_encoding = coin[1:]
    if not raw_encoding.isdecimal():
        raise ValueError(f"invalid outcome market: {coin}")
    encoding = int(raw_encoding)
    if encoding % 10 not in (0, 1):
        raise ValueError(f"invalid outcome side: {coin}")
    return _MarketInfo(
        coin=f"#{encoding}",
        asset=OUTCOME_ASSET_OFFSET + encoding,
        size_decimals=0,
        is_spot=True,
        dex="",
    )


def _market_info(snapshot: _MetadataSnapshot, coin: str) -> _MarketInfo:
    outcome = _outcome_market_info(coin)
    if outcome is not None:
        return outcome

    name = snapshot.coin_by_alias.get(coin)
    asset = None if name is None else snapshot.asset_by_coin.get(name)
    decimals = None if asset is None else snapshot.size_decimals_by_asset.get(asset)
    if name is None or asset is None or decimals is None:
        raise ValueError(f"unknown market: {coin}")
    perp = snapshot.perp_context_by_coin.get(name)
    return _MarketInfo(
        coin=name,
        asset=asset,
        size_decimals=decimals,
        is_spot=name in snapshot.spot_market_coins,
        dex="" if perp is None else perp[0],
    )
```

`size_decimals=0` is an explicit outcome lot-size contract to pin with the outcome unit/live contract tests below; the asset-ID documentation defines naming and asset encoding but not this precision. If testnet disproves the zero-decimal contract, stop outcome order placement with a clear unsupported-precision error instead of inventing precision from current book contents.

Add focused cases:

```python
def test_spot_alias_resolves_to_protocol_coin() -> None:
    hype_meta = deepcopy(SPOT_META)
    hype_tokens = cast(list[JsonValue], hype_meta["tokens"])
    hype_base = cast(JsonObject, hype_tokens[1])
    hype_pairs = cast(list[JsonValue], hype_meta["universe"])
    hype_pair = cast(JsonObject, hype_pairs[0])
    hype_base["name"] = "HYPE"
    hype_base["szDecimals"] = 2
    hype_pair["name"] = "@107"
    hype_pair["index"] = 107
    hype_snapshot = _build_metadata(
        ("", "xyz"),
        cast(AllPerpMetas, ALL_PERP_METAS),
        cast(SpotMeta, hype_meta),
    )
    purr_meta = deepcopy(SPOT_META)
    purr_pairs = cast(list[JsonValue], purr_meta["universe"])
    cast(JsonObject, purr_pairs[0])["name"] = "PURR/USDC"
    purr_snapshot = _build_metadata(
        ("", "xyz"),
        cast(AllPerpMetas, ALL_PERP_METAS),
        cast(SpotMeta, purr_meta),
    )

    hype = _market_info(hype_snapshot, "HYPE/USDC")
    assert (hype.coin, hype.asset, hype.is_spot) == ("@107", 10_107, True)
    purr = _market_info(purr_snapshot, "PURR/USDC")
    assert purr.coin == "PURR/USDC"


@pytest.mark.parametrize("coin", ["#10", "+10"])
def test_outcome_market_uses_documented_encoding(coin: str) -> None:
    snapshot = _build_metadata(
        ("", "xyz"),
        cast(AllPerpMetas, ALL_PERP_METAS),
        cast(SpotMeta, SPOT_META),
    )
    market = _market_info(snapshot, coin)

    assert market == _MarketInfo(
        coin="#10",
        asset=100_000_010,
        size_decimals=0,
        is_spot=True,
        dex="",
    )


@pytest.mark.parametrize("coin", ["#", "+abc", "#12"])
def test_outcome_market_rejects_invalid_encoding(coin: str) -> None:
    snapshot = _build_metadata(
        ("", "xyz"),
        cast(AllPerpMetas, ALL_PERP_METAS),
        cast(SpotMeta, SPOT_META),
    )
    with pytest.raises(ValueError, match="outcome"):
        _market_info(snapshot, coin)
```

The fixtures must contain real-shaped `spotMeta` entries: HYPE's `name` is `@107`, while PURR's `name` is the exceptional `PURR/USDC`. Do not special-case HYPE or PURR in runtime code; `spotMeta.universe[].name` is the authority.

- [ ] **Step 6: Make `InfoClient` consume canonical market values without repeating metadata lookup**

Update `info.py`:

```python
from ._metadata import _MarketInfo, _MetadataSnapshot, _build_metadata, _market_info
```

Return `_build_metadata(...)` from `_load_metadata`, change `_market_info` and `_market_infos` to return `_MarketInfo`, and change the private mids helper to consume already-resolved values:

```python
async def _market_info(self, coin: str) -> _MarketInfo:
    return _market_info(await self._ensure_metadata(), coin)


async def _market_infos(self, coins: Sequence[str]) -> tuple[_MarketInfo, ...]:
    snapshot = await self._ensure_metadata()
    return tuple(_market_info(snapshot, coin) for coin in coins)


async def _mid_prices(self, markets: Sequence[_MarketInfo]) -> tuple[float, ...]:
    commands = tuple(markets)
    if not commands:
        return ()
    dexs = tuple(dict.fromkeys(market.dex for market in commands))
    tasks = {dex: asyncio.create_task(self.all_mids(dex)) for dex in dexs}
    await _wait_for_tasks(tuple(tasks.values()))
    mids_by_dex = {dex: task.result() for dex, task in tasks.items()}

    prices: list[float] = []
    for market in commands:
        price = mids_by_dex[market.dex].get(market.coin)
        if not isinstance(price, str):
            raise ProtocolError("allMids is missing a string price")
        try:
            prices.append(float(price))
        except ValueError:
            raise ProtocolError("allMids contains an invalid price") from None
    return tuple(prices)


async def mid_price(self, coin: str) -> float:
    market = await self._market_info(coin)
    return (await self._mid_prices((market,)))[0]
```

Update `asset_id` and `size_decimals` to project `.asset` and `.size_decimals` from `_market_info`, so outcomes and ordinary markets follow the same resolver. Existing token-only methods remain table-driven and must not accept outcome aliases.

Because this changes the private return type, migrate all consumers in the same commit; do not leave a tuple adapter behind. First make venue explicit at the encoder boundary while preserving the current rounding implementation until Task 2:

```python
def encode_order(
    order: PlaceOrderRequest | ModifyOrderRequest,
    *,
    asset: int,
    size_decimals: int,
    is_spot: bool,
) -> EncodedOrder:
    price_decimals = (8 if is_spot else 6) - size_decimals
```

Then mechanically consume `_MarketInfo` in every call path:

```python
async def _encode_orders(
    self, orders: Sequence[PlaceOrderRequest]
) -> tuple[EncodedOrder, ...]:
    markets = await self._info._market_infos(
        tuple(order["coin"] for order in orders)
    )
    return tuple(
        encode_order(
            order,
            asset=market.asset,
            size_decimals=market.size_decimals,
            is_spot=market.is_spot,
        )
        for order, market in zip(orders, markets, strict=True)
    )
```

- `_encode_market_orders` resolves `markets` once, passes them to `_mid_prices`, builds IOC limits, and encodes those limits against the same `markets`; it must not call `_encode_orders` and trigger a second lookup.
- `cancel_orders` and `cancel_orders_by_cloid` use `market.asset`.
- `_encode_modify(order, market)` uses all three encoding fields; singular and plural modify paths pass `_MarketInfo` directly.
- `place_twap` uses `market.asset` and `market.size_decimals`.
- Direct `encode_order` unit/oracle calls pass the expected `is_spot` literal.
- `FakeInfo`/oracle fakes return `_MarketInfo` instances, including their canonical coin and dex.

These are private RC1 contracts, so do not add tuple compatibility, overloads, default `is_spot`, or a second resolver method.

In `MetadataTransport`, move the existing `allMids` response into a mutable `self.all_mids` dictionary and return a copy from `post_json`. Then pin that a public alias is not used as the response key:

```python
async def test_mid_price_uses_canonical_spot_coin() -> None:
    transport = MetadataTransport()
    base = cast(JsonObject, cast(list[JsonValue], transport.spot_meta["tokens"])[1])
    pair = cast(JsonObject, cast(list[JsonValue], transport.spot_meta["universe"])[0])
    base["name"] = "HYPE"
    base["szDecimals"] = 2
    pair["name"] = "@107"
    pair["index"] = 107
    transport.all_mids = {"BTC": "100", "@107": "42.5"}
    info = build_info(transport)

    assert await info.mid_price("HYPE/USDC") == 42.5
    assert transport.all_mids_dexes == [""]


async def test_mid_price_preserves_purr_protocol_coin() -> None:
    transport = MetadataTransport()
    pair = cast(JsonObject, cast(list[JsonValue], transport.spot_meta["universe"])[0])
    pair["name"] = "PURR/USDC"
    transport.all_mids = {"BTC": "100", "PURR/USDC": "0.123"}
    info = build_info(transport)

    assert await info.mid_price("PURR/USDC") == 0.123


async def test_mid_prices_groups_only_by_resolved_dex() -> None:
    transport = MetadataTransport()
    info = build_info(transport)
    btc = await info._market_info("BTC")
    purr = await info._market_info("PURR/USDC")

    assert await info._mid_prices((btc, purr)) == (100.0, 2.1)
    assert transport.all_mids_dexes == [""]
```

The critical contract is one metadata load, one `allMids` call per distinct dex, and lookup by `market.coin`.

- [ ] **Step 7: Run metadata and canonical-mids tests and static checks**

Run:

```bash
uv run pytest -q \
  tests/unit/test_metadata.py \
  tests/unit/test_exchange_client.py \
  tests/unit/test_order_encoding.py \
  tests/oracle/test_signing_payload_parity.py
uv run ruff check src/async_hyperliquid/_metadata.py src/async_hyperliquid/info.py src/async_hyperliquid/_encoding.py src/async_hyperliquid/client.py tests/unit/test_metadata.py tests/unit/test_exchange_client.py tests/unit/test_order_encoding.py
uv run ty check src/async_hyperliquid/_metadata.py src/async_hyperliquid/info.py src/async_hyperliquid/_encoding.py src/async_hyperliquid/client.py tests/unit/test_metadata.py tests/unit/test_exchange_client.py tests/unit/test_order_encoding.py tests/oracle/test_signing_payload_parity.py
```

Expected: all commands pass; existing malformed metadata cases retain their current exception messages, aliases are resolved exactly once, and `allMids` is indexed only with `_MarketInfo.coin`.

- [ ] **Step 8: Commit the independently reviewable metadata refactor**

```bash
git add src/async_hyperliquid/constants.py src/async_hyperliquid/_metadata.py src/async_hyperliquid/info.py src/async_hyperliquid/_encoding.py src/async_hyperliquid/client.py tests/unit/test_metadata.py tests/unit/test_exchange_client.py tests/unit/test_order_encoding.py tests/oracle/test_signing_payload_parity.py
git commit -m "refactor: split and type market metadata"
```

---

### Task 2: Implement the Official Tick and Lot Rules

**Files:**
- Modify: `src/async_hyperliquid/constants.py:1-7`
- Modify: `src/async_hyperliquid/_encoding.py:1-65`
- Modify: `src/async_hyperliquid/client.py:1-15,116-138,390-400`
- Test: `tests/unit/test_order_encoding.py`
- Test: `tests/unit/test_place_order.py`
- Test: `tests/oracle/test_signing_payload_parity.py`

**Interfaces:**
- Produces: `_round_price(value: float, max_decimals: int) -> float | int`.
- Produces: `_round_size(value: float, size_decimals: int) -> float | int`.
- Produces: `_market_limit_price(mid, *, is_buy, slippage, is_outcome) -> float`.
- Changes: `encode_order(..., asset, size_decimals, is_spot, is_outcome)` makes the outcome price domain explicit without adding a market-kind class.

- [ ] **Step 1: Add the official price matrix as failing unit tests**

Import `_round_price` and add:

```python
from async_hyperliquid._encoding import _round_price, _round_size


@pytest.mark.parametrize(
    ("value", "max_decimals", "expected"),
    [
        (10_001.0, 1, 10_001),
        (0.002001, 6, 0.002001),
        (123_456.0, 1, 123_456),
        (123_456.6, 1, 123_460),
        (1_234.56, 6, 1_234.6),
        (0.0012345, 6, 0.001234),
        (0.012345, 5, 0.01235),
        (0.0001234, 8, 0.0001234),
        (0.0001234, 5, 0.00012),
    ],
)
def test_round_price_obeys_tick_size(
    value: float, max_decimals: int, expected: float | int
) -> None:
    assert _round_price(value, max_decimals) == expected
```

- [ ] **Step 2: Add the size matrix that exposes the `.8g` truncation**

```python
@pytest.mark.parametrize(
    ("value", "size_decimals", "expected"),
    [
        (1.001, 3, 1.001),
        (1.0001, 3, 1.0),
        (1.23456, 3, 1.235),
        (100_000_001.0, 0, 100_000_001),
    ],
)
def test_round_size_obeys_lot_size(
    value: float, size_decimals: int, expected: float | int
) -> None:
    assert _round_size(value, size_decimals) == expected
```

- [ ] **Step 3: Add outcome price-domain and no-local-notional-gate tests**

Add explicit outcome encoding cases. Exchange prices are denominated in USDC, so Outcome's `0.001` cent tick is `0.00001` USDC:

```python
def _outcome_order(px: float, sz: float = 1.0) -> PlaceOrderRequest:
    return {
        "coin": "#10",
        "is_buy": True,
        "sz": sz,
        "px": px,
        "is_market": False,
        "order_type": limit_order_type(TimeInForce.GTC),
    }


@pytest.mark.parametrize(
    ("px", "expected"),
    [
        (0.00001, "0.00001"),
        (0.4, "0.4"),
        (0.400014, "0.40001"),
        (0.99999, "0.99999"),
    ],
)
def test_encode_outcome_uses_fixed_price_tick(px: float, expected: str) -> None:
    encoded = encode_order(
        _outcome_order(px),
        asset=100_000_010,
        size_decimals=0,
        is_spot=True,
        is_outcome=True,
    )

    assert encoded["p"] == expected


@pytest.mark.parametrize("px", [0.000009, 1.0])
def test_encode_outcome_rejects_price_outside_binary_domain(px: float) -> None:
    with pytest.raises(ValueError, match="outcome price"):
        encode_order(
            _outcome_order(px),
            asset=100_000_010,
            size_decimals=0,
            is_spot=True,
            is_outcome=True,
        )


def test_encode_outcome_does_not_gate_minimum_notional() -> None:
    encoded = encode_order(
        _outcome_order(0.4, sz=1.0),
        asset=100_000_010,
        size_decimals=0,
        is_spot=True,
        is_outcome=True,
    )

    assert float(encoded["p"]) * float(encoded["s"]) == 0.4
```

The last case is intentionally below `10 USDC`. It must encode successfully; do not assert or calculate a local notional minimum anywhere in production code.

Add SDK-generated market-limit boundary cases to `tests/unit/test_place_order.py`:

```python
@pytest.mark.parametrize(
    ("mid", "is_buy", "expected"),
    [
        (0.99999, True, 0.99999),
        (0.00001, False, 0.00001),
        (0.4, True, 0.42),
        (0.4, False, 0.38),
    ],
)
def test_outcome_market_limit_price_stays_in_domain(
    mid: float, is_buy: bool, expected: float
) -> None:
    assert _market_limit_price(
        mid,
        is_buy=is_buy,
        slippage=0.05,
        is_outcome=True,
    ) == pytest.approx(expected)
```

- [ ] **Step 4: Run the new matrix and observe the failures**

Run:

```bash
uv run pytest -q tests/unit/test_order_encoding.py tests/unit/test_place_order.py \
  -k "round_price or round_size or outcome"
```

Expected before the fix:

- `100_000_001` is incorrectly reduced to `100_000_000`.
- `123_456.6` is incorrectly truncated to `123_456`.
- Outcome price `1.0` is not rejected.
- SDK-generated outcome IOC prices are not clamped to the binary price domain.

- [ ] **Step 5: Replace the conflated rounding helper and encode the outcome price domain**

Add protocol constants to `constants.py`:

```python
OUTCOME_MIN_PRICE = 0.00001
OUTCOME_MAX_PRICE = 0.99999
OUTCOME_PRICE_DECIMALS = 5
```

Import all three constants in `_encoding.py`; import `OUTCOME_MIN_PRICE` and `OUTCOME_MAX_PRICE` in `client.py`:

```python
from .constants import (
    OUTCOME_MAX_PRICE,
    OUTCOME_MIN_PRICE,
    OUTCOME_PRICE_DECIMALS,
)
```

```python
from .constants import OUTCOME_MAX_PRICE, OUTCOME_MIN_PRICE
```

Use this implementation in `_encoding.py`:

```python
def _round_size(value: float, size_decimals: int) -> float | int:
    rounded = round(float(value), size_decimals)
    return int(rounded) if rounded.is_integer() else rounded


def _round_price(value: float, max_decimals: int) -> float | int:
    number = float(value)
    if number.is_integer():
        return int(number)
    rounded = round(float(f"{number:.5g}"), max_decimals)
    return int(rounded) if rounded.is_integer() else rounded
```

Use explicit booleans when calculating price precision. Validate the caller-supplied outcome price before normalization, but do not inspect `price * size`:

```python
def encode_order(
    order: PlaceOrderRequest | ModifyOrderRequest,
    *,
    asset: int,
    size_decimals: int,
    is_spot: bool,
    is_outcome: bool,
) -> EncodedOrder:
    max_decimals = (8 if is_spot else 6) - size_decimals
    raw_price = float(order["px"])
    if is_outcome and not OUTCOME_MIN_PRICE <= raw_price <= OUTCOME_MAX_PRICE:
        raise ValueError(
            "outcome price must be between 0.00001 and 0.99999 USDC"
        )
    price = _round_price(
        raw_price, OUTCOME_PRICE_DECIMALS if is_outcome else max_decimals
    )
    size = _round_size(order["sz"], size_decimals)
```

Add the pure IOC-price helper in `client.py`:

```python
def _market_limit_price(
    mid: float,
    *,
    is_buy: bool,
    slippage: float,
    is_outcome: bool,
) -> float:
    price = mid * (1 + slippage if is_buy else 1 - slippage)
    if not is_outcome:
        return price
    return min(max(price, OUTCOME_MIN_PRICE), OUTCOME_MAX_PRICE)
```

In the existing `_encode_market_orders` loop, pair each order with its resolved `_MarketInfo` and call `_market_limit_price(..., is_outcome=market.coin.startswith("#"))`. The prefix is safe here because `market.coin` is already the canonical protocol representation, not user input.

Update all `encode_order` call sites and direct tests to pass `is_outcome=market.coin.startswith("#")` or the exact test literal. Do not add a default: every caller must make the protocol distinction explicit.

Update `client.py` close-size handling to import and call `_round_size` instead of `_round_float`.

- [ ] **Step 6: Run encoding, market-price, closing, and official-oracle tests**

```bash
uv run pytest -q tests/unit/test_order_encoding.py tests/unit/test_place_order.py tests/unit/test_close_positions.py tests/oracle/test_signing_payload_parity.py
uv run ruff check src/async_hyperliquid/constants.py src/async_hyperliquid/_encoding.py src/async_hyperliquid/client.py tests/unit/test_order_encoding.py tests/unit/test_place_order.py
uv run ty check src/async_hyperliquid/constants.py src/async_hyperliquid/_encoding.py src/async_hyperliquid/client.py tests/unit/test_order_encoding.py tests/unit/test_place_order.py
```

Expected: all pass; exact signed payload parity remains unchanged for existing valid vectors, outcome prices use the fixed five-decimal USDC tick, and a sub-`10 USDC` outcome order still reaches the encoded-order boundary.

- [ ] **Step 7: Commit the rounding and outcome-price correction**

```bash
git add src/async_hyperliquid/constants.py src/async_hyperliquid/_encoding.py src/async_hyperliquid/client.py tests/unit/test_order_encoding.py tests/unit/test_place_order.py tests/unit/test_close_positions.py tests/oracle/test_signing_payload_parity.py
git commit -m "fix: implement market price and lot normalization"
```

---

### Task 3: Make `place_orders` the Single Order Pipeline

**Files:**
- Modify: `src/async_hyperliquid/client.py:105-263,553-572`
- Modify: `tests/unit/test_place_order.py`
- Modify: `tests/unit/test_close_positions.py`
- Modify: `tests/unit/test_exchange_client.py`
- Modify: `tests/public_api/test_surface.py`
- Modify: `README.md:120-185`
- Modify: `docs/migration-0.5-to-1.0.md:180-215`
- Modify: `CHANGELOG.md:1-25`

**Interfaces:**
- Preserves: expanded `place_order(...) -> PlaceOrderResponse`.
- Preserves: `place_orders(orders, *, grouping, builder, expires_after)`.
- Preserves: `batch_place_orders = place_orders`.
- Adds: `grouping` keyword to `place_trigger_order`.
- Removes: provisional RC1 method `place_market_orders`.

- [ ] **Step 1: Rewrite delegation tests around one owner**

Import `InfoClient`, then add these typed request fixtures to `tests/unit/test_place_order.py`:

```python
from async_hyperliquid import AsyncHyperliquid, InfoClient
from async_hyperliquid._metadata import _MarketInfo


def _limit_request(coin: str = "BTC") -> PlaceOrderRequest:
    return {
        "coin": coin,
        "is_buy": True,
        "sz": 0.01,
        "px": 100_000.0,
        "is_market": False,
        "order_type": limit_order_type(TimeInForce.GTC),
    }


def _spot_limit_request() -> PlaceOrderRequest:
    return {
        "coin": "@0",
        "is_buy": True,
        "sz": 1.0,
        "px": 1.0,
        "is_market": False,
        "order_type": limit_order_type(TimeInForce.GTC),
    }


def _market_request() -> PlaceOrderRequest:
    return {
        "coin": "BTC",
        "is_buy": True,
        "sz": 0.01,
        "px": 0.0,
        "is_market": True,
    }


def _trigger_request() -> PlaceOrderRequest:
    return {
        "coin": "BTC",
        "is_buy": False,
        "sz": 0.01,
        "px": 90_000.0,
        "is_market": False,
        "ro": True,
        "order_type": trigger_order_type(
            is_market=True,
            trigger_px="90000",
            tpsl=TriggerKind.STOP_LOSS,
        ),
    }
```

Replace mocks of `place_market_orders` with one `place_orders` mock and assert all singular helpers use it:

```python
async def test_singular_order_methods_delegate_to_place_orders(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    place_orders = AsyncMock(return_value=RESPONSE)
    monkeypatch.setattr(AsyncHyperliquid, "place_orders", place_orders)
    client = AsyncHyperliquid(ADDRESS, KEY)
    limit = _limit_request()
    market = _market_request()
    trigger = _trigger_request()

    await client.place_limit_order(limit)
    await client.place_market_order(market)
    await client.place_trigger_order(
        trigger, grouping=OrderGrouping.POSITION_TPSL
    )

    assert [call.args[0] for call in place_orders.await_args_list] == [
        (limit,),
        (market,),
        (trigger,),
    ]
    assert place_orders.await_args_list[-1].kwargs["grouping"] is (
        OrderGrouping.POSITION_TPSL
    )
```

Update the expanded `place_order` dispatch test with both outer modes:

```python
@pytest.mark.parametrize("is_market", [False, True])
async def test_place_order_always_dispatches_to_place_orders(
    monkeypatch: pytest.MonkeyPatch, is_market: bool
) -> None:
    place_orders = AsyncMock(return_value=RESPONSE)
    monkeypatch.setattr(AsyncHyperliquid, "place_orders", place_orders)
    client = AsyncHyperliquid(ADDRESS, KEY)

    result = await client.place_order(
        "BTC", True, 0.01, 100_000.0, is_market=is_market
    )

    assert result is RESPONSE
    place_orders.assert_awaited_once()
    request = place_orders.await_args.args[0][0]
    assert request["is_market"] is is_market
```

- [ ] **Step 2: Add validation tests that must fail before Info or Exchange calls**

Add tests for the outer/nested market conflict and `normalTpsl` structure:

```python
async def test_outer_market_mode_cannot_replace_a_trigger(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    market_infos = AsyncMock()
    submit = AsyncMock()
    monkeypatch.setattr(InfoClient, "_market_infos", market_infos)
    monkeypatch.setattr(ExchangeClient, "_submit_orders", submit)
    client = AsyncHyperliquid(ADDRESS, KEY)
    order = _trigger_request()
    order["is_market"] = True

    with pytest.raises(ValueError, match="trigger.isMarket"):
        await client.place_orders((order,))

    market_infos.assert_not_awaited()
    submit.assert_not_awaited()


async def test_normal_tpsl_requires_parent_and_trigger_child(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    market_infos = AsyncMock()
    monkeypatch.setattr(InfoClient, "_market_infos", market_infos)
    client = AsyncHyperliquid(ADDRESS, KEY)

    with pytest.raises(ValueError, match="parent and at least one trigger child"):
        await client.place_orders(
            (_limit_request(),), grouping=OrderGrouping.NORMAL_TPSL
        )

    market_infos.assert_not_awaited()
```

Add the remaining pure-structure cases:

```python
async def test_normal_tpsl_rejects_trigger_as_parent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    market_infos = AsyncMock()
    monkeypatch.setattr(InfoClient, "_market_infos", market_infos)
    client = AsyncHyperliquid(ADDRESS, KEY)

    with pytest.raises(ValueError, match="first order must be a non-trigger parent"):
        await client.place_orders(
            (_trigger_request(), _trigger_request()),
            grouping=OrderGrouping.NORMAL_TPSL,
        )

    market_infos.assert_not_awaited()


async def test_normal_tpsl_rejects_non_trigger_child(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    market_infos = AsyncMock()
    monkeypatch.setattr(InfoClient, "_market_infos", market_infos)
    client = AsyncHyperliquid(ADDRESS, KEY)

    with pytest.raises(ValueError, match="child orders must be trigger orders"):
        await client.place_orders(
            (_limit_request(), _limit_request()),
            grouping=OrderGrouping.NORMAL_TPSL,
        )

    market_infos.assert_not_awaited()
```

Do not add a test asserting a maximum of three orders.

- [ ] **Step 3: Add the mixed market-parent/trigger-child batch test**

Use a market parent and trigger child in one `normalTpsl` call:

```python
async def test_place_orders_normalizes_only_the_market_subset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parent = _market_request()
    child = _trigger_request()
    btc = _MarketInfo("BTC", 0, 5, False, "")
    market_infos = AsyncMock(return_value=(btc, btc))
    mid_prices = AsyncMock(return_value=(100_000.0,))
    submit = AsyncMock(return_value=RESPONSE)
    monkeypatch.setattr(InfoClient, "_market_infos", market_infos)
    monkeypatch.setattr(InfoClient, "_mid_prices", mid_prices)
    monkeypatch.setattr(ExchangeClient, "_submit_orders", submit)
    client = AsyncHyperliquid(ADDRESS, KEY)

    await client.place_orders(
        (parent, child), grouping=OrderGrouping.NORMAL_TPSL
    )

    market_infos.assert_awaited_once_with(("BTC", "BTC"))
    mid_prices.assert_awaited_once_with((btc,))
    submit.assert_awaited_once()
    encoded = submit.await_args.args[0]
    assert encoded[0]["t"] == {"limit": {"tif": "Ioc"}}
    assert encoded[1]["t"] == child["order_type"]
```

- [ ] **Step 4: Add the spot/perp fast-fail unit test**

```python
async def test_place_orders_rejects_spot_and_perp_in_one_batch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    market_infos = AsyncMock(
        return_value=(
            _MarketInfo("BTC", 0, 5, False, ""),
            _MarketInfo("PURR/USDC", 10_000, 0, True, ""),
        )
    )
    mid_prices = AsyncMock()
    submit = AsyncMock()
    monkeypatch.setattr(InfoClient, "_market_infos", market_infos)
    monkeypatch.setattr(InfoClient, "_mid_prices", mid_prices)
    monkeypatch.setattr(ExchangeClient, "_submit_orders", submit)
    client = AsyncHyperliquid(ADDRESS, KEY)

    with pytest.raises(
        ValueError, match="orders cannot mix spot and perpetual markets"
    ):
        await client.place_orders((_limit_request(), _spot_limit_request()))

    mid_prices.assert_not_awaited()
    submit.assert_not_awaited()
```

- [ ] **Step 5: Pin builder hard-gate boundaries and call order**

Add unit cases for every boundary. Use the existing valid address fixture; only the fee and resolved venue matter:

```python
@pytest.mark.parametrize(
    ("market", "fee"),
    [
        (_MarketInfo("BTC", 0, 5, False, ""), 100),
        (_MarketInfo("ETH", 1, 4, False, ""), 100),
        (_MarketInfo("@107", 10_107, 2, True, ""), 1000),
        (_MarketInfo("#10", 100_000_010, 0, True, ""), 1000),
    ],
)
async def test_place_orders_accepts_builder_fee_at_venue_limit(
    monkeypatch: pytest.MonkeyPatch, market: _MarketInfo, fee: int
) -> None:
    market_infos = AsyncMock(return_value=(market,))
    submit = AsyncMock(return_value=RESPONSE)
    monkeypatch.setattr(InfoClient, "_market_infos", market_infos)
    monkeypatch.setattr(ExchangeClient, "_submit_orders", submit)
    client = AsyncHyperliquid(ADDRESS, KEY)

    await client.place_orders(
        (_limit_request(market.coin),),
        builder=Builder(address=BUILDER_ADDRESS, fee_tenths_bps=fee),
    )

    submit.assert_awaited_once()


@pytest.mark.parametrize(
    ("market", "fee", "maximum"),
    [
        (_MarketInfo("BTC", 0, 5, False, ""), 101, 100),
        (_MarketInfo("@107", 10_107, 2, True, ""), 1001, 1000),
        (_MarketInfo("#10", 100_000_010, 0, True, ""), 1001, 1000),
    ],
)
async def test_place_orders_rejects_builder_fee_above_venue_limit(
    monkeypatch: pytest.MonkeyPatch,
    market: _MarketInfo,
    fee: int,
    maximum: int,
) -> None:
    market_infos = AsyncMock(return_value=(market,))
    mid_prices = AsyncMock()
    submit = AsyncMock()
    monkeypatch.setattr(InfoClient, "_market_infos", market_infos)
    monkeypatch.setattr(InfoClient, "_mid_prices", mid_prices)
    monkeypatch.setattr(ExchangeClient, "_submit_orders", submit)
    client = AsyncHyperliquid(ADDRESS, KEY)
    order = _market_request()
    order["coin"] = market.coin

    with pytest.raises(
        ValueError, match=rf"fee_tenths_bps must be <= {maximum}"
    ):
        await client.place_orders(
            (order,),
            builder=Builder(address=BUILDER_ADDRESS, fee_tenths_bps=fee),
        )

    market_infos.assert_awaited_once()
    mid_prices.assert_not_awaited()
    submit.assert_not_awaited()
```

Add one explicit spot-buy case at or below the cap and assert it is submitted:

```python
async def test_place_orders_does_not_reject_spot_buy_with_builder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    market = _MarketInfo("@107", 10_107, 2, True, "")
    market_infos = AsyncMock(return_value=(market,))
    submit = AsyncMock(return_value=RESPONSE)
    monkeypatch.setattr(InfoClient, "_market_infos", market_infos)
    monkeypatch.setattr(ExchangeClient, "_submit_orders", submit)
    client = AsyncHyperliquid(ADDRESS, KEY)
    order = _spot_limit_request()
    order["coin"] = "HYPE/USDC"

    await client.place_orders(
        (order,),
        builder=Builder(address=BUILDER_ADDRESS, fee_tenths_bps=1000),
    )

    submit.assert_awaited_once()
```

This pins the protocol rule that the fee is non-applicable to the buying side rather than locally illegal. Keep the dataclass-level non-negative test in `tests/unit/types/test_commands.py`; `Builder` itself cannot know the order venue.

- [ ] **Step 6: Implement small pure validation, builder, and conversion functions**

Add module-level helpers in `client.py`:

```python
def _is_trigger_order(order: PlaceOrderRequest) -> bool:
    order_type = order.get("order_type")
    return order_type is not None and "trigger" in order_type


def _validate_orders(
    orders: tuple[PlaceOrderRequest, ...], grouping: OrderGrouping
) -> None:
    for order in orders:
        if order["is_market"] and _is_trigger_order(order):
            raise ValueError(
                "outer is_market cannot be used with a trigger order; "
                "use trigger.isMarket"
            )
        if order["is_market"]:
            slippage = order.get("slippage", 0.05)
            if not math.isfinite(slippage) or not 0 <= slippage < 1:
                raise ValueError("slippage must be finite and in [0, 1)")

    if grouping is not OrderGrouping.NORMAL_TPSL:
        return
    if len(orders) < 2:
        raise ValueError("normalTpsl requires a parent and at least one trigger child")
    if _is_trigger_order(orders[0]):
        raise ValueError("normalTpsl first order must be a non-trigger parent")
    if any(not _is_trigger_order(order) for order in orders[1:]):
        raise ValueError("normalTpsl child orders must be trigger orders")


_MAX_PERP_BUILDER_FEE_TENTHS_BPS = 100
_MAX_SPOT_BUILDER_FEE_TENTHS_BPS = 1000


def _validate_builder(builder: Builder | None, *, is_spot: bool) -> None:
    if builder is None:
        return
    maximum = (
        _MAX_SPOT_BUILDER_FEE_TENTHS_BPS
        if is_spot
        else _MAX_PERP_BUILDER_FEE_TENTHS_BPS
    )
    if builder.fee_tenths_bps > maximum:
        venue = "spot" if is_spot else "perpetual"
        raise ValueError(
            f"builder fee_tenths_bps must be <= {maximum} for {venue} orders"
        )


def _market_limit_order(
    order: PlaceOrderRequest, mid: float, *, is_outcome: bool
) -> PlaceOrderRequest:
    slippage = order.get("slippage", 0.05)
    limit: PlaceOrderRequest = {
        "coin": order["coin"],
        "is_buy": order["is_buy"],
        "sz": order["sz"],
        "px": _market_limit_price(
            mid,
            is_buy=order["is_buy"],
            slippage=slippage,
            is_outcome=is_outcome,
        ),
        "is_market": False,
        "ro": order.get("ro", False),
        "order_type": limit_order_type(TimeInForce.IOC),
    }
    cloid = order.get("cloid")
    if cloid is not None:
        limit["cloid"] = cloid
    return limit
```

Keep these as functions; do not introduce a normalizer class. The fee caps stay private to the order orchestrator because only it owns both the resolved venue and the builder argument.

- [ ] **Step 7: Replace the split pipelines with one `place_orders` body**

Make `_encode_orders` synchronous and pass already-resolved market information:

```python
def _encode_orders(
    orders: Sequence[PlaceOrderRequest],
    market_infos: Sequence[_MarketInfo],
) -> tuple[EncodedOrder, ...]:
    return tuple(
        encode_order(
            order,
            asset=market.asset,
            size_decimals=market.size_decimals,
            is_spot=market.is_spot,
            is_outcome=market.coin.startswith("#"),
        )
        for order, market in zip(orders, market_infos, strict=True)
    )
```

Use this canonical method body:

```python
async def place_orders(
    self,
    orders: Sequence[PlaceOrderRequest],
    *,
    grouping: OrderGrouping = OrderGrouping.NA,
    builder: Builder | None = None,
    expires_after: int | None = None,
) -> PlaceOrderResponse:
    commands = tuple(orders)
    if not commands:
        raise ValueError("orders must not be empty")
    _validate_orders(commands, grouping)

    market_infos = await self._info._market_infos(
        tuple(order["coin"] for order in commands)
    )
    venues = {market.is_spot for market in market_infos}
    if len(venues) != 1:
        raise ValueError("orders cannot mix spot and perpetual markets")
    _validate_builder(builder, is_spot=market_infos[0].is_spot)

    market_indexes = tuple(
        index for index, order in enumerate(commands) if order["is_market"]
    )
    normalized = list(commands)
    if market_indexes:
        mids = await self._info._mid_prices(
            tuple(market_infos[index] for index in market_indexes)
        )
        for index, mid in zip(market_indexes, mids, strict=True):
            normalized[index] = _market_limit_order(
                commands[index],
                mid,
                is_outcome=market_infos[index].coin.startswith("#"),
            )

    encoded = _encode_orders(normalized, market_infos)
    return await self._exchange._submit_orders(
        encoded,
        grouping=grouping,
        builder=builder,
        expires_after=expires_after,
    )
```

This order is intentional: pure request validation first, then one metadata resolution, then mixed-venue rejection, then the venue-specific builder gate, then `allMids`, rounding, encoding, signing, and POST. Therefore HYPE/USDC reaches `allMids` as `@107`/`@1035`, PURR remains `PURR/USDC`, and an invalid builder fee cannot trigger price I/O or signing.

Then:

- make `place_order` always call `place_orders((order,), ...)`;
- make `place_market_order` validate `is_market=True` and call `place_orders`;
- add `grouping` to `place_trigger_order` and forward it;
- keep `batch_place_orders = place_orders`;
- make close workflows call `place_orders` directly;
- delete `_encode_market_orders` and `place_market_orders`.

- [ ] **Step 8: Update the RC1 public surface and migration text**

Remove `place_market_orders` from `tests/public_api/test_surface.py`. Document these replacements:

```python
await client.place_market_order(order)
await client.place_orders(market_orders)
```

State explicitly that `place_orders` accepts mixed outer market and non-market modes within one venue, but rejects spot/perp mixtures. Document the builder limits in tenths of a basis point and that spot buys are not rejected when a builder is present. Document the outcome wire-price range/tick and explicitly state that minimum order notional is validated by the Exchange, not the SDK. Add the provisional helper removal to `CHANGELOG.md`.

- [ ] **Step 9: Run the complete order unit surface**

```bash
uv run pytest -q \
  tests/unit/test_place_order.py \
  tests/unit/test_close_positions.py \
  tests/unit/test_exchange_client.py \
  tests/public_api/test_surface.py \
  tests/oracle/test_signing_payload_parity.py
uv run ruff check src/async_hyperliquid/client.py tests/unit/test_place_order.py tests/unit/test_close_positions.py
uv run ty check src/async_hyperliquid/client.py tests/unit/test_place_order.py tests/unit/test_close_positions.py
```

Expected: all pass; every placement path reaches exactly one `_submit_orders` call.

- [ ] **Step 10: Commit the canonical order pipeline**

```bash
git add \
  src/async_hyperliquid/client.py \
  tests/unit/test_place_order.py \
  tests/unit/test_close_positions.py \
  tests/unit/test_exchange_client.py \
  tests/public_api/test_surface.py \
  README.md \
  docs/migration-0.5-to-1.0.md \
  CHANGELOG.md
git commit -m "refactor: canonicalize order placement through place_orders"
```

---

### Task 4: Pin Canonical Mids and Price Readback on Testnet

**Files:**
- Modify: `tests/integration/test_info.py`
- Modify: `tests/integration/exchange/test_orders.py`

**Interfaces:**
- Consumes: testnet `spotMeta`, `allMids`, and the canonical `InfoClient.mid_price` path.
- Consumes: `AsyncHyperliquid.exchange.execution_address`, `InfoClient.order_status`, and the existing cancel helpers.
- Produces: non-destructive HYPE/PURR/outcome identity checks, one cleanup-safe proof that minimum notional is Exchange-owned, and two cleanup-safe regressions proving server-visible order prices.

- [ ] **Step 1: Pin HYPE, PURR, and outcome names against live testnet `allMids`**

Add these non-destructive cases to `tests/integration/test_info.py`:

```python
async def test_spot_mid_price_uses_testnet_protocol_coin(info: InfoClient) -> None:
    mids = await info.all_mids()

    assert "@1035" in mids
    assert await info.mid_price("HYPE/USDC") == float(mids["@1035"])
    assert await info.asset_id("HYPE/USDC") == 11_035


async def test_purr_mid_price_preserves_named_pair(info: InfoClient) -> None:
    mids = await info.all_mids()

    assert "PURR/USDC" in mids
    assert await info.mid_price("PURR/USDC") == float(mids["PURR/USDC"])


async def test_outcome_market_uses_spot_like_encoding(info: InfoClient) -> None:
    mids = await info.all_mids()
    coin = next((name for name in mids if name.startswith("#")), None)
    if coin is None:
        raise pytest.skip.Exception("testnet allMids has no outcome market")
    encoding = int(coin[1:])

    assert encoding % 10 in (0, 1)
    assert await info.asset_id(coin) == 100_000_000 + encoding
    assert await info.asset_id(f"+{encoding}") == 100_000_000 + encoding
    assert await info.size_decimals(coin) == 0
    assert await info.mid_price(coin) == float(mids[coin])
```

These tests deliberately pin `@1035` only in the testnet integration suite. Runtime code remains environment-neutral and trusts the current `spotMeta.universe[].name`; the same alias resolves to `@107` on mainnet metadata.

- [ ] **Step 2: Prove sub-minimum outcome notional reaches the Exchange**

Add a test that deliberately sends a valid price/size encoding whose notional is below `10 USDC` and asserts the server's order-level error:

```python
async def test_outcome_minimum_notional_is_exchange_owned(
    api_hl: AsyncHyperliquid,
) -> None:
    mids = await api_hl.info.all_mids()
    coin = next((name for name in mids if name.startswith("#")), None)
    if coin is None:
        raise pytest.skip.Exception("testnet allMids has no outcome market")
    mid = float(mids[coin])
    is_buy = mid > OUTCOME_MIN_PRICE
    px = OUTCOME_MIN_PRICE if is_buy else OUTCOME_MAX_PRICE
    oid: int | None = None
    try:
        response = await api_hl.place_limit_order(
            {
                "coin": coin,
                "is_buy": is_buy,
                "sz": 1.0,
                "px": px,
                "is_market": False,
                "order_type": limit_order_type(TimeInForce.ALO),
            }
        )
        assert response["status"] == "ok"
        status = cast(JsonObject, response["response"]["data"]["statuses"][0])
        resting = status.get("resting")
        if isinstance(resting, dict):
            resting_oid = resting.get("oid")
            if isinstance(resting_oid, int):
                oid = resting_oid
        error = status.get("error")
        assert isinstance(error, str)
        assert "minimum value" in error.lower()
    finally:
        if oid is not None:
            await _cancel(api_hl, (CancelOrder(coin, oid),))
```

Import `OUTCOME_MIN_PRICE` and `OUTCOME_MAX_PRICE` from `async_hyperliquid.constants`. The cleanup branch is a safety net if the Exchange contract changes; the test must fail rather than silently turning a server rule into an SDK rule.

- [ ] **Step 3: Add a helper that places, reads, compares, and cancels a resting order**

Import `Decimal` and add:

```python
from decimal import Decimal


async def _assert_resting_price(
    client: AsyncHyperliquid, coin: str, expected_px: Decimal
) -> None:
    mid = await client.info.mid_price(coin)
    px = float(expected_px)
    is_buy = px < mid
    size_decimals = await client.info.size_decimals(coin)
    size = round(20 / px, size_decimals)
    oid: int | None = None
    try:
        response = await client.place_limit_order(
            {
                "coin": coin,
                "is_buy": is_buy,
                "sz": size,
                "px": px,
                "is_market": False,
                "order_type": limit_order_type(TimeInForce.ALO),
            }
        )
        oid = _resting_oid(response)
        result = await client.info.order_status(
            client.exchange.execution_address, oid
        )
        assert result["status"] == "order"
        assert Decimal(result["order"]["order"]["limitPx"]) == expected_px
    finally:
        if oid is not None:
            await _cancel(client, (CancelOrder(coin, oid),))
```

Decimal comparison intentionally accepts server strings such as `"10001"` and `"10001.0"` while rejecting a changed numeric price.

- [ ] **Step 4: Add the exact BTC and kPEPE cases**

```python
async def test_btc_integer_price_above_10000_is_preserved(
    api_hl: AsyncHyperliquid,
) -> None:
    await _assert_resting_price(api_hl, "BTC", Decimal("10001"))


async def test_kpepe_six_decimal_price_is_preserved(
    api_hl: AsyncHyperliquid,
) -> None:
    await _assert_resting_price(api_hl, "kPEPE", Decimal("0.002001"))
```

- [ ] **Step 5: Run canonical Info cases, then the focused destructive testnet cases**

Run the read-only Info cases first:

```bash
uv run pytest -q tests/integration/test_info.py \
  -k "spot_mid_price_uses_testnet_protocol_coin or purr_mid_price or outcome_market"
```

Then run the Exchange cases:

```bash
RUN_LIVE_EXCHANGE_TESTS=true \
RUN_DESTRUCTIVE_EXCHANGE_TESTS=true \
uv run pytest -q tests/integration/exchange/test_orders.py \
  -k "outcome_minimum_notional_is_exchange_owned or btc_integer_price_above_10000 or kpepe_six_decimal_price"
```

Expected:

- `IS_MAINNET=true` aborts in fixture setup.
- The sub-`10 USDC` outcome order is encoded, signed, posted, and returned as an Exchange `minimum value` error; no SDK exception occurs.
- On testnet, both orders rest, `order_status` returns the exact numeric price, and cleanup cancels both OIDs.

- [ ] **Step 6: Commit the canonical-name and exact-price integration regressions**

```bash
git add tests/integration/test_info.py tests/integration/exchange/test_orders.py
git commit -m "test: pin testnet market identity and price precision"
```

---

### Task 5: Validate Real `normalTpsl` and Mixed-Venue Rejection

**Files:**
- Modify: `tests/integration/exchange/test_orders.py`

**Interfaces:**
- Consumes: canonical `place_orders`, action-level `OrderGrouping`, nested `trigger.isMarket`, and live metadata.
- Produces: a semantically valid two-order `normalTpsl` test and a live-metadata spot/perp fast-fail test.

- [ ] **Step 1: Replace the invalid singleton `normalTpsl` integration case**

Construct one resting parent plus one trigger child for BTC:

```python
async def test_normal_tpsl_accepts_parent_and_trigger_child(
    api_hl: AsyncHyperliquid,
) -> None:
    mid = await api_hl.info.mid_price("BTC")
    size_decimals = await api_hl.info.size_decimals("BTC")
    parent_px = mid * 0.5
    stop_px = round(parent_px * 0.8, 6 - size_decimals)
    size = round(20 / parent_px, size_decimals)
    parent: PlaceOrderRequest = {
        "coin": "BTC",
        "is_buy": True,
        "sz": size,
        "px": parent_px,
        "is_market": False,
        "order_type": limit_order_type(TimeInForce.GTC),
    }
    stop: PlaceOrderRequest = {
        "coin": "BTC",
        "is_buy": False,
        "sz": size,
        "px": stop_px,
        "is_market": False,
        "ro": True,
        "order_type": trigger_order_type(
            is_market=True,
            trigger_px=str(stop_px),
            tpsl=TriggerKind.STOP_LOSS,
        ),
    }
    cancels: list[CancelOrder] = []
    try:
        response = await api_hl.place_orders(
            (parent, stop), grouping=OrderGrouping.NORMAL_TPSL
        )
        assert response["status"] == "ok"
        statuses = response["response"]["data"]["statuses"]
        assert len(statuses) == 2
        for status in statuses:
            status_object = cast(JsonObject, status)
            assert "error" not in status_object
            resting = status_object.get("resting")
            if resting is not None:
                resting_object = cast(JsonObject, resting)
                oid = resting_object["oid"]
                assert isinstance(oid, int)
                cancels.append(CancelOrder("BTC", oid))
    finally:
        await _cancel(api_hl, cancels)
```

Keep the test at two orders. Do not add a local maximum based only on this success.

- [ ] **Step 2: Add the live-metadata mixed spot/perp fast-fail case**

```python
async def test_place_orders_rejects_live_spot_and_perp_batch(
    api_hl: AsyncHyperliquid,
) -> None:
    spot_meta = await api_hl.info.spot_meta()
    assert spot_meta["universe"]
    spot_coin = spot_meta["universe"][0]["name"]
    perp = await _limit_request(api_hl, "BTC")
    spot = await _limit_request(api_hl, spot_coin)

    with pytest.raises(
        ValueError, match="orders cannot mix spot and perpetual markets"
    ):
        await api_hl.place_orders((perp, spot))
```

This integration case resolves real testnet asset IDs but must fail before signing or submitting an Exchange action.

- [ ] **Step 3: Run the two focused testnet cases**

```bash
RUN_LIVE_EXCHANGE_TESTS=true \
RUN_DESTRUCTIVE_EXCHANGE_TESTS=true \
uv run pytest -q tests/integration/exchange/test_orders.py \
  -k "normal_tpsl_accepts_parent or rejects_live_spot_and_perp"
```

Expected: `normalTpsl` returns two non-error statuses; mixed venue raises locally.

- [ ] **Step 4: Probe the standard three-order form without changing validation**

Add a separate parent + TP + SL case after the two-order case passes:

```python
async def test_normal_tpsl_accepts_parent_take_profit_and_stop_loss(
    api_hl: AsyncHyperliquid,
) -> None:
    mid = await api_hl.info.mid_price("BTC")
    size_decimals = await api_hl.info.size_decimals("BTC")
    price_decimals = 6 - size_decimals
    parent_px = round(mid * 0.5, price_decimals)
    take_px = round(parent_px * 1.2, price_decimals)
    stop_px = round(parent_px * 0.8, price_decimals)
    size = round(20 / parent_px, size_decimals)
    parent: PlaceOrderRequest = {
        "coin": "BTC",
        "is_buy": True,
        "sz": size,
        "px": parent_px,
        "is_market": False,
        "order_type": limit_order_type(TimeInForce.GTC),
    }
    take_profit: PlaceOrderRequest = {
        "coin": "BTC",
        "is_buy": False,
        "sz": size,
        "px": take_px,
        "is_market": False,
        "ro": True,
        "order_type": trigger_order_type(
            is_market=True,
            trigger_px=str(take_px),
            tpsl=TriggerKind.TAKE_PROFIT,
        ),
    }
    stop_loss: PlaceOrderRequest = {
        "coin": "BTC",
        "is_buy": False,
        "sz": size,
        "px": stop_px,
        "is_market": False,
        "ro": True,
        "order_type": trigger_order_type(
            is_market=True,
            trigger_px=str(stop_px),
            tpsl=TriggerKind.STOP_LOSS,
        ),
    }
    cancels: list[CancelOrder] = []
    try:
        response = await api_hl.place_orders(
            (parent, take_profit, stop_loss),
            grouping=OrderGrouping.NORMAL_TPSL,
        )
        assert response["status"] == "ok"
        statuses = response["response"]["data"]["statuses"]
        assert len(statuses) == 3
        for status in statuses:
            status_object = cast(JsonObject, status)
            assert "error" not in status_object
            resting = status_object.get("resting")
            if resting is not None:
                resting_object = cast(JsonObject, resting)
                oid = resting_object["oid"]
                assert isinstance(oid, int)
                cancels.append(CancelOrder("BTC", oid))
    finally:
        await _cancel(api_hl, cancels)
```

Do not infer `max=3` from this successful request. A maximum requires explicit protocol documentation or a consistent four-order rejection.

- [ ] **Step 5: Commit the grouping and venue integration contract**

```bash
git add tests/integration/exchange/test_orders.py
git commit -m "test: validate grouped orders and venue boundaries"
```

---

### Task 6: Run the Final RC1 Quality Gate

**Files:**
- Verify: all changed source, tests, and documentation
- Update only if results changed: `README.md`, `CHANGELOG.md`, `docs/migration-0.5-to-1.0.md`

**Interfaces:**
- Consumes: all outputs from Tasks 1-5.
- Produces: a clean, packageable RC1 follow-up commit with explicit live-test evidence.

- [ ] **Step 1: Format and lint the complete repository scope**

```bash
uv run ruff format --check src tests scripts benchmarks
uv run ruff check src tests scripts benchmarks
```

Expected: both commands pass without modifying files.

- [ ] **Step 2: Run static typing by source group**

```bash
uv run ty check src
uv run ty check tests
uv run ty check scripts
uv run ty check benchmarks
```

Expected: all four commands pass.

- [ ] **Step 3: Run non-Exchange tests and contract/oracle coverage**

```bash
uv run pytest -q -m "not exchange"
uv run pytest -q tests/contracts tests/oracle tests/public_api tests/package
```

Expected: all pass; no Exchange integration test is collected by the first command.

- [ ] **Step 4: Verify dependency lock, diff hygiene, package build, and hot path**

```bash
uv lock --check
git diff --check
uv build
uv run python scripts/client_hotpath_benchmark.py \
  --baseline-wheel /path/to/base/dist/async_hyperliquid-1.0.0rc1-py3-none-any.whl \
  --candidate-wheel dist/async_hyperliquid-1.0.0rc1-py3-none-any.whl \
  --baseline-api v1
```

Expected: lock and diff checks pass, sdist/wheel build, and the benchmark completes without a new per-order metadata or HTTP loop.

- [ ] **Step 5: Run the complete Exchange suite only with explicit testnet opt-in**

```bash
RUN_LIVE_EXCHANGE_TESTS=true \
RUN_DESTRUCTIVE_EXCHANGE_TESTS=true \
uv run pytest -q tests/integration/exchange
```

Expected: fixture setup rejects mainnet; testnet suite passes and leaves no test-created resting orders or positions.

- [ ] **Step 6: Review the final diff for the explicit smell gates**

Confirm all statements are true:

- `_build_metadata` only orchestrates domain helpers and snapshot assembly.
- There is no `_build_size_decimals` extra pass.
- There is no `place_market_orders` method or forwarding alias.
- `batch_place_orders` is an exact alias.
- Mixed outer market modes work within one venue.
- Trigger orders retain nested `isMarket` and are never converted to IOC limits.
- Mixed spot/perp orders fail before price lookup, signing, and submission.
- Builder caps are selected from `_MarketInfo.is_spot` only after market resolution; no asset-ID threshold or user coin string decides the cap.
- Perp builder fee `100` and spot/outcome fee `1000` are accepted; `101` and `1001` respectively fail before `allMids`, signing, or submission.
- Spot buys carrying a valid builder are not locally rejected.
- Market-price lookup consumes `_MarketInfo.coin`, so HYPE aliases never reach `allMids`, while `PURR/USDC` remains unchanged.
- Outcome markets are spot-like and use explicit formula handling; no eager `outcomeMeta` cache or second metadata framework is introduced.
- `encode_order` receives `is_spot` and `is_outcome` explicitly and contains no numeric asset-range venue inference.
- Explicit outcome `px` values outside `0.00001..0.99999` USDC fail before signing; valid values normalize to the `0.00001` USDC tick.
- SDK-generated outcome IOC limits clamp to the valid price endpoints instead of failing near zero or one.
- Production code contains no `px * sz`, `10 USDC`, `MinTradeNtl`, or `MinTradeSpotNtl` precheck; those errors remain Exchange-owned.
- No `asyncio.gather` splits an order batch.
- No maximum `normalTpsl` count is encoded.
- No new wrapper class, strategy, facade, or generic abstraction exists.

- [ ] **Step 7: Commit any final documentation-only corrections**

If Step 6 requires wording corrections, commit only those files:

```bash
git add README.md CHANGELOG.md docs/migration-0.5-to-1.0.md
git commit -m "docs: finalize rc1 order semantics"
```

If no documentation changed after Task 3, skip this commit and retain a clean worktree.

---

## Acceptance Criteria

- `_build_metadata_snapshot` no longer exists; `_build_metadata` has one orchestration responsibility.
- Perp, spot token, and spot market indexing have separate private functions with unchanged validation semantics.
- `place_orders` is the only plural placement implementation and submits exactly one action.
- `place_market_orders` is absent from source, tests, public-surface expectations, and documentation.
- `place_order`, `place_limit_order`, `place_market_order`, `place_trigger_order`, close workflows, and `batch_place_orders` converge on `place_orders`.
- A market parent and trigger child can be submitted together in one `normalTpsl` batch.
- Outer market mode combined with trigger `order_type` fails before any Info/Exchange I/O.
- `normalTpsl` rejects singleton, trigger-first, and non-trigger-child structures without imposing a maximum count.
- Spot/perp mixtures fail locally and are never auto-split.
- `_MarketInfo` is the single internal fact passed from metadata resolution to venue validation, builder validation, mid lookup, and order encoding.
- HYPE/USDC resolves from live metadata to `@107` on mainnet or `@1035` on testnet before `allMids`; PURR/USDC resolves to `PURR/USDC`.
- Outcome `#<encoding>` and `+<encoding>` aliases resolve to canonical `#<encoding>`, asset `100_000_000 + encoding`, and the spot venue; invalid side suffixes fail locally.
- Outcome wire prices are bounded to `0.00001..0.99999` USDC and normalized to five decimal places; generated IOC limits clamp at the endpoints.
- A validly encoded outcome order below `10 USDC` reaches the testnet Exchange and returns its `minimum value` order error; the SDK performs no local notional gate.
- Builder fees are hard-gated at `100` for perps and `1000` for spot/outcome after market resolution and before price lookup or signing.
- A valid builder on a spot buy is accepted even though the exchange does not apply the fee to that side.
- BTC `10001` and kPEPE `0.002001` survive testnet placement and `order_status` readback exactly.
- Price normalization follows five significant figures, venue decimal caps, integer-price exemption, and the fixed outcome tick/domain.
- Size normalization uses only `szDecimals` and preserves large integers.
- Ruff, ty, non-Exchange tests, contract/oracle tests, package build, and the client hot-path benchmark pass.
- Testnet Exchange tests pass only under explicit destructive opt-in; mainnet fast-fails.
