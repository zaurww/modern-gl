"""Database rules of docs/ENGINEERING.md (D72): every table belongs to a company, references
stay inside the company, money is never REAL, migrations are frozen, new tables index their
references. Allowances are the debt listed there; a paid debt must leave the list."""

import hashlib
import re
import sqlite3

import pytest

from modern_gl.demo_data import create_demo_company
from modern_gl.infrastructure.db import (
    APPLICATION_ID,
    MIGRATIONS_DIR,
    BusyError,
    close,
    connect,
    open_snapshot,
    transaction,
)

# A migration is never edited once written (CLAUDE.md); a new one is added here with its hash.
FROZEN = {
    "0001_initial.sql": "773fd87b67c2391e",
    "0002_account_class.sql": "53f82d1fc1d53dbb",
    "0003_two_sided_instead_of_kind.sql": "748e6c1d254a44f7",
    "0004_unpost_and_numbering.sql": "ded6a7a9dc47ebf6",
    "0005_optional_account_code.sql": "0d06f768ae2df1f6",
    "0006_entry_templates.sql": "5bb5466d36c7643f",
    "0007_inventory.sql": "aee94863f5bf8c30",
    "0008_currencies.sql": "0043b6a5f5dda80a",
    "0009_contract_owner_mixed_currency.sql": "cbb199f1324dfcd0",
    "0010_account_roles_receipt_vat.sql": "f34f28f498eed3bd",
    "0011_landed_cost_charges.sql": "8a8f38562eaa14e9",
    "0012_account_type.sql": "412123518a4ddd64",
    "0013_inventory_currency.sql": "2b4eeb47d65120f0",
    "0014_counterparty_tax_id.sql": "4c68c12d06d31810",
    "0015_posting_invoice.sql": "65b98272660dbd09",
    "0016_receipt_invoice.sql": "b6a2e14cb750d494",
    "0017_opening_balances.sql": "ceb74dc377630317",
    "0018_currency_conversions.sql": "76f90ef359cc1098",
    "0019_transit_type.sql": "813dbecc41de77bd",
    "0020_conversion_fees.sql": "975a6d4a0164128c",
    "0021_vat_deposit_type.sql": "175646ed9ccd1b1c",
    "0022_sales.sql": "4d77082df18fbc9d",
    "0023_receipt_expense_lines.sql": "c28e59e19fd70e59",
    "0024_counterparty_legal_name.sql": "5a6f9fe06e463229",
    "0025_bank_operations.sql": "c0290e2d9f18dfa4",
    "0026_eqaime_portal.sql": "514114b1f1ad6a68",
    "0027_subconto_groups.sql": "4b02c305ff5418da",
    "0028_account_optional_subconto.sql": "b804f22eb22c0d77",
    "0029_parallel_books.sql": "c2bbcaf3905d395c",
    "0030_tags.sql": "a897026dc663030d",
    "0031_receipt_expense_period.sql": "9fe806ded219f5fb",
    "0032_document_owners.sql": "547973ab1e6eed4d",
    "0033_bank_statements.sql": "677ed451924b0b90",
    "0034_advance_roles.sql": "64ae2788859eb910",
    "0035_long_term_types.sql": "9af358600e337aea",
    "0036_company_mode.sql": "a9553da764433920",
    "0037_incoming.sql": "76850b60a80bfa56",
    "0038_owner_indexes.sql": "dd926587843c2ffe",
    "0039_lines_by_item.sql": "ec898b1c996643ed",
    "0040_company_tax_id.sql": "91d5adcf284ecf68",
    "0041_bank_portal_loads.sql": "1d265c1fa64e29f2",
    "0042_bank_portal_reconciled.sql": "4c717085ecd1097b",
    "0043_awaits_invoice.sql": "2297aebcf3e8dbb3",
    "0044_document_owner_ids.sql": "229ad0a9b7d6b115",
    "0045_line_counterparties.sql": "1aa158be48f2f26c",
    "0046_query_indexes.sql": "c9c524291c9fe367",
    "0047_company_scoped_references.sql": "86041a67459f7242",
    "0048_ifrs_types.sql": "6cfdde82474f65bf",
    "0049_document_sources.sql": "16358f1735946b2c",
    "0050_expense_per_line.sql": "7e6955a40daf47b5",
    "0051_reconciled_books.sql": "57e0bf8cfe5ecda6",
    "0052_vat_payer.sql": "3fd20def7c6eebfa",
    "0053_integrity_guards.sql": "cbe99972b6e18951",
    "0054_document_language.sql": "bf04a8471463d5ce",
    "0055_returns.sql": "0a1c590717ca2e89",
    "0056_item_minimum.sql": "5434a29414182511",
    "0057_value_checks.sql": "b9905e018735542d",
    "0058_audit_by_time.sql": "50d0c877d782adc0",
    "0059_bank_checked.sql": "2173242eb9d7ecf4",
    "0060_bank_note.sql": "4d398c9ed6e057c9",
    "0061_report_views.sql": "a477a8f7abf7ccf2",
    "0062_accrued_income.sql": "240527be33d912a7",
    "0063_kind_per_line.sql": "bada74f41e413a11",
    "0064_posting_quantity.sql": "082436d33cf4605b",
    "0065_bank_party.sql": "e3d9c55fa898e725",
    "0066_inventory_sale_accounts.sql": "887ecf356eec0ddb",
    "0067_charge_from_purchase_line.sql": "78c114f622b05d2c",
    "0068_document_kinds.sql": "2fa56e7c912632d9",
    "0069_cash_orders.sql": "52a0610a815a89e4",
    "0070_advance_reports.sql": "385d347eec8d5d6e",
}

# Tables of schema 0031; a table added later must index every reference (debt 5).
LEGACY_TABLES = {
    "account_roles",
    "accounts",
    "audit_events",
    "bank_operation_lines",
    "bank_operations",
    "companies",
    "conversion_fees",
    "currencies",
    "currency_conversions",
    "currency_rates",
    "documents",
    "entry_template_lines",
    "entry_templates",
    "eqaime_portal",
    "eqaime_portal_changes",
    "eqaime_reconciled",
    "inventory_documents",
    "inventory_items",
    "inventory_lines",
    "inventory_units",
    "landed_cost_charges",
    "landed_cost_expense_allocations",
    "landed_cost_shares",
    "landed_cost_types",
    "layers",
    "opening_balance_documents",
    "postings",
    "stock_consumptions",
    "stock_movements",
    "subconto_kinds",
    "subconto_value_tags",
    "subconto_values",
    "tags",
    "warehouses",
}
# Debt 4: references between a company's tables that do not carry company_id (paid in 0047).
SINGLE_COLUMN_ALLOWED: set[str] = set()
# A column that names another row but is not a reference: the audit log outlives what it
# records; the portal's own id of an e-qaimə and another program's id of an imported
# document are text; a VÖEN is a number of the state.
NOT_REFERENCES = {
    "audit_events.entity_id",
    "eqaime_portal.portal_id",
    "document_sources.external_id",
}
DATE_COLUMNS = re.compile(r"(_date|^date_from|^date_to|^closed_through)$")
DATE_CHECK = "GLOB '[0-9][0-9][0-9][0-9]-[0-1][0-9]-[0-3][0-9]'"
# A row that belongs to a parent (a line to its document) is found by the parent: indexed.
OWNER_COLUMNS = {"document_id", "operation_id", "conversion_id", "template_id", "line_id"}
# Debt 5: owner references without an index (paid in 0038; keep empty).
UNINDEXED_OWNER_ALLOWED: set[str] = set()


@pytest.fixture(scope="module")
def db():
    c = connect(":memory:")
    yield c
    c.close()


def tables(db: sqlite3.Connection) -> list[str]:
    return [
        r[0]
        for r in db.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
    ]


def references(db: sqlite3.Connection, table: str) -> list[tuple[str, tuple[str, ...]]]:
    """(parent table, child columns) of each foreign key."""
    groups: dict[int, list] = {}
    for fk in db.execute(f"PRAGMA foreign_key_list({table})"):
        groups.setdefault(fk[0], []).append(fk)
    return [
        (g[0][2], tuple(fk[3] for fk in sorted(g, key=lambda fk: fk[1]))) for g in groups.values()
    ]


def indexed(db: sqlite3.Connection, table: str, columns: tuple[str, ...]) -> bool:
    """An index (or the primary key) starts with these columns, company_id aside."""
    key = tuple(c for c in columns if c != "company_id")
    prefixes = [
        tuple(r[2] for r in db.execute(f"PRAGMA index_info('{i[1]}')"))
        for i in db.execute(f"PRAGMA index_list({table})")
    ]
    pk = [r for r in db.execute(f"PRAGMA table_info({table})") if r[5]]
    prefixes.append(tuple(r[1] for r in sorted(pk, key=lambda r: r[5])))
    return any(p[: len(columns)] == columns or p[: len(key)] == key for p in prefixes)


def test_migrations_are_numbered_without_gaps():
    numbers = sorted(int(p.name.split("_", 1)[0]) for p in MIGRATIONS_DIR.glob("*.sql"))
    assert numbers == list(range(1, len(numbers) + 1))


def test_migrations_are_frozen():
    found = {
        p.name: hashlib.sha256(p.read_bytes().replace(b"\r\n", b"\n")).hexdigest()[:16]
        for p in sorted(MIGRATIONS_DIR.glob("*.sql"))
    }
    changed = sorted(n for n in FROZEN if found.get(n) != FROZEN[n])
    assert not changed, f"старые миграции изменены: {changed} — схему меняет только новая"
    new = sorted(set(found) - set(FROZEN))
    assert not new, f"добавьте новые миграции в FROZEN: {[(n, found[n]) for n in new]}"


def test_every_table_belongs_to_a_company(db):
    for table in tables(db):
        if table in ("companies", "audit_events"):  # the audit log outlives what it records
            continue
        cols = {r[1]: r for r in db.execute(f"PRAGMA table_info({table})")}
        assert "company_id" in cols, f"{table}: нет company_id"
        rowid = cols["company_id"][5] and sum(1 for r in cols.values() if r[5]) == 1
        assert cols["company_id"][3] or rowid, f"{table}.company_id может быть NULL"


def test_references_stay_inside_the_company(db):
    single = set()
    for table in tables(db):
        for parent, columns in references(db, table):
            if parent != "companies" and "company_id" not in columns and table != "companies":
                single.add(f"{table}.{columns[0]}")
    assert single <= SINGLE_COLUMN_ALLOWED, (
        f"ссылка без company_id: {sorted(single - SINGLE_COLUMN_ALLOWED)} — "
        "нужен составной FK (company_id, id)"
    )
    paid = SINGLE_COLUMN_ALLOWED - single
    assert not paid, f"долг погашен: уберите {sorted(paid)} из SINGLE_COLUMN_ALLOWED"


def test_every_reference_column_is_a_foreign_key(db):
    """Debt 7 (paid in 0047): a column named like a reference (`*_id`, `sc1..3`, `*_sc1..3`)
    without a FOREIGN KEY — ALTER TABLE ADD COLUMN cannot add one, so a rebuild must."""
    missing = set()
    for table in tables(db):
        declared = {fk[3] for fk in db.execute(f"PRAGMA foreign_key_list({table})")}
        for r in db.execute(f"PRAGMA table_info({table})"):
            name = r[1]
            looks = name.endswith("_id") and name != "company_id" and not name.endswith("tax_id")
            looks = looks or re.fullmatch(r"(\w+_)?sc[1-3]", name) is not None
            if looks and name not in declared and f"{table}.{name}" not in NOT_REFERENCES:
                missing.add(f"{table}.{name}")
    assert not missing, f"ссылка без FOREIGN KEY: {sorted(missing)}"


def test_every_date_column_checks_its_format(db):
    """Debt 8 (paid in 0047): dates are TEXT compared as strings — one row in another
    format silently falls out of every period."""
    missing = set()
    for table in tables(db):
        sql = db.execute("SELECT sql FROM sqlite_master WHERE name = ?", (table,)).fetchone()[0]
        for r in db.execute(f"PRAGMA table_info({table})"):
            if DATE_COLUMNS.search(r[1]) and not re.search(
                re.escape(r[1]) + r"\s+TEXT[^,]*" + re.escape(DATE_CHECK), sql
            ):
                missing.add(f"{table}.{r[1]}")
    assert not missing, f"дата без CHECK формата: {sorted(missing)}"


def test_columns_are_typed_and_money_is_never_real(db):
    for table in tables(db):
        for r in db.execute(f"PRAGMA table_info({table})"):
            assert r[2], f"{table}.{r[1]}: тип не указан"
            assert r[2].upper() not in ("REAL", "FLOAT", "DOUBLE", "NUMERIC"), (
                f"{table}.{r[1]}: {r[2]} — деньги и количества только INTEGER"
            )


def test_references_are_indexed(db):
    missing = set()
    for table in tables(db):
        for _parent, columns in references(db, table):
            if columns == ("company_id",) or indexed(db, table, columns):
                continue
            name = f"{table}.{columns[-1]}"
            if table not in LEGACY_TABLES or columns[-1] in OWNER_COLUMNS:
                missing.add(name)
    assert missing <= UNINDEXED_OWNER_ALLOWED, (
        f"ссылки без индекса: {sorted(missing - UNINDEXED_OWNER_ALLOWED)}"
    )
    paid = UNINDEXED_OWNER_ALLOWED - missing
    assert not paid, f"долг погашен: уберите {sorted(paid)} из UNINDEXED_OWNER_ALLOWED"


def test_the_receipts_of_an_item_are_found_by_its_index(db):
    """Debt 6: an issue or a sale looks up the receipts of its item; without the index the
    demo year's recalculation read every warehouse row ~3 400 times (2.9 s → 1.7 s)."""
    assert indexed(db, "inventory_lines", ("company_id", "item_id"))
    plan = " ".join(
        r[3]
        for r in db.execute(
            "EXPLAIN QUERY PLAN SELECT id FROM inventory_lines WHERE company_id = 1 AND item_id = 2"
        )
    )
    assert "inventory_lines_by_item" in plan


def plan(db: sqlite3.Connection, sql: str) -> str:
    return " ".join(r[3] for r in db.execute("EXPLAIN QUERY PLAN " + sql))


def test_the_journal_reads_a_period_by_the_date_index(db):
    """Session 49: the index of 0001 starts with the status, so a period of the journal
    (every status) read all the company's documents and sorted them in a temporary tree."""
    found = plan(
        db,
        "SELECT id FROM documents WHERE company_id = 1 AND doc_date >= '2026-01-01' "
        "AND doc_date <= '2026-01-31' ORDER BY doc_date, number",
    )
    assert "documents_by_date" in found
    assert "TEMP B-TREE" not in found


def test_the_contracts_of_a_counterparty_are_found_by_index(db):
    found = plan(db, "SELECT id FROM subconto_values WHERE company_id = 1 AND owner_id = 2")
    assert "subconto_values_owner" in found


def test_a_company_file_declares_itself(tmp_path):
    """A file of another program is refused before its tables are read (0046)."""
    path = tmp_path / "own.gl"
    close(connect(path))
    with sqlite3.connect(path) as own:
        assert own.execute("PRAGMA application_id").fetchone()[0] == APPLICATION_ID
    own.close()
    foreign = tmp_path / "other.gl"
    with sqlite3.connect(foreign) as other:
        other.execute("PRAGMA application_id = 12345")
    other.close()
    with pytest.raises(sqlite3.DatabaseError):
        connect(foreign)
    assert foreign.with_name("other.gl-wal").exists() is False  # the file was not touched


def test_another_programs_file_with_the_default_id_is_refused(tmp_path):
    """application_id 0 is what every other program leaves: a file with tables of its
    own is not ours and stays byte for byte as it was (no migration is run on it)."""
    foreign = tmp_path / "notes.gl"
    with sqlite3.connect(foreign) as other:
        other.execute("CREATE TABLE notes (id INTEGER PRIMARY KEY, text TEXT)")
        other.execute("INSERT INTO notes (text) VALUES ('hello')")
    other.close()
    before = hashlib.sha256(foreign.read_bytes()).hexdigest()
    with pytest.raises(sqlite3.DatabaseError, match="не файл компании"):
        connect(foreign)
    with pytest.raises(sqlite3.DatabaseError, match="не файл компании"):
        open_snapshot(foreign)
    assert hashlib.sha256(foreign.read_bytes()).hexdigest() == before
    assert not foreign.with_name("notes.gl-wal").exists()


def test_an_empty_file_and_an_old_file_of_ours_are_accepted(tmp_path):
    empty = tmp_path / "new.gl"
    close(connect(empty))  # a new file: no tables, application_id 0
    old = tmp_path / "old.gl"
    with sqlite3.connect(old) as ours:  # before 0046: our tables, application_id 0
        ours.execute("CREATE TABLE companies (id INTEGER PRIMARY KEY, name TEXT NOT NULL)")
    ours.close()
    with pytest.raises(sqlite3.DatabaseError, match="already exists"):
        connect(old)  # the mark is accepted; the schema has no version: 0001 fails on it


def test_demo_company_is_consistent(ledger):
    create_demo_company(ledger)
    conn = ledger.conn
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_a_locked_file_is_told_in_the_users_words(tmp_path):
    """Another connection (another program) keeps the write lock: after the timeout the
    write is refused with a message for the user, not with a traceback (D159)."""
    path = tmp_path / "shared.gl"
    first = connect(path)
    second = connect(path, timeout=0.2)
    try:
        first.execute("BEGIN IMMEDIATE")
        with pytest.raises(BusyError, match="занят другой программой"), transaction(second):
            pass
        first.execute("ROLLBACK")
        with transaction(second):  # free again
            pass
    finally:
        close(first)
        close(second)


def test_a_failed_update_leaves_the_file_header_as_it_was(tmp_path):
    """The move to WAL comes after the migrations: a file whose update failed is byte for
    byte what the older program wrote («файл не изменён» is true)."""
    path = tmp_path / "old.gl"
    with sqlite3.connect(path) as ours:
        ours.execute("CREATE TABLE companies (id INTEGER PRIMARY KEY, name TEXT NOT NULL)")
    ours.close()
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(sqlite3.DatabaseError, match="already exists"):
        connect(path)
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before
    assert not path.with_name("old.gl-wal").exists()
