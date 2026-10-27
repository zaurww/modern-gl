"""A test module imports what it shares with others from tests/helpers/, never from
another test module (that ran the other module's import and needed `# noqa: F811` for the
fixtures it brought along)."""

import ast
from pathlib import Path

TESTS = Path(__file__).parent


def test_no_test_module_imports_another():
    found = [
        f"{path.relative_to(TESTS)}:{node.lineno} {node.module}"
        for path in TESTS.rglob("*.py")
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("tests.test_")
    ]
    assert found == []
