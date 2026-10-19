"""Accounts without a code: known by their name everywhere.

Example (hand-calculated), March 2026:
  1  2026-03-01  Dt Kassa     Ct 85 Kapital   1 000.00
  2  2026-03-10  Dt Xərclər   Ct Kassa          250.00

  account   turnover Dt/Ct     closing Dt/Ct
  85             - / 1 000          - / 1 000
  Kassa      1 000 / 250          750 / -
  Xərclər      250 / -            250 / -
  total      1 250 / 1 250      1 000 / 1 000
"""

import sqlite3

import pytest

from modern_gl.application.catalog import Catalog
from modern_gl.application.ledger import PostingInput
from modern_gl.domain.errors import ValidationError
from modern_gl.infrastructure.db import MIGRATIONS_DIR, connect
from modern_gl.reporting.reports import account_analysis, account_card, trial_balance


@pytest.fixture
def company(ledger):
    cid = ledger.create_company("Kodsuz MMC")
    ids = {
        "kassa": ledger.add_account(cid, None, "Kassa", account_class="asset"),
        "capital": ledger.add_account(cid, "85", "Kapital", account_class="equity"),
        "costs": ledger.add_account(cid, "", "Xərclər", account_class="expense"),
    }
    ledger.post_new(cid, "2026-03-01", [PostingInput(ids["kassa"], ids["capital"], "1000")])
    ledger.post_new(cid, "2026-03-10", [PostingInput(ids["costs"], ids["kassa"], "250")])
    return cid, ids


def test_reports_name_accounts_without_code(ledger, conn, company):
    cid, ids = company
    osv = trial_balance(conn, cid, "2026-03-01", "2026-03-31")
    rows = [
        (r.code, r.name, r.turnover_dt, r.turnover_ct, r.closing_dt, r.closing_ct) for r in osv.rows
    ]
    assert rows == [
        ("85", "Kapital", 0, 100000, 0, 100000),  # coded accounts first,
        ("", "Kassa", 100000, 25000, 75000, 0),  # then the others alphabetically
        ("", "Xərclər", 25000, 0, 25000, 0),
    ]
    assert (osv.total.closing_dt, osv.total.closing_ct) == (100000, 100000)

    card = account_card(conn, cid, ids["kassa"], "2026-03-01", "2026-03-31")
    assert [(ln.corr_code, ln.corr_id, ln.balance) for ln in card.lines] == [
        ("85", ids["capital"], 100000),
        ("Xərclər", ids["costs"], 75000),  # no code: the name stands in
    ]
    analysis = account_analysis(conn, cid, ids["kassa"], "2026-03-01", "2026-03-31")
    assert [(r.corr_code, r.corr_name, r.debit, r.credit) for r in analysis] == [
        ("85", "Kapital", 100000, 0),
        ("", "Xərclər", 0, 25000),
    ]


def test_catalog_finds_accounts_by_name(conn, company):
    cid, ids = company
    cat = Catalog(conn, cid)
    assert cat.resolve_account("kas").id == ids["kassa"]
    assert cat.resolve_account("xerc").id == ids["costs"]  # Azerbaijani letters folded
    assert cat.resolve_account("85").id == ids["capital"]
    assert cat.accounts[ids["kassa"]].label == "Kassa"
    assert cat.accounts[ids["kassa"]].short == "Kassa"
    assert cat.accounts[ids["capital"]].short == "85"
    assert "" not in cat.by_code


def test_codes_optional_but_unique(ledger, conn, company):
    cid, ids = company
    ledger.add_account(cid, None, "Bank")  # many accounts may have no code
    with pytest.raises(ValidationError, match="уже есть"):
        ledger.add_account(cid, "85", "Başqa kapital")
    with pytest.raises(ValidationError, match="название"):
        ledger.add_account(cid, None, "  ")

    ledger.update_account(cid, ids["kassa"], new_code="50")
    assert ledger.account_id(cid, "50") == ids["kassa"]
    ledger.update_account(cid, ids["kassa"], new_code="")  # the code can be removed again
    code = conn.execute("SELECT code FROM accounts WHERE id = ?", (ids["kassa"],)).fetchone()[0]
    assert code is None


def test_codeless_subaccount_stays_under_its_parent(ledger, conn):
    cid = ledger.create_company("Ağac")
    ledger.add_account(cid, "60", "Malsatanlar", is_group=True, account_class="liability")
    ledger.add_account(cid, None, "Alfa", parent="60")
    ledger.add_account(cid, "60.1", "Digər", parent="60")
    ledger.add_account(cid, "70", "Əmək haqqı")
    cat = Catalog(conn, cid)
    assert [a.short for a in cat.accounts.values()] == ["60", "60.1", "Alfa", "70"]


def test_migration_keeps_accounts_and_postings(tmp_path):
    """A file made before codes became optional opens with its history intact."""
    path = tmp_path / "old.gl"
    old = sqlite3.connect(path)
    for script in sorted(MIGRATIONS_DIR.glob("*.sql"))[:4]:
        old.executescript(f"BEGIN;\n{script.read_text(encoding='utf-8')}\nCOMMIT;")
    old.execute("PRAGMA user_version = 4")
    old.execute("INSERT INTO companies (id, name, created_at) VALUES (1, 'Old', 'now')")
    old.execute("INSERT INTO layers (id, company_id, code, name) VALUES (1, 1, 'common', 'C')")
    old.execute("INSERT INTO accounts (id, company_id, code, name) VALUES (1, 1, '50', 'Kassa')")
    old.execute("INSERT INTO accounts (id, company_id, code, name) VALUES (2, 1, '85', 'Kapital')")
    old.execute(
        "INSERT INTO documents (id, company_id, number, doc_date, layer_id, status, created_at) "
        "VALUES (1, 1, 1, '2026-01-01', 1, 'draft', 'now')"
    )
    old.execute(
        "INSERT INTO postings (company_id, document_id, line_no, debit_account_id, "
        "credit_account_id, amount) VALUES (1, 1, 1, 1, 2, 500)"
    )
    old.commit()
    old.close()

    conn = connect(path)
    assert conn.execute("PRAGMA user_version").fetchone()[0] >= 5
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    posting = conn.execute("SELECT debit_account_id, credit_account_id FROM postings").fetchone()
    assert tuple(posting) == (1, 2)
    nullable = {r[1]: r[3] for r in conn.execute("PRAGMA table_info(accounts)")}
    assert nullable["code"] == 0  # NOT NULL dropped
    conn.close()
