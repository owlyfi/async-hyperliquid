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


def _called_info_coroutines(paths: tuple[str, ...]) -> set[str]:
    return {
        node.value.func.attr
        for tree in _trees(paths)
        for node in ast.walk(tree)
        if isinstance(node, ast.Await)
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Attribute)
        and isinstance(node.value.func.value, ast.Name)
        and node.value.func.value.id == "info"
    }


def _test_names(paths: tuple[str, ...]) -> set[str]:
    return {
        node.name
        for tree in _trees(paths)
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef)
        and node.name.startswith("test_")
    }


def test_info_calls_require_awaited_info_receiver(tmp_path: Path) -> None:
    source = tmp_path / "info_calls.py"
    source.write_text(
        """
async def scenario(info, fake):
    await info.all_mids()
    info.user_role()
    await fake.user_role()
"""
    )

    assert _called_info_coroutines((str(source),)) == {"all_mids"}


def test_info_public_coroutines_have_unit_and_integration_coverage() -> None:
    methods = _public_coroutines(InfoClient)
    deterministic = _called_methods(
        ("tests/unit/test_info.py", "tests/unit/test_metadata.py")
    )
    integration = _called_info_coroutines(("tests/integration/test_info.py",))

    assert methods <= deterministic
    assert methods <= integration


def test_info_integration_names_are_concise() -> None:
    names = _test_names(("tests/integration/test_info.py",))
    assert {name for name in names if name.count("_") > 4} == set()


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
