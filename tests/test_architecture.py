"""Code rules of docs/ENGINEERING.md (D71): the core knows nothing of modules, layers stay
apart; code size is test_code_size.py (D70). Each allowance below is a debt listed there;
when the debt is paid, the test asks to remove the allowance."""

import ast
import re
from pathlib import Path

import pytest

SRC = Path(__file__).parent.parent / "src" / "modern_gl"

CORE = [
    *(
        SRC / "application" / "ledger" / f"{name}.py"
        for name in (
            "base",
            "inputs",
            "companies",
            "currencies",
            "chart",
            "subconto",
            "documents",
            "validation",
            "document_import",
            "revaluation",
            "opening",
            "templates",
        )
    ),
    SRC / "reporting" / "reports.py",
    SRC / "reporting" / "report_common.py",
    SRC / "reporting" / "plaintext.py",
    SRC / "reporting" / "handover.py",
    SRC / "reporting" / "overview.py",
    *(SRC / "domain").glob("*.py"),
]

MODULE_TABLE = re.compile(
    r"\b(inventory_\w+|landed_cost_\w+|stock_\w+|warehouses|bank_operation\w*|bank_statements|"
    r"bank_account_details|"
    r"currency_conversions|conversion_fees|eqaime_\w+)\b"
)
MODULE_CODE = (
    "modern_gl.application.inventory",
    "modern_gl.application.bank",
    "modern_gl.application.conversions",
    "modern_gl.application.eqaime_import",
    "modern_gl.application.eqaime_portal",
    "modern_gl.application.quick_entry",
    "modern_gl.application.trade_batch",
    "modern_gl.reporting.inventory",
    "modern_gl.reporting.trade",
    "modern_gl.reporting.eqaime_reconciliation",
)

# The core never reads a module's table (debt 1 paid in session 25: the document_owners
# view tells it who owns a GL document); a new reading is not allowed.
CORE_TABLE_ALLOWED: dict[str, set[str]] = {}
# A widget never runs its own query (debt 3 paid in session 22); a new one is not allowed.
SQL_IN_WIDGETS_ALLOWED: set[str] = set()


def rel(path: Path) -> str:
    return path.relative_to(SRC).as_posix()


def imports(path: Path) -> set[str]:
    found = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
    return found


def files(*parts: str) -> list[Path]:
    return sorted(SRC.joinpath(*parts).rglob("*.py"))


@pytest.mark.parametrize("path", CORE, ids=rel)
def test_core_does_not_read_module_tables(path):
    tables = set(MODULE_TABLE.findall(path.read_text(encoding="utf-8")))
    allowed = CORE_TABLE_ALLOWED.get(rel(path), set())
    assert tables <= allowed, (
        f"ядро {rel(path)} читает таблицы модулей {sorted(tables - allowed)} "
        "— см. docs/ENGINEERING.md"
    )
    assert allowed <= tables, (
        f"долг в {rel(path)} погашен: уберите {sorted(allowed - tables)} из CORE_TABLE_ALLOWED"
    )


@pytest.mark.parametrize("path", CORE, ids=rel)
def test_core_does_not_import_modules(path):
    bad = {m for m in imports(path) if m.startswith(MODULE_CODE)}
    assert not bad, f"ядро {rel(path)} импортирует модули {sorted(bad)}"


@pytest.mark.parametrize(
    "layer", ["domain", "application", "reporting", "infrastructure", "assistant"]
)
def test_no_qt_outside_desktop(layer):
    bad = [
        rel(p)
        for p in files(layer)
        if any(m.startswith(("PySide6", "modern_gl.desktop")) for m in imports(p))
    ]
    assert not bad, f"Qt вне desktop: {bad}"


def test_domain_has_no_sql_or_other_layers():
    outer = ("sqlite3", "modern_gl.application", "modern_gl.reporting", "modern_gl.infrastructure")
    bad = [rel(p) for p in files("domain") if any(m.startswith(outer) for m in imports(p))]
    assert not bad, f"domain зависит от SQL или внешних слоёв: {bad}"


def test_no_sql_in_widgets():
    with_sql = {rel(p) for p in files("desktop") if ".execute(" in p.read_text(encoding="utf-8")}
    assert with_sql <= SQL_IN_WIDGETS_ALLOWED, (
        f"SQL в виджетах: {sorted(with_sql - SQL_IN_WIDGETS_ALLOWED)} — "
        "перенесите запрос в queries / catalog / reporting"
    )
    paid = SQL_IN_WIDGETS_ALLOWED - with_sql
    assert not paid, f"долг погашен: уберите {sorted(paid)} из SQL_IN_WIDGETS_ALLOWED"


# The database engine is known only to infrastructure (D77): elsewhere the SQL is the common
# part of SQLite and PostgreSQL, so the move to a server changes one package, not the queries.
SQLITE_ONLY = re.compile(
    r"\b(GROUP_CONCAT|INSERT\s+OR|REPLACE\s+INTO|PRAGMA|sqlite_master|rowid|lastrowid|"
    r"executescript|iif|instr|ifnull|julianday|typeof|total_changes)\b|"
    r"COLLATE\s+NOCASE|\b(date|datetime|strftime)\('",
    re.IGNORECASE,
)


@pytest.mark.parametrize("layer", ["domain", "application", "reporting", "desktop", "assistant"])
def test_database_engine_only_in_infrastructure(layer):
    bad = {}
    for path in files(layer):
        found = {m.group(0) for m in SQLITE_ONLY.finditer(path.read_text(encoding="utf-8"))}
        if "sqlite3" in imports(path):
            found.add("import sqlite3")
        if found:
            bad[rel(path)] = sorted(found)
    assert not bad, (
        f"только в SQLite: {bad} — типы и ошибки берите из infrastructure.db, "
        "справочные запросы о схеме — оттуда же; SQL — общий для SQLite и PostgreSQL "
        "(string_agg, ON CONFLICT, COALESCE) — docs/ENGINEERING.md, п. 3.9"
    )


def test_sqlite_knows_the_common_sql():
    # string_agg is in SQLite since 3.44 (the Python of uv brings a newer one)
    import sqlite3

    assert sqlite3.sqlite_version_info >= (3, 44), sqlite3.sqlite_version


def test_windows_open_no_transaction():
    """A scenario is one method of Ledger / Inventory with its own transaction (debt 10,
    paid in session 38): a window never decides where a scenario begins and ends."""
    bad = []
    for path in files("desktop"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            db = isinstance(node, ast.ImportFrom) and node.module == "modern_gl.infrastructure.db"
            if db and any(alias.name == "transaction" for alias in node.names):  # type: ignore[union-attr]
                bad.append(rel(path))
    assert not bad, f"окно открывает транзакцию: {bad} — один метод Ledger на сценарий"


def test_ledger_is_the_core_and_modules_are_objects_of_their_own():
    """Debt 2 (paid in session 38): the bank, conversion and e-qaimə are not mixed into
    Ledger; they are its objects over the same connection — the core knows none of them."""
    from modern_gl.application.ledger import BankModule, ConversionModule, EqaimeModule, Ledger
    from modern_gl.infrastructure.db import connect

    module_groups = {
        cls
        for module in (BankModule, ConversionModule, EqaimeModule)
        for cls in module.__mro__
        if cls.__module__.rsplit(".", 1)[-1] in {"bank", "bank_statements", "conversion", "eqaime"}
    }
    assert not module_groups & set(Ledger.__mro__)
    ledger = Ledger(connect(":memory:"), actor="Aynur")
    assert ledger.bank.conn is ledger.conn and ledger.bank.actor == "Aynur"
    assert ledger.bank is ledger.bank  # one object per ledger
