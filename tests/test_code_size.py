"""Modules, classes and functions stay small enough to read (D70, docs/CODE_QUALITY.md).

Over the limit is only what OVER_LIMIT lists, and it may not grow: a change that needs
more room splits the code first. An entry back within the limit must leave the list.

`uv run python tests/test_code_size.py` prints the largest pieces of code for a review.
"""

import ast
import sys
from collections.abc import Iterator
from pathlib import Path

SRC = Path(__file__).parent.parent / "src" / "modern_gl"
LIMITS = {"module": 600, "class": 500, "function": 80}  # lines, docstrings included
SKIP = {"i18n_az.py"}  # translations: data, not code

# Code over the limit today and its size: the debt to pay off (STATUS, «Архитектурный
# аудит», п. 7). Lower a number when the code shrinks; never raise it.
OVER_LIMIT = {
    "application/bank.py::bank_places": 92,
    "application/bank.py::statement": 92,
    "application/catalog.py::Catalog.reload": 83,
    "application/eqaime_import.py": 641,
    "application/inventory/drafts.py::DraftCommands._insert_line": 86,
    "application/inventory/movements.py::MovementCommands._apply_line": 96,
    "application/ledger/chart.py::ChartCommands.add_account": 98,
    "application/ledger/chart.py::ChartCommands.update_account": 101,
    "application/ledger/conversion.py::ConversionCommands._conversion_postings": 115,
    "application/ledger/validation.py::PostingChecks._validate_for_posting": 92,
    "application/quick_entry.py": 602,
    "demo_data.py::create_demo_company": 124,
    "desktop/account_dialog.py::AccountDialog.__init__": 123,
    "desktop/currencies_page.py::CurrenciesPage.__init__": 87,
    "desktop/inventory_page.py::InventoryPage.__init__": 93,
    "desktop/inventory_page.py::InventoryPage.refresh": 88,
    "desktop/opening_balances_page.py::OpeningBalancesPage.__init__": 127,
    "desktop/reports_page/view.py": 651,
    "desktop/reports_page/view.py::ReportPage.__init__": 87,
    "desktop/templates_page.py::TemplatePage.__init__": 98,
    "desktop/theme.py::stylesheet": 186,
    "reporting/reports.py::trial_balance": 103,
    "reporting/reports.py::account_card": 83,
}


def sizes() -> Iterator[tuple[str, str, int]]:
    """(kind, name, lines) of every module, class and function; a name is
    "path" for a module and "path::Class.method" for the code in it."""
    for path in sorted(SRC.rglob("*.py")):
        rel = path.relative_to(SRC).as_posix()
        if rel in SKIP:
            continue
        text = path.read_text(encoding="utf-8")
        yield "module", rel, len(text.splitlines())
        yield from _definitions(ast.parse(text), f"{rel}::")


def _definitions(tree: ast.AST, prefix: str) -> Iterator[tuple[str, str, int]]:
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            kind = "class" if isinstance(node, ast.ClassDef) else "function"
            name = prefix + node.name
            yield kind, name, (node.end_lineno or node.lineno) - node.lineno + 1
            yield from _definitions(node, name + ".")


def test_code_stays_within_limits() -> None:
    problems = []
    for kind, name, lines in sizes():
        allowed = OVER_LIMIT.get(name, LIMITS[kind])
        if lines > allowed:
            problems.append(
                f"{name}: {lines} lines, allowed {allowed} — split it (docs/CODE_QUALITY.md)"
            )
    assert not problems, "\n".join(problems)


def test_over_limit_list_is_current() -> None:
    """An entry for code that is gone or back within the limit leaves the list."""
    found = {name: (kind, lines) for kind, name, lines in sizes()}
    stale = [
        name for name in OVER_LIMIT if name not in found or found[name][1] <= LIMITS[found[name][0]]
    ]
    assert not stale, f"remove from OVER_LIMIT: {stale}"


if __name__ == "__main__":
    top = int(sys.argv[1]) if len(sys.argv) > 1 else 25
    rows = sorted(sizes(), key=lambda row: row[2] / LIMITS[row[0]], reverse=True)
    for kind, name, lines in rows[:top]:
        mark = "!" if lines > LIMITS[kind] else " "
        print(f"{mark} {lines:5} / {LIMITS[kind]:<4} {kind:8} {name}")
