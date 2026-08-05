"""Rate-controlled Hyperliquid testnet order benchmarks."""

from __future__ import annotations

import argparse
import asyncio
import importlib.metadata
import os
import platform
import subprocess
import sys
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter_ns

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from benchmarks.live.models import (
    BenchmarkConfig,
    BenchmarkFailure,
    COMBINED_DIAGNOSTIC_WORKLOAD,
    CONCURRENT_CANCEL_WORKLOAD,
    GitMetadata,
    PROVIDER_DIAGNOSTIC_WORKLOAD,
    WorkloadName,
)
from benchmarks.live.pacing import WeightedPacer
from benchmarks.live.preflight import Credentials
from benchmarks.live.providers import (
    ConcurrentCancelProvider,
    ProviderSet,
    build_providers,
)
from benchmarks.live.reporting import publish_report, write_csv, write_figures
from benchmarks.live.results import SampleRecorder, write_report
from benchmarks.live.runner import run_cancel_id_suite, run_provider_suite


ProviderFactory = Callable[[Credentials], Awaitable[ProviderSet]]
PacerFactory = Callable[[int], WeightedPacer]


@dataclass(frozen=True, slots=True)
class LiveRunOutcome:
    report_path: Path
    valid: bool


def _positive(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be positive")
    return parsed


def _nonnegative(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("must not be negative")
    return parsed


def _interval_ms(value: str) -> int:
    parsed = int(value)
    if parsed < 250:
        raise argparse.ArgumentTypeError("must be at least 250")
    return parsed


def _add_live_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--rounds", default=30, type=_positive)
    parser.add_argument("--warmups", default=3, type=_nonnegative)
    parser.add_argument("--interval-ms", default=250, type=_interval_ms)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name, help_text in (
        ("cancel-id", "run the publishable 20-request OID/CLOID benchmark"),
        ("providers", "run the unpublishable provider diagnostic suite"),
        ("all", "run both suites for diagnostics; output is not publishable"),
    ):
        command = commands.add_parser(name, help=help_text)
        _add_live_arguments(command)
    publish = commands.add_parser(
        "publish", help="publish one validated default-shape report"
    )
    publish.add_argument("--report", required=True, type=Path)
    publish.add_argument("--repository-root", default=Path.cwd(), type=Path)
    return parser


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    return build_parser().parse_args(argv)


def _runtime_versions() -> dict[str, str]:
    return {
        "async-hyperliquid": importlib.metadata.version("async-hyperliquid"),
        "sdk": importlib.metadata.version("hyperliquid-python-sdk"),
        "ccxt": importlib.metadata.version("ccxt"),
    }


def _git_metadata(repository_root: Path) -> GitMetadata:
    try:
        revision = subprocess.run(
            ("git", "rev-parse", "HEAD"),
            cwd=repository_root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        dirty = bool(
            subprocess.run(
                ("git", "status", "--porcelain"),
                cwd=repository_root,
                check=True,
                capture_output=True,
                text=True,
            ).stdout
        )
    except (OSError, subprocess.CalledProcessError):
        return GitMetadata(revision="unknown", dirty=True)
    return GitMetadata(revision=revision, dirty=dirty)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _default_pacer(interval_ns: int) -> WeightedPacer:
    return WeightedPacer(interval_ns=interval_ns)


def _failure_reason(error: Exception, phase: str) -> str:
    if phase == "preflight":
        return "preflight_failed"
    if phase == "provider_setup":
        return "provider_setup_failed"
    if isinstance(error, BenchmarkFailure) and error.args in (
        ("cancel-id cleanup failed",),
        ("providers cleanup failed",),
    ):
        return "order_cleanup_failed"
    if phase == "cancel-id":
        return "cancel_id_failed"
    if phase == "providers":
        return "provider_suite_failed"
    return "benchmark_failed"


def _secret_values(environ: Mapping[str, str]) -> tuple[str, ...]:
    return tuple(
        value
        for name in ("HL_ADDR", "HL_AK", "HL_SK", "HL_SUB")
        if len(value := environ.get(name, "")) >= 8
    )


def _prepare_output_directory(path: Path) -> None:
    try:
        if path.exists():
            if not path.is_dir() or any(path.iterdir()):
                raise BenchmarkFailure("output directory must be empty")
            return
        path.mkdir(parents=True)
    except BenchmarkFailure:
        raise
    except OSError as error:
        raise BenchmarkFailure("output directory is not usable") from error


async def run_live(
    args: argparse.Namespace,
    *,
    environ: Mapping[str, str],
    provider_factory: ProviderFactory = build_providers,
    pacer_factory: PacerFactory = _default_pacer,
    clock_ns: Callable[[], int] = perf_counter_ns,
    versions: Mapping[str, str] | None = None,
) -> LiveRunOutcome:
    output_dir = args.output_dir
    _prepare_output_directory(output_dir)
    config = BenchmarkConfig(
        rounds=args.rounds,
        warmups=args.warmups,
        interval_ns=args.interval_ms * 1_000_000,
    )
    workloads: dict[str, WorkloadName] = {
        "cancel-id": CONCURRENT_CANCEL_WORKLOAD,
        "providers": PROVIDER_DIAGNOSTIC_WORKLOAD,
        "all": COMBINED_DIAGNOSTIC_WORKLOAD,
    }
    workload = workloads.get(args.command)
    if workload is None:
        raise BenchmarkFailure("benchmark workload is not supported")
    recorder = SampleRecorder(
        config=config,
        environment={
            "network": "testnet",
            "python": platform.python_version(),
            "platform": f"{platform.system()}-{platform.machine()}",
        },
        versions=_runtime_versions() if versions is None else versions,
        git=_git_metadata(Path.cwd()),
        workload=workload,
    )
    started_at = _utc_now()
    providers: ProviderSet | None = None
    failure_reason: str | None = None
    cleanup_ok = True
    phase = "preflight"

    try:
        credentials = Credentials.from_environ(environ)
        phase = "provider_setup"
        providers = await provider_factory(credentials)
        phase = "benchmark"
        pacer = pacer_factory(config.interval_ns)
        if args.command in ("cancel-id", "all"):
            phase = "cancel-id"
            async_candidates = tuple(
                provider
                for provider in providers.measured
                if provider.name == "async-hyperliquid"
                and isinstance(provider, ConcurrentCancelProvider)
            )
            if len(async_candidates) != 1:
                raise BenchmarkFailure(
                    "provider set must contain one async-hyperliquid provider"
                )
            await run_cancel_id_suite(
                async_candidates[0],
                providers.recovery,
                providers.mid_source,
                pacer,
                config,
                recorder,
                clock_ns=clock_ns,
            )
        if args.command in ("providers", "all"):
            phase = "providers"
            await run_provider_suite(
                providers.measured,
                providers.recovery,
                providers.mid_source,
                pacer,
                config,
                recorder,
                clock_ns=clock_ns,
            )
    except Exception as error:
        failure_reason = _failure_reason(error, phase)
        if failure_reason == "order_cleanup_failed":
            cleanup_ok = False
    finally:
        if providers is not None:
            try:
                await providers.close()
            except Exception:
                cleanup_ok = False
                failure_reason = (
                    "client_cleanup_failed"
                    if failure_reason is None
                    else "multiple_failures"
                )

    completed_at = _utc_now()
    valid = failure_reason is None and cleanup_ok
    report = recorder.build_report(
        valid=valid,
        failure_reason=failure_reason,
        cleanup_ok=cleanup_ok,
        started_at=started_at,
        completed_at=completed_at,
    )
    forbidden_values = _secret_values(environ)
    if valid:
        try:
            write_csv(report, output_dir)
            write_figures(report, output_dir)
        except Exception:
            valid = False
            report = recorder.build_report(
                valid=False,
                failure_reason="artifact_generation_failed",
                cleanup_ok=cleanup_ok,
                started_at=started_at,
                completed_at=completed_at,
            )
    report_path = write_report(report, output_dir, forbidden_values=forbidden_values)
    return LiveRunOutcome(report_path=report_path, valid=valid)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.command == "publish":
            destination = publish_report(args.report, args.repository_root)
            print(destination)
            return 0

        from dotenv import load_dotenv

        load_dotenv(Path(".env.local"), override=False)
        outcome = asyncio.run(run_live(args, environ=os.environ))
        print(outcome.report_path)
        return 0 if outcome.valid else 1
    except BenchmarkFailure as error:
        print(f"live benchmark failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
