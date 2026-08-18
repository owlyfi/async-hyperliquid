import ast
from pathlib import Path
import textwrap


ROOT = Path(__file__).resolve().parents[2]
SIGNED_EXAMPLE_METHODS = {
    "agent_send_asset",
    "cancel_twap",
    "hip3_liquidator_transfer",
    "place_orders",
    "place_trigger_order",
    "place_twap",
    "send_asset",
    "send_to_evm_with_data",
    "spot_transfer",
    "staking_deposit",
    "staking_withdraw",
    "token_delegate",
    "usd_class_transfer",
    "usd_transfer",
    "vault_transfer",
    "withdraw",
}


def _python_blocks(path: Path) -> list[str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    blocks = []
    line_index = 0
    while line_index < len(lines):
        if lines[line_index].strip() != ".. code-block:: python":
            line_index += 1
            continue

        line_index += 1
        while line_index < len(lines) and not lines[line_index].strip():
            line_index += 1
        block = []
        while line_index < len(lines):
            line = lines[line_index]
            if line and not line.startswith("   "):
                break
            block.append(line[3:] if line else "")
            line_index += 1
        blocks.append("\n".join(block).rstrip())
    return blocks


def _example_tree(block: str) -> ast.Module:
    wrapped = "async def example():\n" + textwrap.indent(block, "    ")
    return ast.parse(wrapped)


def _called_method(call: ast.Call) -> str | None:
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    return None


def _signed_assignments(block: str) -> list[tuple[str, str]]:
    assignments = []
    for node in ast.walk(_example_tree(block)):
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        value = node.value
        if not isinstance(value, ast.Await) or not isinstance(value.value, ast.Call):
            continue
        method = _called_method(value.value)
        target = node.targets[0]
        if method in SIGNED_EXAMPLE_METHODS and isinstance(target, ast.Name):
            assignments.append((target.id, method))
    return assignments


def _checked_response_names(block: str) -> set[str]:
    checked = set()
    for node in ast.walk(_example_tree(block)):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
            continue
        if not node.func.id.startswith("require_"):
            continue
        checked.update(arg.id for arg in node.args if isinstance(arg, ast.Name))
    return checked


def test_python_examples_are_valid_inside_an_async_main() -> None:
    for path in sorted((ROOT / "docs").rglob("*.rst")):
        for block in _python_blocks(path):
            _example_tree(block)


def test_each_copyable_twap_example_submits_at_most_one_twap() -> None:
    blocks = _python_blocks(ROOT / "docs/howto/orders.rst")

    for block in blocks:
        place_twap_calls = [
            node
            for node in ast.walk(_example_tree(block))
            if isinstance(node, ast.Call) and _called_method(node) == "place_twap"
        ]
        assert len(place_twap_calls) <= 1, (
            "one copied Python block must not submit multiple real TWAPs"
        )


def test_signed_action_examples_check_returned_status() -> None:
    for relative in (
        "docs/howto/orders.rst",
        "docs/howto/transfers-administration.rst",
    ):
        for block in _python_blocks(ROOT / relative):
            assignments = _signed_assignments(block)
            checked_names = _checked_response_names(block)
            unchecked = [
                f"{name} ({method})"
                for name, method in assignments
                if name not in checked_names
            ]
            assert not unchecked, (
                f"{relative} leaves signed responses unchecked: {', '.join(unchecked)}"
            )


def test_short_tpsl_execution_prices_cross_above_the_trigger() -> None:
    assignments = {}
    for block in _python_blocks(ROOT / "docs/howto/orders.rst"):
        for node in ast.walk(_example_tree(block)):
            if isinstance(node, ast.Assign) and len(node.targets) == 1:
                target = node.targets[0]
                if isinstance(target, ast.Name) and target.id.startswith("short_"):
                    assignments[target.id] = node.value

    values: dict[str, float] = {"mark_px": 100.0}
    for name in (
        "short_take_trigger_px",
        "short_stop_trigger_px",
        "short_take_execution_px",
        "short_stop_execution_px",
    ):
        assert name in assignments, f"missing documented short TP/SL value: {name}"
        values[name] = eval(  # noqa: S307 - evaluating repository-owned arithmetic AST
            compile(ast.Expression(assignments[name]), "<docs-example>", "eval"),
            {"__builtins__": {}, "float": float},
            values,
        )

    assert values["short_take_execution_px"] > values["short_take_trigger_px"]
    assert values["short_stop_execution_px"] > values["short_stop_trigger_px"]
    assert values["short_take_trigger_px"] < values["mark_px"]
    assert values["short_stop_trigger_px"] > values["mark_px"]
