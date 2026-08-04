from typing import get_args, get_type_hints

from async_hyperliquid.types.exchange import (
    ActionEnvelope,
    EncodedOrder,
    ExchangeAction,
)
from async_hyperliquid.types.info import (
    ActiveAssetLeverage,
    AgentUserRole,
    AllPerpMetas,
    EvmContract,
    GasAuction,
    L2Book,
    OpenOrder,
    PlainUserRole,
    PerpMeta,
    PerpMetaAndContexts,
    Referral,
    ReferralReward,
    ReferrerState,
    SpotMeta,
    SpotMetaAndContexts,
    SpotToken,
    TokenReferralEntry,
    SubAccountUserRole,
    UnknownOrderStatus,
    UserRole,
    UserRateLimit,
)


def test_rate_limit_includes_surplus_counter() -> None:
    assert get_type_hints(UserRateLimit) == {
        "cumVlm": str,
        "nRequestsUsed": int,
        "nRequestsCap": int,
        "nRequestsSurplus": int,
    }


def test_open_order_includes_original_size() -> None:
    assert get_type_hints(OpenOrder)["origSz"] is str


def test_l2_book_matches_coin_time_and_two_sided_levels_shape() -> None:
    assert set(get_type_hints(L2Book)) == {"coin", "time", "levels"}


def test_unknown_order_status_spelling_matches_the_wire() -> None:
    assert get_args(get_type_hints(UnknownOrderStatus)["status"]) == ("unknownOid",)


def test_meta_context_pairs_are_exact_two_tuples() -> None:
    assert get_args(PerpMetaAndContexts)[0] is PerpMeta
    assert get_args(SpotMetaAndContexts)[0] is SpotMeta


def test_spot_token_uses_the_evm_contract_object_shape() -> None:
    contract_type = get_type_hints(SpotToken)["evmContract"]

    assert EvmContract in get_args(contract_type)
    assert get_type_hints(EvmContract) == {
        "address": str,
        "evm_extra_wei_decimals": int,
    }


def test_all_perp_metas_is_a_list_of_meta_objects() -> None:
    assert get_args(AllPerpMetas)[0] is PerpMeta


def test_encoded_cloid_is_a_raw_string() -> None:
    assert get_type_hints(EncodedOrder)["c"] is str


def test_action_envelope_has_a_discriminated_action_union() -> None:
    hints = get_type_hints(ActionEnvelope)

    assert hints["action"] == ExchangeAction
    assert set(get_args(hints["vaultAddress"])) == {str, type(None)}
    assert set(get_args(hints["expiresAfter"])) == {int, type(None)}
    assert ActionEnvelope.__required_keys__ == frozenset(hints)


def test_referral_includes_token_reward_state() -> None:
    assert get_type_hints(Referral)["tokenToState"] == list[TokenReferralEntry]
    assert get_type_hints(Referral)["rewardHistory"] == list[ReferralReward]
    assert type(None) in get_args(get_type_hints(Referral)["referredBy"])
    assert len(get_args(ReferrerState)) == 3


def test_active_asset_leverage_supports_hip3_raw_usd() -> None:
    assert get_type_hints(ActiveAssetLeverage)["rawUsd"] is str


def test_spot_gas_auction_phase_prices_can_be_missing() -> None:
    hints = get_type_hints(GasAuction)

    assert type(None) in get_args(hints["currentGas"])
    assert type(None) in get_args(hints["endGas"])


def test_user_role_is_a_discriminated_union_without_a_mapping_escape_hatch() -> None:
    assert get_args(UserRole) == (PlainUserRole, AgentUserRole, SubAccountUserRole)
