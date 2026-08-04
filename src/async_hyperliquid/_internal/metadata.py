from dataclasses import dataclass, field
from typing import cast

from ..constants import (
    OUTCOME_ASSET_OFFSET,
    PERP_DEX_ASSET_OFFSET,
    PERP_DEX_ASSET_STRIDE,
    SPOT_ASSET_OFFSET,
)
from ..errors import ProtocolError
from ..types import JsonObject, JsonValue
from ..types.info import AllPerpMetas, SpotMeta, SpotToken


@dataclass(frozen=True, slots=True)
class _MarketInfo:
    coin: str
    asset: int
    size_decimals: int
    is_spot: bool
    dex: str


@dataclass(frozen=True, slots=True)
class _MetadataSnapshot:
    coin_by_alias: dict[str, str]
    asset_by_coin: dict[str, int]
    symbol_by_coin: dict[str, str]
    size_decimals_by_asset: dict[int, int]
    spot_token_by_coin: dict[str, SpotToken]
    perp_context_by_coin: dict[str, tuple[str, int]]
    spot_market_coins: frozenset[str]
    perp_dex_names: tuple[str, ...]


@dataclass(slots=True)
class _MetadataIndex:
    coin_by_alias: dict[str, str] = field(default_factory=dict)
    asset_by_coin: dict[str, int] = field(default_factory=dict)
    symbol_by_coin: dict[str, str] = field(default_factory=dict)
    size_decimals_by_asset: dict[int, int] = field(default_factory=dict)
    spot_token_by_coin: dict[str, SpotToken] = field(default_factory=dict)
    perp_context_by_coin: dict[str, tuple[str, int]] = field(default_factory=dict)
    spot_market_coins: set[str] = field(default_factory=set)


def _require_list(value: JsonValue | None, field: str) -> list[JsonValue]:
    if not isinstance(value, list):
        raise ProtocolError(f"metadata field {field} must be a list")
    return value


def _require_object(value: JsonValue, field: str) -> dict[str, JsonValue]:
    if not isinstance(value, dict):
        raise ProtocolError(f"metadata field {field} must be an object")
    return value


def _require_str(value: JsonValue | None, field: str) -> str:
    if not isinstance(value, str):
        raise ProtocolError(f"metadata field {field} must be a string")
    return value


def _require_int(value: JsonValue | None, field: str) -> int:
    if type(value) is not int:
        raise ProtocolError(f"metadata field {field} must be an integer")
    return value


def _require_non_negative_int(value: JsonValue | None, field: str) -> int:
    number = _require_int(value, field)
    if number < 0:
        raise ProtocolError(f"metadata field {field} must be non-negative")
    return number


def _require_bool(value: JsonValue | None, field: str) -> bool:
    if type(value) is not bool:
        raise ProtocolError(f"metadata field {field} must be a boolean")
    return value


def _require_optional_str(value: JsonValue, field: str) -> str | None:
    if value is not None and not isinstance(value, str):
        raise ProtocolError(f"metadata field {field} must be a string or null")
    return value


def _require_optional_evm_contract(value: JsonValue, field: str) -> None:
    if value is None:
        return
    contract = _require_object(value, field)
    _require_str(contract.get("address"), f"{field}.address")
    _require_int(
        contract.get("evm_extra_wei_decimals"), f"{field}.evm_extra_wei_decimals"
    )


def _dex_offsets(dex_names: tuple[str, ...]) -> dict[str, int]:
    if not dex_names or dex_names[0] != "":
        raise ProtocolError("perpDexs must start with the base dex")
    if len(set(dex_names)) != len(dex_names):
        raise ProtocolError("perpDexs contains duplicate names")
    return {
        name: (
            0
            if index == 0
            else PERP_DEX_ASSET_OFFSET + (index - 1) * PERP_DEX_ASSET_STRIDE
        )
        for index, name in enumerate(dex_names)
    }


def _perp_dex(name: str) -> str:
    return name.partition(":")[0] if ":" in name else ""


def _index_perp_metadata(
    index: _MetadataIndex, dex_names: tuple[str, ...], all_perp_metas: AllPerpMetas
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
        base_index = _require_int(token_indexes[0], "spotMeta.universe[].tokens[0]")
        quote_index = _require_int(token_indexes[1], "spotMeta.universe[].tokens[1]")
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


def _build_metadata(
    dex_names: tuple[str, ...], all_perp_metas: AllPerpMetas, spot_meta: SpotMeta
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


def _outcome_market_info(coin: str) -> _MarketInfo | None:
    if not coin.startswith(("#", "+")):
        return None
    raw_encoding = coin[1:]
    if not raw_encoding.isascii() or not raw_encoding.isdecimal():
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
