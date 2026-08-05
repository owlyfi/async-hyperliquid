import json
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import cast

import pytest

from benchmarks.live.models import CanonicalOrder, OrderPair
from benchmarks.live.pacing import WeightedPacer
from benchmarks.live.preflight import Credentials
from benchmarks.live.providers import ProviderSet, WireOrder
from benchmarks.live_exchange import parse_args, run_live


ROOT = Path(__file__).parents[2]


class FakeProvider:
    def __init__(self, name: str) -> None:
        self.name = name
        self.closed = False
        self._next_oid = 100

    def wire_orders(self, pair: OrderPair) -> tuple[WireOrder, WireOrder]:
        orders = tuple(
            cast(
                WireOrder,
                {
                    "asset": 0,
                    "isBuy": order.is_buy,
                    "limitPx": str(order.price),
                    "sz": str(order.size),
                    "reduceOnly": False,
                    "orderType": {"limit": {"tif": "Alo"}},
                    "cloid": order.cloid,
                },
            )
            for order in pair.as_tuple()
        )
        return cast(tuple[WireOrder, WireOrder], orders)

    async def place(self, pair: OrderPair) -> tuple[int, int]:
        del pair
        self._next_oid += 2
        return (self._next_oid - 1, self._next_oid)

    async def cancel_oids(
        self, orders: Sequence[CanonicalOrder], oids: Sequence[int]
    ) -> None:
        assert len(orders) == len(oids)

    async def cancel_cloids(self, orders: Sequence[CanonicalOrder]) -> None:
        assert orders

    async def close(self) -> None:
        self.closed = True


class FakeMarketSource:
    async def snapshot(self) -> tuple[float, int]:
        return (100_000.0, 5)


class IncrementingClock:
    def __init__(self, step: int) -> None:
        self.value = 0
        self.step = step

    def __call__(self) -> int:
        self.value += self.step
        return self.value


async def no_sleep(seconds: float) -> None:
    del seconds


def fake_pacer(interval_ns: int) -> WeightedPacer:
    return WeightedPacer(
        interval_ns=interval_ns,
        clock_ns=IncrementingClock(1_000_000_000),
        sleep=no_sleep,
    )


def test_live_cli_defaults_and_required_paths(tmp_path: Path) -> None:
    args = parse_args(["all", "--output-dir", str(tmp_path)])

    assert args.command == "all"
    assert args.rounds == 30
    assert args.warmups == 3
    assert args.interval_ms == 250
    assert args.output_dir == tmp_path

    with pytest.raises(SystemExit):
        parse_args(["providers"])
    with pytest.raises(SystemExit):
        parse_args(["publish"])


def test_live_cli_rejects_interval_below_rate_limit_floor(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        parse_args(["cancel-id", "--output-dir", str(tmp_path), "--interval-ms", "249"])


@pytest.mark.asyncio
async def test_missing_credentials_fail_before_provider_construction(
    tmp_path: Path,
) -> None:
    constructed = False

    async def provider_factory(credentials: Credentials) -> ProviderSet:
        nonlocal constructed
        constructed = True
        raise AssertionError(f"must not construct providers: {credentials!r}")

    outcome = await run_live(
        parse_args(["all", "--output-dir", str(tmp_path)]),
        environ={},
        provider_factory=provider_factory,
    )

    assert not outcome.valid
    assert outcome.report_path.name == "report.invalid.json"
    assert not constructed
    report = json.loads(outcome.report_path.read_text())
    assert report["failure_reason"] == "preflight_failed"


@pytest.mark.asyncio
async def test_all_runs_offline_through_injected_providers(tmp_path: Path) -> None:
    providers = tuple(
        FakeProvider(name) for name in ("ccxt", "sdk", "async-hyperliquid")
    )
    recovery = FakeProvider("recovery")
    provider_set = ProviderSet(
        measured=providers,
        recovery=recovery,
        mid_source=FakeMarketSource(),
        owned=(*providers, recovery),
    )
    constructed = 0

    async def provider_factory(credentials: Credentials) -> ProviderSet:
        nonlocal constructed
        constructed += 1
        assert (
            credentials.subaccount_address
            == "0x3333333333333333333333333333333333333333"
        )
        return provider_set

    environment: Mapping[str, str] = {
        "IS_MAINNET": "false",
        "HL_ADDR": "0x1111111111111111111111111111111111111111",
        "HL_AK": "0x19E7E376E7C213B7E7e7e46cc70A5dD086DAff2A",
        "HL_SK": "0x" + "11" * 32,
        "HL_SUB": "0x3333333333333333333333333333333333333333",
    }
    args = parse_args(
        ["all", "--output-dir", str(tmp_path), "--rounds", "1", "--warmups", "0"]
    )

    outcome = await run_live(
        args,
        environ=environment,
        provider_factory=provider_factory,
        pacer_factory=fake_pacer,
        clock_ns=IncrementingClock(1_000_000),
        versions={"async-hyperliquid": "1.0.0rc1", "sdk": "0.24.0", "ccxt": "4.5.71"},
    )

    assert outcome.valid
    assert outcome.report_path.name == "report.json"
    assert constructed == 1
    assert all(provider.closed for provider in (*providers, recovery))
    report = json.loads(outcome.report_path.read_text())
    assert len(report["samples"]) == 8
    assert set(report["summaries"]) == {"cancel-id", "providers"}
    assert (tmp_path / "samples.csv").is_file()
    assert (tmp_path / "cancel-id-latency.svg").is_file()
    assert (tmp_path / "providers-latency.png").is_file()


def test_documented_script_entrypoint_can_render_help() -> None:
    completed = subprocess.run(
        (sys.executable, str(ROOT / "benchmarks" / "live_exchange.py"), "--help"),
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert "cancel-id" in completed.stdout
    assert "providers" in completed.stdout
    assert "publish" in completed.stdout
