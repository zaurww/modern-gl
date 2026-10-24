"""The year demo: the whole 2026 with documents on every day and in every module."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from modern_gl.application.ledger import Ledger
from modern_gl.demo_year import TWO_YEARS, TWO_YEARS_NAME, create_year_demo
from modern_gl.infrastructure.db import connect
from modern_gl.reporting.inventory import landed_cost_report
from modern_gl.reporting.reports import trial_balance


@pytest.fixture(scope="module")
def year():
    conn = connect(":memory:")
    cid = create_year_demo(Ledger(conn))
    yield conn, cid
    conn.close()


def count(conn, sql: str, *params) -> int:
    return conn.execute(sql, params).fetchone()[0]


def test_every_day_of_the_year_has_posted_documents(year):
    conn, cid = year
    days = {
        r[0]
        for r in conn.execute(
            "SELECT DISTINCT doc_date FROM documents WHERE company_id = ? AND status = 'posted'",
            (cid,),
        )
    }
    missing = []
    day = date(2026, 1, 1)
    while day.year == 2026:
        if day.isoformat() not in days:
            missing.append(day)
        day += timedelta(days=1)
    assert missing == []


def test_the_books_balance_and_money_is_never_short(year):
    conn, cid = year
    osv = trial_balance(conn, cid, "2026-01-01", "2026-12-31")
    assert osv.total.closing_dt == osv.total.closing_ct
    rows = {r.code: r for r in osv.rows if not r.is_group}
    balance = {code: r.closing_dt - r.closing_ct for code, r in rows.items()}
    for money in ("50", "51", "54"):
        assert balance[money] >= 0, money
    for closed in ("19", "26", "44", "46", "57", "71", "80"):  # cleared every month / year
        assert balance[closed] == 0, closed
    assert rows["88"].turnover_ct > 0  # a profitable year


def test_every_module_is_used(year):
    conn, cid = year
    inventory = {
        r[0]
        for r in conn.execute(
            "SELECT doc_type FROM inventory_documents WHERE company_id = ? AND status = 'posted'",
            (cid,),
        )
    }
    assert inventory == {"opening", "receipt", "issue", "transfer", "sale", "landed_cost"}
    kinds = {
        r[0] for r in conn.execute("SELECT kind FROM bank_operations WHERE company_id = ?", (cid,))
    }
    assert kinds == {"supplier", "customer", "tax", "salary", "fee", "transfer", "other"}
    layers = {
        r[0]
        for r in conn.execute(
            "SELECT l.code FROM documents d JOIN layers l ON l.id = d.layer_id "
            "WHERE d.company_id = ?",
            (cid,),
        )
    }
    assert layers == {"common", "ifrs_adj", "tax_adj"}
    for table in (
        "currency_conversions",
        "opening_balance_documents",
        "eqaime_portal",
        "eqaime_reconciled",
        "entry_templates",
        "subconto_value_tags",
    ):
        assert count(conn, f"SELECT COUNT(*) FROM {table} WHERE company_id = ?", cid), table
    for condition in (
        "reversal_of IS NOT NULL",  # a storno
        "status = 'draft'",
        "id IN (SELECT document_id FROM postings WHERE currency_amount = 0)",  # revaluation
    ):
        assert count(
            conn, f"SELECT COUNT(*) FROM documents WHERE company_id = ? AND {condition}", cid
        )
    assert count(conn, "SELECT closed_through FROM companies WHERE id = ?", cid) == "2026-06-30"


def test_imports_on_declarations_carry_their_expenses(year):
    conn, cid = year
    kinds, rows = landed_cost_report(conn, cid, "2026-01-01", "2026-12-31")
    assert kinds == ["Gömrük rüsumu", "Gömrük yığımı", "Daşınma", "Sığorta", "Sertifikatlaşdırma"]
    declarations = [d for d in rows if d.invoice_kind == "customs"]
    assert len(declarations) == 7
    assert {d.currency for d in declarations} == {"EUR", "USD"}
    assert all(len(d.lines) >= 10 and d.added > 0 for d in declarations)
    charged = count(
        conn,
        "SELECT SUM(c.amount) FROM landed_cost_charges c JOIN inventory_documents d "
        "ON d.id = c.document_id WHERE d.company_id = ? AND d.status = 'posted'",
        cid,
    )
    assert sum(d.added for d in rows) == charged  # every qəpik reached a line
    certified = {
        line.item_name
        for d in declarations
        for line in d.lines
        if "Sertifikatlaşdırma" in line.expenses
    }
    assert "Proyektor Full HD" in certified and "Laminator A3" not in certified
    # the certification comes when part of the goods is sold: that share is cost of sales
    assert count(
        conn,
        "SELECT COUNT(*) FROM inventory_lines l JOIN inventory_documents d "
        "ON d.id = l.document_id WHERE d.company_id = ? AND d.doc_type = 'landed_cost' "
        "AND l.expense_amount > 0",
        cid,
    )


def test_two_years_follow_one_another():
    """2025 and 2026: the second year starts from where the first ended — one opening on
    01.01.2025, the loan repaid across the years, both years closed into 88."""
    conn = connect(":memory:")
    cid = create_year_demo(Ledger(conn), TWO_YEARS_NAME, TWO_YEARS)
    days = {
        r[0]
        for r in conn.execute(
            "SELECT DISTINCT doc_date FROM documents WHERE company_id = ? AND status = 'posted'",
            (cid,),
        )
    }
    day, missing = date(2025, 1, 1), []
    while day.year <= 2026:
        if day.isoformat() not in days:
            missing.append(day)
        day += timedelta(days=1)
    assert missing == []
    assert (
        count(conn, "SELECT COUNT(*) FROM opening_balance_documents WHERE company_id = ?", cid) == 1
    )
    for year, loan in ((2025, 2_500_000), (2026, 0)):
        osv = trial_balance(conn, cid, f"{year}-01-01", f"{year}-12-31")
        assert osv.total.closing_dt == osv.total.closing_ct
        rows = {r.code: r for r in osv.rows if not r.is_group}
        balance = {code: r.closing_dt - r.closing_ct for code, r in rows.items()}
        assert all(balance[money] >= 0 for money in ("50", "51", "54"))
        assert balance["80"] == 0 and rows["88"].turnover_ct > 0
        assert -balance["90"] == loan  # 5 000 AZN, 250 a month from March 2025
    conn.close()
