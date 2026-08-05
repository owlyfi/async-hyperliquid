from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).parents[2]


def _collect(path: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", path],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def test_exchange_tests_are_collected_by_default() -> None:
    result = _collect("tests/integration/exchange")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "test_place_limit_order" in result.stdout
    assert "test_routes_orders_to_expected_owner" in result.stdout


def test_info_tests_collect_both_networks() -> None:
    result = _collect("tests/integration/test_info.py")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "test_all_mids[mainnet]" in result.stdout
    assert "test_all_mids[testnet]" in result.stdout


def test_mainnet_info_collects_once() -> None:
    result = _collect("tests/integration/test_info.py")
    output = result.stdout

    assert result.returncode == 0, result.stdout + result.stderr
    assert "test_mainnet_spot_mapping[mainnet-" in output
    assert "test_mainnet_spot_mapping[testnet-" not in output
    assert "test_mainnet_metadata_mapping[mainnet-" in output
    assert "test_mainnet_metadata_mapping[testnet-" not in output
    assert "test_hype_price_parity[mainnet]" in output
    assert "test_hype_price_parity[testnet]" not in output
    assert "test_mainnet_quote_tokens[mainnet]" in output
    assert "test_mainnet_quote_tokens[testnet]" not in output
    assert "test_token_details[mainnet]" in output
    assert "test_token_details[testnet]" not in output
    assert "test_mainnet_size_decimals[mainnet-BTC-5]" in output
    assert "test_mainnet_size_decimals[testnet-" not in output
    assert "test_mainnet_metadata_mapping[mainnet-UBTC/USDC-10142]" in output
    assert "test_mainnet_metadata_mapping[mainnet-xyz:GOLD-110003]" in output
    assert "test_mainnet_metadata_mapping[mainnet-xyz:SILVER-110026]" in output
    assert "test_perp_network_prices" in output
    assert "test_mainnet_price_parity[mainnet-BTC-BTC/USDC]" in output
    assert "test_mainnet_price_parity[testnet-" not in output
    assert "test_mainnet_stablecoin_prices[mainnet-USDH/USDC]" in output
    assert "test_mainnet_stablecoin_prices[mainnet-USDE/USDC]" in output
    assert "test_mainnet_stablecoin_prices[testnet-" not in output
    assert "test_aligned_quote_token_info" not in output
    assert "legacy_coin_aliases" not in output
    assert "legacy_unsupported_aliases" not in output
