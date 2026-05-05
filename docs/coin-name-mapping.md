# Coin 到 Coin Name 映射规则

本文档基于 `AsyncHyperliquidCore` 中 `init_metas()` / `_refresh_metas()` 构造 `coin_names`、`coin_assets`、`coin_symbols` 的代码逻辑，说明调用方传入的 `coin` 如何解析为 Hyperliquid 使用的 `coin name`。

## 术语

- `coin`：调用方传入的名称，例如 `BTC`、`HYPE/USDC`、`@107`、`xyz:NVDA`。
- `coin name`：客户端内部和 Hyperliquid 部分接口使用的规范市场名，即 `get_coin_name(coin)` 的结果。
- `asset id`：下单、撤单等 exchange action 中使用的整数资产编号，即 `get_coin_asset(coin)` 的结果。
- `symbol`：面向用户展示的反向名称，即 `get_coin_symbol(coin)` 的结果。

## 元数据来源

`_refresh_metas()` 会并发读取三类元数据：

- `perpDexs`：返回所有 perp DEX 的顺序，用来确定 HIP-3 DEX 的 asset id offset。
- `allPerpMetas`：返回 base perp 和 HIP-3 DEX perp 的 `universe`。
- `spotMeta`：返回 spot token 表和 spot pair `universe`。

缓存重建顺序是：

1. 初始化 base perp meta，offset 为 `0`。
2. 初始化 spot meta，offset 固定为 `SPOT_OFFSET = 10_000`。
3. 初始化 `self.perp_dexs` 中配置的 HIP-3 DEX perp meta，offset 从 `PERP_DEX_OFFSET = 110_000` 开始。

## Asset Id 空间

| 市场类型 | asset id 规则 | 例子 |
| --- | --- | --- |
| Base perp | `asset = perp universe index` | `BTC` 如果是 base perp 第 0 个市场，则 asset id 为 `0` |
| Spot | `asset = 10_000 + spotMeta.universe[].index` | `@107` 的 spot index 是 `107`，asset id 为 `10_107` |
| HIP-3 perp | `asset = 110_000 + (dex_position - 1) * 10_000 + perp universe index` | `xyz:NVDA` 在第一个 HIP-3 DEX 且 universe index 为 `2` 时，asset id 为 `110_002` |

`dex_position` 来自 `perpDexs` 的顺序，base perp 必须在第 0 位。若 `perpDexs` 缺少 base、出现重复 DEX 名称，或缺少已配置的 DEX，metadata refresh 会拒绝更新缓存，避免 asset id offset 错位。

## Perp 映射

Perp 的映射最直接。对每个 `perp_meta["universe"]` 条目：

```python
asset_name = info["name"]
coin_assets[asset_name] = offset + universe_index
coin_names[asset_name] = asset_name
```

因此 perp 的 `coin` 通常就是 `coin name`：

| 输入 coin | 市场类型 | coin name | asset id 规则 |
| --- | --- | --- | --- |
| `BTC` | base perp | `BTC` | base universe index，例如 `0` |
| `HYPE` | base perp | `HYPE` | base universe index |
| `xyz:NVDA` | HIP-3 perp | `xyz:NVDA` | `xyz` DEX offset + universe index |
| `flx:TSLA` | HIP-3 perp | `flx:TSLA` | `flx` DEX offset + universe index |

带 `:` 的名称会被视为 HIP-3 / builder-deployed perp 名称，DEX 名来自冒号前缀，例如 `xyz:NVDA` 的 DEX 是 `xyz`。

## Spot 映射

Spot 的核心区别是：`spotMeta.universe[].name` 才是规范 `coin name`。这个名称可能是 `@index`，也可能已经是 `BASE/QUOTE` 形式。

对每个 `spot_meta["universe"]` 条目，客户端会先注册规范名：

```python
asset_name = info["name"]
asset = SPOT_OFFSET + info["index"]
coin_assets[asset_name] = asset
coin_names[asset_name] = asset_name
```

如果 `info["tokens"]` 中的 base / quote token index 有效，客户端还会基于 token 表注册 `BASE/QUOTE` 别名：

```python
name = f"{base_token_name}/{quote_token_name}"
coin_names.setdefault(name, asset_name)
coin_names.setdefault(quote_token_name, quote_token_name)
```

所以 spot 有两类常见输入：

| 输入 coin | 市场类型 | coin name | 说明 |
| --- | --- | --- | --- |
| `@107` | spot | `@107` | 直接使用 spot universe 的规范名 |
| `HYPE/USDC` | spot | `@107` | `BASE/QUOTE` 别名映射到规范名 `@107` |
| `@142` | spot | `@142` | 直接使用 spot universe 的规范名 |
| `UBTC/USDC` | spot | `@142` | `BASE/QUOTE` 别名映射到规范名 `@142` |
| `PURR/USDC` | spot | `PURR/USDC` | 如果 spot universe 本身使用 `PURR/USDC` 作为 name，则规范名和输入相同 |

注意：`coin_names.setdefault(...)` 不会覆盖已存在的 key。也就是说，如果某个 spot universe 的规范名本身已经是 `PURR/USDC`，则 `PURR/USDC -> PURR/USDC` 会保留下来，不会被后续别名逻辑改写。

## 反向 Symbol 映射

`coin_symbols` 由 `coin_names` 反向生成：

```python
coin_symbols = {coin_name: coin for coin, coin_name in coin_names.items() if not coin.startswith("@")}
```

这会跳过 `@107 -> @107` 这类内部规范名 key，优先留下更友好的非 `@` 输入名：

| 输入 coin | coin name | symbol |
| --- | --- | --- |
| `@107` | `@107` | `HYPE/USDC` |
| `HYPE/USDC` | `@107` | `HYPE/USDC` |
| `@142` | `@142` | `UBTC/USDC` |
| `BTC` | `BTC` | `BTC` |

## 查询路径

`get_coin_name(coin)` 的查找顺序是：

1. 如果 `coin` 已在 `coin_names` 中，直接返回 `coin_names[coin]`。
2. 如果 `coin` 已在 `coin_assets` 中，说明它本身就是规范名，直接返回 `coin`。
3. 如果缓存未初始化或已初始化但 miss，则刷新 metas 后重试。
4. 仍然找不到则抛出 `ValueError("Coin {coin} not found")`。

`get_coin_asset(coin)` 会先用同一套缓存规则把 `coin` 解析成 `coin name`，再从 `coin_assets[coin_name]` 读取 asset id。

## 内部解析逻辑标注

### 1. 构建缓存

入口是 `AsyncHyperliquidCore._refresh_metas()`：

```text
_refresh_metas()
  -> get_all_dex_name()
  -> info.get_all_perp_metas()
  -> info.get_spot_meta()
  -> _map_all_perp_metas_by_dex()
  -> _get_perp_meta_offsets_by_dex()
  -> _init_perp_meta(base perp, offset=0)
  -> _init_spot_meta(spot, offset=SPOT_OFFSET)
  -> _init_perp_meta(configured HIP-3 perp dexs, offset=PERP_DEX_OFFSET + ...)
  -> _build_coin_symbols()
```

对应缓存写入如下：

| 函数 | 输入元数据 | 写入内容 |
| --- | --- | --- |
| `_init_perp_meta()` | `perp_meta["universe"]` | `coin_assets[name] = offset + index`，`coin_names[name] = name` |
| `_init_spot_meta()` | `spot_meta["universe"]` | `coin_assets[asset_name] = 10_000 + spot_index`，`coin_names[asset_name] = asset_name` |
| `_init_spot_meta()` | `spot_meta["tokens"]` + pair tokens | `coin_names["BASE/QUOTE"] = asset_name`，例如 `coin_names["HYPE/USDC"] = "@107"` |
| `_build_coin_symbols()` | `coin_names` | 反向生成 `coin_symbols[coin_name] = display_symbol`，并跳过 `@...` key |

### 2. 解析 Coin Name

`get_coin_name(coin)` 实际调用 `_lookup_cached_coin_name(coin)`：

```text
_lookup_cached_coin_name(coin)
  -> if coin in coin_names:
       return coin_names[coin]
  -> elif coin in coin_assets:
       return coin
  -> else:
       return None
```

如果第一次查不到，`get_coin_name()` 会触发 metadata refresh：

```text
get_coin_name(coin)
  -> _lookup_cached_coin_name(coin)
  -> if miss and metas already initialized:
       init_metas()
  -> if miss and metas not initialized:
       _ensure_metas_initialized()
  -> _lookup_cached_coin_name(coin)
  -> if still miss:
       raise ValueError
```

### 3. 解析 Asset Id

`get_coin_asset(coin)` 使用 `_lookup_cached_asset(coin)` 走 fast path：

```text
_lookup_cached_asset_id(coin)
  -> if coin in coin_assets:
       return coin_assets[coin]
  -> coin_name = coin_names.get(coin)
  -> if coin_name is not None:
       return coin_assets.get(coin_name)
```

然后 `_lookup_cached_asset(coin)` 会把 `coin_name` 和 `asset id` 组合返回：

```text
_lookup_cached_asset(coin)
  -> asset = _lookup_cached_asset_id(coin)
  -> coin_name = _lookup_cached_coin_name(coin)
  -> return (coin_name, asset)
```

如果 fast path miss，`get_coin_asset()` 会先 `await get_coin_name(coin)`，再读取 `coin_assets[coin_name]`。

### 4. 下单和撤单如何使用解析结果

下单入口最终会走 `_round_sz_px()` / `_round_sz_px_cached()`：

```text
place_order()
  -> place_market_order() or place_typed_order()
  -> _round_sz_px(coin, sz, px)
  -> asset = resolved asset id
  -> encode_order({"asset": asset, ...})
  -> exchange.post_action(...)
```

批量下单会先对每个 `coin` 尝试 `_round_sz_px_cached()`，如果缓存命中，就不再调用 async refresh 路径。

撤单入口 `cancel_orders()` / `batch_cancel_by_cloid()` 也会先尝试 `_lookup_cached_asset_id(coin)`，只有部分 coin miss 时才并发调用 `get_coin_asset(coin)`。

### 5. 查价如何使用解析结果

`get_mark_price(coin)` 有一个特殊分支：

```text
if ":" in coin:
  treat as HIP-3 perp name
  -> _get_cached_perp_ctx_index(coin)
  -> info.get_perp_meta_ctx(dex)
else:
  coin_name = await get_coin_name(coin)
  asset = _lookup_cached_asset_id(coin_name)
  -> if 10_000 <= asset < 110_000:
       info.get_spot_meta_ctx()
     else:
       info.get_perp_meta_ctx(dex)
```

也就是说：

- `xyz:NVDA` 这类带 `:` 的输入会直接按 perp DEX 路径处理。
- `HYPE/USDC` 会先解析为 `@107`，再根据 `asset id = 10_107` 判断为 spot。
- `BTC` 会解析为 `BTC`，再根据 `asset id < 10_000` 判断为 base perp。

## 逐步 Trace

### `BTC` -> `BTC`

```text
_init_perp_meta(base)
  -> universe[0]["name"] = "BTC"
  -> coin_assets["BTC"] = 0
  -> coin_names["BTC"] = "BTC"

get_coin_name("BTC")
  -> coin_names["BTC"]
  -> "BTC"

get_coin_asset("BTC")
  -> coin_assets["BTC"]
  -> 0
```

### `HYPE/USDC` -> `@107`

```text
_init_spot_meta(spot)
  -> pair.name = "@107"
  -> pair.index = 107
  -> pair.tokens = (HYPE token index, USDC token index)
  -> coin_assets["@107"] = 10_000 + 107
  -> coin_names["@107"] = "@107"
  -> coin_names["HYPE/USDC"] = "@107"

get_coin_name("HYPE/USDC")
  -> coin_names["HYPE/USDC"]
  -> "@107"

get_coin_asset("HYPE/USDC")
  -> coin_names["HYPE/USDC"] = "@107"
  -> coin_assets["@107"]
  -> 10_107
```

### `@107` -> `@107`

```text
get_coin_name("@107")
  -> coin_names["@107"]
  -> "@107"

get_coin_symbol("@107")
  -> coin_name = "@107"
  -> coin_symbols["@107"]
  -> "HYPE/USDC"
```

### `xyz:NVDA` -> `xyz:NVDA`

```text
_init_perp_meta(xyz, offset=110_000)
  -> universe[2]["name"] = "xyz:NVDA"
  -> coin_assets["xyz:NVDA"] = 110_000 + 2
  -> coin_names["xyz:NVDA"] = "xyz:NVDA"

get_coin_name("xyz:NVDA")
  -> coin_names["xyz:NVDA"]
  -> "xyz:NVDA"

get_coin_asset("xyz:NVDA")
  -> coin_assets["xyz:NVDA"]
  -> 110_002
```

## 使用建议

- Perp 下单或查价传 `BTC`、`HYPE`、`xyz:NVDA` 这类 perp name 即可。
- Spot 下单或查价建议传 `BASE/QUOTE`，例如 `HYPE/USDC`；客户端会解析到实际 `coin name`，例如 `@107`。
- 如果已经知道 spot 规范名，也可以直接传 `@107`。
- 不要手写推导 `@107` 这类编号；这些编号来自运行时 `spotMeta`，应通过 `await hl.get_coin_name("HYPE/USDC")` 获取。
- 不是所有 `BASE/QUOTE` 字符串都会存在，只有 `spotMeta.universe` 中实际返回的 pair 才能解析，例如测试中 `ETH/USDC` 被视为不支持。
- quote token 自身，例如 `USDC`，会被缓存为 token 别名以支持 token info 查询；它不一定对应一个可交易 market asset。

## 快速例子

```python
await hl.init_metas()

await hl.get_coin_name("BTC")
# "BTC"

await hl.get_coin_name("HYPE/USDC")
# "@107" on current mainnet metadata

await hl.get_coin_asset("HYPE/USDC")
# 10107 when spot index is 107

await hl.get_coin_symbol("@107")
# "HYPE/USDC"
```
