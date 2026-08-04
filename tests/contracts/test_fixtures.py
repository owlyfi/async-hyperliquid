import json
from pathlib import Path
from typing import cast


FIXTURES = Path(__file__).parent / "fixtures"
EXPECTED_INFO_REQUESTS = {
    "activeAssetData",
    "alignedQuoteTokenInfo",
    "allMids",
    "allPerpMetas",
    "candleSnapshot",
    "clearinghouseState",
    "delegations",
    "delegatorHistory",
    "delegatorRewards",
    "delegatorSummary",
    "frontendOpenOrders",
    "fundingHistory",
    "historicalOrders",
    "l2Book",
    "maxBuilderFee",
    "meta",
    "metaAndAssetCtxs",
    "openOrders",
    "orderStatus",
    "perpDeployAuctionStatus",
    "perpDexs",
    "perpsAtOpenInterestCap",
    "portfolio",
    "predictedFundings",
    "referral",
    "spotClearinghouseState",
    "spotDeployState",
    "spotMeta",
    "spotMetaAndAssetCtxs",
    "subAccounts",
    "tokenDetails",
    "userAbstraction",
    "userDexAbstraction",
    "userFees",
    "userFills",
    "userFillsByTime",
    "userFunding",
    "userNonFundingLedgerUpdates",
    "userRateLimit",
    "userRole",
    "userTwapSliceFills",
    "userVaultEquities",
    "vaultDetails",
}


def load_fixture(name: str) -> dict[str, object]:
    data = json.loads((FIXTURES / name).read_text())
    return cast(dict[str, object], data)


def test_info_fixture_covers_every_0_5_1_request_shape() -> None:
    responses = load_fixture("info-responses.json")

    assert set(responses) == EXPECTED_INFO_REQUESTS


def test_exchange_fixture_freezes_all_order_and_cancel_status_shapes() -> None:
    responses = load_fixture("exchange-responses.json")

    assert set(responses) == {
        "cancel_error",
        "cancel_success",
        "order_deferred",
        "order_error",
        "order_filled",
        "order_resting",
        "twap_cancel_error",
        "twap_cancel_success",
        "twap_order_error",
        "twap_order_running",
    }


def test_meta_context_fixtures_keep_exact_two_item_pairs() -> None:
    responses = load_fixture("info-responses.json")

    assert len(cast(list[object], responses["metaAndAssetCtxs"])) == 2
    assert len(cast(list[object], responses["spotMetaAndAssetCtxs"])) == 2


def test_all_perp_metas_fixture_is_a_list_of_meta_objects() -> None:
    responses = load_fixture("info-responses.json")
    all_perp_metas = cast(list[object], responses["allPerpMetas"])

    assert all(
        isinstance(meta, dict)
        and isinstance(cast(dict[str, object], meta).get("universe"), list)
        for meta in all_perp_metas
    )
