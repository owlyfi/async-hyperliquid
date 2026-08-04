from dataclasses import dataclass
from typing import cast

from .constants import PERP_DEX_ASSET_OFFSET, PERP_DEX_ASSET_STRIDE, SPOT_ASSET_OFFSET
from .errors import ProtocolError
from .types import JsonObject, JsonValue
from .types.info import AllPerpMetas, SpotMeta, SpotToken


@dataclass(frozen=True, slots=True)
class _MetadataSnapshot:
    coin_by_alias: dict[str, str]
    asset_by_coin: dict[str, int]
    symbol_by_coin: dict[str, str]
    size_decimals_by_asset: dict[int, int]
    spot_token_by_coin: dict[str, SpotToken]
    perp_context_by_coin: dict[str, tuple[str, int]]
    spot_context_by_coin: dict[str, int]
    perp_dex_names: tuple[str, ...]


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


def _build_metadata_snapshot(
    dex_names: tuple[str, ...], all_perp_metas: AllPerpMetas, spot_meta: SpotMeta
) -> _MetadataSnapshot:
    offsets = _dex_offsets(dex_names)
    coin_by_alias: dict[str, str] = {}
    asset_by_coin: dict[str, int] = {}
    symbol_by_coin: dict[str, str] = {}
    size_decimals_by_asset: dict[int, int] = {}
    spot_token_by_coin: dict[str, SpotToken] = {}
    perp_context_by_coin: dict[str, tuple[str, int]] = {}
    spot_context_by_coin: dict[str, int] = {}

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

        for index, asset_value in enumerate(universe):
            asset = _require_object(asset_value, "allPerpMetas[].universe[]")
            name = _require_str(asset.get("name"), "allPerpMetas[].universe[].name")
            decimals = _require_int(
                asset.get("szDecimals"), "allPerpMetas[].universe[].szDecimals"
            )
            if _perp_dex(name) != dex:
                raise ProtocolError("allPerpMetas contains mixed dex asset metadata")
            if name in asset_by_coin:
                raise ProtocolError("allPerpMetas contains duplicate asset metadata")
            asset_id = offset + index
            coin_by_alias[name] = name
            asset_by_coin[name] = asset_id
            symbol_by_coin[name] = name
            size_decimals_by_asset[asset_id] = decimals
            perp_context_by_coin[name] = (dex, index)

    if seen_perp_dexes != offsets.keys():
        raise ProtocolError("allPerpMetas is missing dex metadata")

    spot_object = cast(JsonObject, spot_meta)
    token_objects = _require_list(spot_object.get("tokens"), "spotMeta.tokens")
    tokens_by_index: dict[int, SpotToken] = {}
    for token_value in token_objects:
        token = _require_object(token_value, "spotMeta.tokens[]")
        index = _require_non_negative_int(token.get("index"), "spotMeta.tokens[].index")
        _require_str(token.get("name"), "spotMeta.tokens[].name")
        _require_bool(token.get("isCanonical"), "spotMeta.tokens[].isCanonical")
        _require_non_negative_int(
            token.get("szDecimals"), "spotMeta.tokens[].szDecimals"
        )
        _require_non_negative_int(
            token.get("weiDecimals"), "spotMeta.tokens[].weiDecimals"
        )
        _require_str(token.get("tokenId"), "spotMeta.tokens[].tokenId")
        for field in ("evmContract", "fullName"):
            if field not in token:
                raise ProtocolError(
                    f"metadata field spotMeta.tokens[].{field} is required"
                )
            _require_optional_str(token[field], f"spotMeta.tokens[].{field}")
        if index in tokens_by_index:
            raise ProtocolError("spotMeta contains duplicate token indexes")
        tokens_by_index[index] = cast(SpotToken, token)

    pair_objects = _require_list(spot_object.get("universe"), "spotMeta.universe")
    spot_pair_indexes: set[int] = set()
    for context_index, pair_value in enumerate(pair_objects):
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
        if coin in asset_by_coin or pair_index in spot_pair_indexes:
            raise ProtocolError("spotMeta contains duplicate pair metadata")
        spot_pair_indexes.add(pair_index)

        base_name = base["name"]
        quote_name = quote["name"]
        display_name = f"{base_name}/{quote_name}"
        asset_id = SPOT_ASSET_OFFSET + pair_index

        coin_by_alias[coin] = coin
        coin_by_alias.setdefault(display_name, coin)
        coin_by_alias.setdefault(quote_name, quote_name)
        asset_by_coin[coin] = asset_id
        symbol_by_coin[coin] = display_name
        size_decimals_by_asset[asset_id] = base["szDecimals"]
        spot_token_by_coin[coin] = base
        spot_token_by_coin.setdefault(quote_name, quote)
        spot_context_by_coin[coin] = context_index

    return _MetadataSnapshot(
        coin_by_alias=coin_by_alias,
        asset_by_coin=asset_by_coin,
        symbol_by_coin=symbol_by_coin,
        size_decimals_by_asset=size_decimals_by_asset,
        spot_token_by_coin=spot_token_by_coin,
        perp_context_by_coin=perp_context_by_coin,
        spot_context_by_coin=spot_context_by_coin,
        perp_dex_names=dex_names,
    )
