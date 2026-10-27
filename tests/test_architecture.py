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
    *(SRC / "reporting" / "reports").glob("*.py"),
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
    "modern_gl.application.conversion",
    "modern_gl.application.eqaime",
    "modern_gl.application.eqaime.portal",
    "modern_gl.application.quick_entry",
    "modern_gl.application.trade_batch",
    "modern_gl.application.vat",
    "modern_gl.reporting.inventory",
    "modern_gl.reporting.trade",
    "modern_gl.reporting.eqaime_reconciliation",
    "modern_gl.reporting.vat",
    "modern_gl.reporting.vat_liability",
    "modern_gl.reporting.vat_payments",
    "modern_gl.reporting.vat_receipts",
    "modern_gl.reporting.vat_register",
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
    r"COLLATE\s+NOCASE|\b(date|datetime|strftime)\('|"
    r"\bIS\s+NOT\s+\?",  # PostgreSQL: IS DISTINCT FROM ?
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
    """Debt 2 (paid in session 38; D123): the bank, conversion and e-qaimə are not mixed
    into Ledger; each is an object of its own package over the same connection — the core
    knows none of them, and asks for a module only when its handle is used."""
    from modern_gl.application.bank import BankModule
    from modern_gl.application.conversion import ConversionModule
    from modern_gl.application.eqaime import EqaimeModule
    from modern_gl.application.ledger import Ledger
    from modern_gl.infrastructure.db import connect

    packages = (
        "modern_gl.application.bank",
        "modern_gl.application.conversion",
        "modern_gl.application.eqaime",
    )
    module_groups = {
        cls
        for module in (BankModule, ConversionModule, EqaimeModule)
        for cls in module.__mro__
        if cls.__module__.startswith(packages)
    }
    assert module_groups and not module_groups & set(Ledger.__mro__)
    core_init = SRC / "application" / "ledger" / "__init__.py"
    tree = ast.parse(core_init.read_text(encoding="utf-8"))
    top = {n.module for n in tree.body if isinstance(n, ast.ImportFrom) and n.module}
    assert not {m for m in top if m.startswith(packages)}, "Ledger импортирует модуль при загрузке"
    ledger = Ledger(connect(":memory:"), actor="Aynur")
    assert ledger.bank.conn is ledger.conn and ledger.bank.actor == "Aynur"
    assert ledger.bank is ledger.bank  # one object per ledger


def test_a_module_calls_the_core_and_is_not_the_core():
    """D162: a module's write object holds the ledger (`self.ledger`) and calls it; it
    inherits none of the core's scenarios (`ledger.bank.add_account` is no call), and it
    reaches the ledger's internals only through `ledger/module.py`."""
    from modern_gl.application.bank import BankModule
    from modern_gl.application.conversion import ConversionModule
    from modern_gl.application.eqaime import EqaimeModule
    from modern_gl.application.inventory import Inventory
    from modern_gl.application.ledger import Ledger
    from modern_gl.infrastructure.db import connect

    core = {name for name in dir(Ledger) if not name.startswith("_")}
    for module in (BankModule, ConversionModule, EqaimeModule, Inventory):
        public = {name for name in dir(module) if not name.startswith("_")}
        shared = {
            name
            for name in public & core
            if getattr(module, name) is getattr(Ledger, name)  # the same function
        }
        assert not shared, f"{module.__name__} наследует ядро: {sorted(shared)}"
        assert not any(cls is Ledger for cls in module.__mro__)
    ledger = Ledger(connect(":memory:"))
    assert ledger.bank.ledger is ledger and ledger.conversion.ledger is ledger
    assert Inventory(ledger.conn, ledger.actor).ledger is not ledger  # its own, the same base
    bad = [
        rel(path)
        for path in files()
        if "/application/" in path.as_posix()
        and "/application/ledger/" not in path.as_posix()
        and ("ledger._" in path.read_text(encoding="utf-8"))
    ]
    assert not bad, f"модуль лезет внутрь Ledger: {bad} — только через ledger/module.py"


def test_the_counterparty_of_a_line_has_one_rule():
    """Who the counterparty of a purchase or sale line is — the view
    inventory_line_counterparties (migration 0045, debt 12): no query picks it out of
    offset_sc1..3 by itself, with its own rule."""
    bad = [
        rel(path)
        for path in files()
        if "offset_sc" in (text := path.read_text(encoding="utf-8")) and "'counterparty'" in text
    ]
    assert not bad, f"контрагент строки выбирается вручную: {bad} — inventory_line_counterparties"


# The layers and their order (docs/ARCHITECTURE.md, § 1; D122): a layer imports only itself
# and the layers below it. `i18n` is the bottom (texts), `domain` knows no SQL, `infrastructure`
# is the engine and the files, `application` the scenarios and the shared reading,
# `reporting` the reports over them; the top is everything that shows or serves.
LAYERS: list[tuple[str, ...]] = [
    ("i18n", "i18n_az"),
    ("domain",),
    ("infrastructure",),
    ("application",),
    ("reporting",),
    ("desktop", "assistant", "api", "demo_data", "demo_year"),
]


def _layer_of(module: str) -> int | None:
    name = module.removeprefix("modern_gl.").split(".")[0]
    for level, names in enumerate(LAYERS):
        if name in names:
            return level
    return None


def _layer_files(names: tuple[str, ...]) -> list[Path]:
    found = []
    for name in names:
        found += files(name) if (SRC / name).is_dir() else [SRC / f"{name}.py"]
    return sorted(found)


@pytest.mark.parametrize("level", range(len(LAYERS)), ids=lambda i: "+".join(LAYERS[i]))
def test_layers_depend_downwards_only(level):
    bad = {}
    for path in _layer_files(LAYERS[level]):
        above = sorted(
            m for m in imports(path) if m.startswith("modern_gl") and (_layer_of(m) or 0) > level
        )
        if above:
            bad[rel(path)] = above
    assert not bad, (
        f"слой {'+'.join(LAYERS[level])} импортирует слои выше себя: {bad} — "
        "зависимости только сверху вниз (docs/ARCHITECTURE.md, § 1)"
    )


def test_every_package_has_a_layer():
    """A new top-level package or module takes its place in LAYERS first."""
    names = {p.stem if p.is_file() else p.name for p in SRC.iterdir() if not p.name.startswith("_")}
    known = {name for names in LAYERS for name in names}
    assert names - known == set(), f"не в LAYERS: {sorted(names - known)}"


# SQL is built only from identifiers the code itself names; values go as `?` parameters.
# Ruff's S608 cannot tell the two apart and is off (pyproject.toml); this guards the direct
# way text could reach SQL: a str (or unannotated) parameter put into an SQL f-string.
# A parameter that only ever carries an identifier is listed here with whom it comes from.
SQL_WORDS = re.compile(r"\b(SELECT|INSERT|UPDATE|DELETE|WHERE)\b")
IDENTIFIER_PARAMS: dict[tuple[str, str, str], str] = {
    ("application/books.py", "docs_cte", "columns"): "columns of the CTE, from the callers",
    ("application/books.py", "docs_cte", "status"): "a quoted status constant",
    ("application/inventory/landed_cost.py", "allocated_sql", "company"): "a table alias",
    ("application/inventory/landed_cost.py", "allocated_sql", "document"): "a table alias",
    ("application/inventory/landed_cost.py", "allocated_sql", "line"): "a table alias",
    ("application/ledger/account_types.py", "_with_followers", "same"): "a column condition",
    ("application/ledger/module.py", "rebuild_each", "table"): "a module's table name",
    ("application/ledger/validation.py", "_rows_by_id", "table"): "a table name constant",
}


def _text_params(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    """Parameters that may carry text: annotated with str, or not annotated."""
    a = fn.args
    found = set()
    for arg in (*a.posonlyargs, *a.args, *a.kwonlyargs):
        note = ast.unparse(arg.annotation) if arg.annotation else ""
        if arg.arg not in ("self", "cls") and (not note or re.search(r"\bstr\b", note)):
            found.add(arg.arg)
    return found


def _params_in_sql(path: Path) -> set[tuple[str, str, str]]:
    found = set()
    for fn in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        params = _text_params(fn)
        for node in ast.walk(fn):
            if not isinstance(node, ast.JoinedStr):
                continue
            text = "".join(str(v.value) for v in node.values if isinstance(v, ast.Constant))
            if not SQL_WORDS.search(text):
                continue
            for value in node.values:
                if isinstance(value, ast.FormattedValue):
                    names = {n.id for n in ast.walk(value.value) if isinstance(n, ast.Name)}
                    found |= {(rel(path), fn.name, p) for p in names & params}
    return found


def test_sql_takes_values_as_parameters_not_text():
    found = set().union(*(_params_in_sql(p) for p in files()))
    new = found - IDENTIFIER_PARAMS.keys()
    assert not new, (
        f"текстовый параметр функции вставлен в SQL: {sorted(new)} — значение передайте "
        "параметром `?`; если это имя столбца или таблицы из кода — внесите в IDENTIFIER_PARAMS"
    )
    gone = IDENTIFIER_PARAMS.keys() - found
    assert not gone, f"уберите из IDENTIFIER_PARAMS: {sorted(gone)}"


# Every UPDATE and DELETE names its company in WHERE (D176): the way SAP adds the client to
# every statement, so a row of another company is never touched by an id alone — the guard
# for the day several companies share one server database (D24, D77). In `companies` the
# row's own id is the company.
WRITE_SQL = re.compile(r"^\s*(?:UPDATE|DELETE\s+FROM)\s+(\w+|\{[^}]*\})", re.IGNORECASE)


def _sql_text(node: ast.expr) -> str | None:
    """The SQL of a literal (adjacent literals are one) or an f-string, `{}` for a value."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(str(v.value) if isinstance(v, ast.Constant) else "{}" for v in node.values)
    return None


def _writes_without_company(path: Path) -> list[str]:
    found = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in ("execute", "executemany")
            and node.args
        ):
            continue
        text = _sql_text(node.args[0])
        match = WRITE_SQL.match(text or "")
        if text is None or match is None or match.group(1) == "companies":
            continue
        parts = re.split(r"\bWHERE\b", text, maxsplit=1, flags=re.IGNORECASE)
        if len(parts) < 2 or "company_id" not in parts[1]:
            found.append(f"{rel(path)}:{node.lineno} {match.group(1)}")
    return found


def test_every_write_names_its_company():
    found = [w for p in files() for w in _writes_without_company(p)]
    assert not found, f"UPDATE/DELETE без company_id в WHERE: {found}"
