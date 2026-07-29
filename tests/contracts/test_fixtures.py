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
        "order_error",
        "order_filled",
        "order_resting",
    }


def test_meta_context_fixtures_keep_exact_two_item_pairs() -> None:
    responses = load_fixture("info-responses.json")

    assert len(cast(list[object], responses["metaAndAssetCtxs"])) == 2
    assert len(cast(list[object], responses["spotMetaAndAssetCtxs"])) == 2
    all_perp_metas = cast(list[list[object]], responses["allPerpMetas"])
    assert all(len(meta_and_contexts) == 2 for meta_and_contexts in all_perp_metas)
