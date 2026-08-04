import ast
from pathlib import Path


TYPES_ROOT = Path(__file__).parents[3] / "src" / "async_hyperliquid" / "types"


def test_v1_type_modules_do_not_expose_any_or_naked_containers() -> None:
    violations: list[str] = []
    for path in TYPES_ROOT.glob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id == "Any":
                violations.append(f"{path.name}:{node.lineno}: Any")
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
                    "tuple",
                    "set",
                }:
                    violations.append(
                        f"{path.name}:{annotation.lineno}: naked {annotation.id}"
                    )

    assert violations == []
