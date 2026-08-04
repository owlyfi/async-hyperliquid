import ast
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
import inspect
import json
from pathlib import Path
import subprocess
import sys
from typing import cast

from aiohttp import web
from aiohttp.test_utils import TestServer
import pytest

from async_hyperliquid._http import _HttpTransport
from async_hyperliquid.errors import ProtocolError
from async_hyperliquid.info import InfoClient
from async_hyperliquid.types import CandleInterval, JsonObject, JsonValue, Network


ADDRESS = "0x1111111111111111111111111111111111111111"
FIXTURES = Path(__file__).parents[1] / "contracts" / "fixtures"
Handler = Callable[[web.Request], Awaitable[web.StreamResponse]]


def load_responses() -> dict[str, JsonValue]:
    return cast(
        dict[str, JsonValue], json.loads((FIXTURES / "info-responses.json").read_text())
    )


class RecordingTransport:
    def __init__(self, responses: dict[str, JsonValue] | None = None) -> None:
        self.responses = responses or {}
        self.open_calls = 0
        self.close_calls = 0
        self.requests: list[tuple[str, JsonObject]] = []

    async def open(self) -> None:
        self.open_calls += 1

    async def close(self) -> None:
        self.close_calls += 1

    async def post_json(self, url: str, payload: JsonObject) -> JsonValue:
        self.requests.append((url, payload))
        request_type = payload["type"]
        assert isinstance(request_type, str)
        return self.responses[request_type]


@asynccontextmanager
async def serve(handler: Handler) -> AsyncIterator[TestServer]:
    app = web.Application()
    app.router.add_post("/{path:.*}", handler)
    server = TestServer(app)
    await server.start_server()
    try:
        yield server
    finally:
        await server.close()


def test_constructor_is_synchronous_and_network_selects_only_the_default_url() -> None:
    mainnet = InfoClient()
    testnet = InfoClient(network=Network.TESTNET)
    custom = InfoClient(
        network=Network.TESTNET, info_url="https://provider.example/custom/info"
    )

    assert mainnet.info_url == Network.MAINNET.info_url
    assert testnet.info_url == Network.TESTNET.info_url
    assert custom.info_url == "https://provider.example/custom/info"
    assert mainnet._transport._session is None
    assert not hasattr(mainnet, "exchange")

    with pytest.raises(AttributeError):
        custom.info_url = "https://other.example/info"  # type: ignore[misc]


async def test_standalone_owns_lifecycle_while_bound_client_borrows_it() -> None:
    standalone_transport = RecordingTransport()
    standalone = InfoClient()
    standalone._transport = cast(_HttpTransport, standalone_transport)

    async with standalone:
        pass

    root_transport = RecordingTransport()
    bound = InfoClient._from_transport(
        cast(_HttpTransport, root_transport), info_url="https://provider.example/info"
    )
    await bound.open()
    await bound.close()

    assert standalone_transport.open_calls == 1
    assert standalone_transport.close_calls == 1
    assert root_transport.open_calls == 0
    assert root_transport.close_calls == 0


async def test_all_info_endpoints_match_the_frozen_request_and_response_contracts() -> (
    None
):
    responses = load_responses()
    transport = RecordingTransport(responses)
    info = InfoClient._from_transport(
        cast(_HttpTransport, transport), info_url="https://provider.example/info"
    )

    assert await info.all_mids() == responses["allMids"]
    assert await info.open_orders(ADDRESS) == responses["openOrders"]
    assert (
        await info.open_orders(ADDRESS, frontend=True)
        == responses["frontendOpenOrders"]
    )
    assert (
        await info.user_fills(ADDRESS, aggregate_by_time=True) == responses["userFills"]
    )
    assert (
        await info.user_fills(ADDRESS, aggregate_by_time=True, start_time=1, end_time=2)
        == responses["userFillsByTime"]
    )
    assert await info.user_rate_limit(ADDRESS) == responses["userRateLimit"]
    assert await info.order_status(ADDRESS, 1) == responses["orderStatus"]
    assert await info.l2_book("BTC", n_sig_figs=5, mantissa=2) == responses["l2Book"]
    assert (
        await info.candles("BTC", CandleInterval.FIFTEEN_MINUTES, 1, 2)
        == responses["candleSnapshot"]
    )
    assert await info.max_builder_fee(ADDRESS, ADDRESS) == responses["maxBuilderFee"]
    assert await info.historical_orders(ADDRESS) == responses["historicalOrders"]
    assert await info.twap_slice_fills(ADDRESS) == responses["userTwapSliceFills"]
    assert await info.sub_accounts(ADDRESS) == responses["subAccounts"]
    assert await info.vault_details(ADDRESS, user=ADDRESS) == responses["vaultDetails"]
    assert await info.vault_equities(ADDRESS) == responses["userVaultEquities"]
    assert await info.user_role(ADDRESS) == responses["userRole"]
    assert await info.portfolio(ADDRESS) == responses["portfolio"]
    assert await info.referral(ADDRESS) == responses["referral"]
    assert await info.user_fees(ADDRESS) == responses["userFees"]
    assert await info.delegations(ADDRESS) == responses["delegations"]
    assert await info.staking_summary(ADDRESS) == responses["delegatorSummary"]
    assert await info.staking_history(ADDRESS) == responses["delegatorHistory"]
    assert await info.staking_rewards(ADDRESS) == responses["delegatorRewards"]
    assert await info.user_dex_abstraction(ADDRESS) == responses["userDexAbstraction"]
    assert await info.user_abstraction(ADDRESS) == responses["userAbstraction"]
    assert await info.aligned_quote_token_info(0) == responses["alignedQuoteTokenInfo"]
    assert await info.perp_meta() == responses["meta"]
    assert await info.perp_meta_and_contexts() == tuple(
        cast(list[JsonValue], responses["metaAndAssetCtxs"])
    )
    assert await info.all_perp_metas() == responses["allPerpMetas"]
    assert await info.perp_dexes() == responses["perpDexs"]
    assert await info.perp_account_state(ADDRESS) == responses["clearinghouseState"]
    assert (
        await info.funding_updates(ADDRESS, 1, end_time=2) == responses["userFunding"]
    )
    assert (
        await info.non_funding_ledger_updates(ADDRESS, 1, end_time=2)
        == responses["userNonFundingLedgerUpdates"]
    )
    assert (
        await info.funding_history("BTC", 1, end_time=2) == responses["fundingHistory"]
    )
    assert await info.predicted_fundings() == responses["predictedFundings"]
    assert (
        await info.perps_at_open_interest_cap() == responses["perpsAtOpenInterestCap"]
    )
    assert (
        await info.perp_deploy_auction_status() == responses["perpDeployAuctionStatus"]
    )
    assert await info.active_asset_data(ADDRESS, "BTC") == responses["activeAssetData"]
    assert await info.spot_meta() == responses["spotMeta"]
    assert await info.spot_meta_and_contexts() == tuple(
        cast(list[JsonValue], responses["spotMetaAndAssetCtxs"])
    )
    assert await info.spot_account_state(ADDRESS) == responses["spotClearinghouseState"]
    assert await info.spot_deploy_state(ADDRESS) == responses["spotDeployState"]
    assert await info.token_details("0x00") == responses["tokenDetails"]

    assert {cast(str, payload["type"]) for _, payload in transport.requests} == set(
        responses
    )
    assert all(url == "https://provider.example/info" for url, _ in transport.requests)
    by_type = {cast(str, payload["type"]): payload for _, payload in transport.requests}
    assert by_type["userFills"] == {
        "type": "userFills",
        "user": ADDRESS,
        "aggregateByTime": True,
    }
    assert by_type["userFillsByTime"] == {
        "type": "userFillsByTime",
        "user": ADDRESS,
        "aggregateByTime": True,
        "startTime": 1,
        "endTime": 2,
    }


async def test_endpoint_boundary_rejects_the_wrong_top_level_shape() -> None:
    transport = RecordingTransport({"allMids": []})
    info = InfoClient._from_transport(
        cast(_HttpTransport, transport), info_url="https://provider.example/info"
    )

    with pytest.raises(ProtocolError, match="allMids"):
        await info.all_mids()

    transport.responses = {"tokenDetails": None}
    assert await info.token_details("0x00") is None


async def test_all_perp_metas_returns_the_current_meta_object_list() -> None:
    meta: JsonObject = {
        "universe": [
            {"name": "BTC", "szDecimals": 5, "maxLeverage": 40, "marginTableId": 56}
        ],
        "marginTables": [],
        "collateralToken": 0,
    }
    transport = RecordingTransport({"allPerpMetas": [meta]})
    info = InfoClient._from_transport(
        cast(_HttpTransport, transport), info_url="https://provider.example/info"
    )

    assert await info.all_perp_metas() == [meta]


async def test_self_hosted_info_url_receives_unsigned_info_payload_only() -> None:
    requests: list[JsonObject] = []

    async def handler(request: web.Request) -> web.Response:
        assert request.path == "/local/info"
        payload = cast(JsonObject, await request.json())
        requests.append(payload)
        return web.json_response({"BTC": "100000.0"})

    async with serve(handler) as server:
        async with InfoClient(info_url=str(server.make_url("/local/info"))) as info:
            assert await info.all_mids() == {"BTC": "100000.0"}

    assert requests == [{"type": "allMids", "dex": ""}]
    assert set(requests[0]).isdisjoint({"action", "nonce", "signature"})


def test_public_info_client_has_no_signing_capability_or_dependency() -> None:
    signature = inspect.signature(InfoClient)
    assert tuple(signature.parameters) == ("network", "info_url", "session", "timeout")
    assert "address" not in signature.parameters
    assert "signing_key" not in signature.parameters
    assert not hasattr(InfoClient, "exchange")

    source_root = Path(__file__).parents[2] / "src" / "async_hyperliquid"
    imported_modules: set[str] = set()
    annotation_violations: list[str] = []
    for name in ("info.py", "_metadata.py"):
        tree = ast.parse((source_root / name).read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id == "Any":
                annotation_violations.append(f"{name}:{node.lineno}: Any")
            if isinstance(node, ast.Import):
                imported_modules.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module is not None:
                imported_modules.add(node.module)
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            if node.name.startswith("_"):
                continue
            annotations = [
                argument.annotation
                for argument in (*node.args.posonlyargs, *node.args.args)
                if argument.annotation is not None
            ]
            if node.returns is not None:
                annotations.append(node.returns)
            for annotation in annotations:
                if isinstance(annotation, ast.Name) and annotation.id in {
                    "dict",
                    "list",
                    "set",
                    "tuple",
                }:
                    annotation_violations.append(
                        f"{name}:{annotation.lineno}: naked {annotation.id}"
                    )

    assert all(
        not module.startswith(("eth_account", "hl_web3")) for module in imported_modules
    )
    assert annotation_violations == []


def test_root_info_import_does_not_load_the_signing_stack() -> None:
    probe = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys\n"
                "from async_hyperliquid import InfoClient\n"
                "loaded = sys.modules\n"
                "signing = any(name == 'eth_account' or "
                "name.startswith('eth_account.') for name in loaded)\n"
                "signing |= 'async_hyperliquid._signing' in loaded\n"
                "print(signing)\n"
            ),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert probe.stdout.strip() == "False"
