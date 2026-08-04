import ast
import inspect
from pathlib import Path

from async_hyperliquid import AsyncHyperliquid, InfoClient
from async_hyperliquid.exchange import ExchangeClient


ROOT = Path(__file__).parents[2]
LIFECYCLE = {"open", "close"}


def _public_coroutines(owner: type[object]) -> set[str]:
    return {
        name
        for name, value in inspect.getmembers(owner, inspect.iscoroutinefunction)
        if not name.startswith("_") and name not in LIFECYCLE
    }


def _trees(paths: tuple[str, ...]) -> tuple[ast.AST, ...]:
    return tuple(ast.parse((ROOT / path).read_text()) for path in paths)


def _called_methods(paths: tuple[str, ...]) -> set[str]:
    return {
        node.func.attr
        for tree in _trees(paths)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }


def _test_names(paths: tuple[str, ...]) -> set[str]:
    return {
        node.name
        for tree in _trees(paths)
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef)
        and node.name.startswith("test_")
    }


def test_info_public_coroutines_have_unit_and_integration_coverage() -> None:
    methods = _public_coroutines(InfoClient)
    deterministic = _called_methods(
        ("tests/unit/test_info.py", "tests/unit/test_metadata.py")
    )
    integration = _test_names(("tests/integration/test_info.py",))

    assert methods <= deterministic
    assert {f"test_{method}" for method in methods} <= integration


def test_exchange_public_coroutines_have_unit_and_integration_coverage() -> None:
    methods = _public_coroutines(ExchangeClient)
    deterministic = _called_methods(
        ("tests/unit/test_exchange.py", "tests/unit/test_actions.py")
    )
    integration = _test_names(
        (
            "tests/integration/exchange/test_orders.py",
            "tests/integration/exchange/test_actions.py",
        )
    )

    assert methods <= deterministic
    assert {f"test_{method}" for method in methods} <= integration


def test_root_workflows_keep_unit_and_integration_scenarios() -> None:
    workflows = _public_coroutines(AsyncHyperliquid) - LIFECYCLE
    deterministic = _called_methods(
        (
            "tests/unit/test_orders.py",
            "tests/unit/test_positions.py",
            "tests/unit/test_exchange.py",
        )
    )
    integration = _called_methods(
        (
            "tests/integration/exchange/test_orders.py",
            "tests/integration/exchange/test_actions.py",
        )
    )

    assert workflows <= deterministic
    assert workflows <= integration
    assert AsyncHyperliquid.batch_place_orders is AsyncHyperliquid.place_orders
