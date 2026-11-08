"""D214: a new company enters a batch's expenses without knowing the accounts; the amounts
are counted by hand."""

from __future__ import annotations

from datetime import date

import pytest
from PySide6.QtCore import Qt

from modern_gl.application.bank.customs_payment import CustomsPayment
from modern_gl.application.catalog import Catalog
from modern_gl.application.chart_csv import apply_chart_template
from modern_gl.application.default_accounts import LANDED_COST, SUPPLIER, default_account
from modern_gl.application.ledger import Ledger
from modern_gl.desktop.landed_cost_page import LandedCostPage
from modern_gl.desktop.landed_cost_page.columns import ACCOUNT, SC1, SOURCE
from modern_gl.desktop.preferences import prefs
from modern_gl.desktop.session import Session
from modern_gl.domain.accounts import BATCH_EXPENSES_ACCOUNT
from modern_gl.i18n import tr
from modern_gl.infrastructure.db import connect
from modern_gl.reporting.reports import trial_balance


def company(chart: str | None = "classic"):
    conn = connect(":memory:")
    ledger = Ledger(conn, actor="test")
    cid = ledger.create_company("Yeni")
    if chart:
        apply_chart_template(ledger, cid, chart, "ru")
    return conn, ledger, cid


def session_of(conn, ledger, cid) -> Session:
    return Session(conn, ledger, cid, "Yeni", Catalog(conn, cid), date(2026, 9, 30))


@pytest.mark.parametrize("chart", ["classic", "1c77"])
def test_a_new_company_has_the_waiting_account_at_once(chart):
    conn, ledger, cid = company(chart)
    account = ledger.account_role(cid, BATCH_EXPENSES_ACCOUNT)
    assert account is not None and default_account(ledger, cid, LANDED_COST) == account
    row = conn.execute(
        "SELECT code, account_type FROM accounts WHERE id = ?", (account,)
    ).fetchone()
    assert (row["code"], row["account_type"]) == ("15", "inventory")


def test_an_older_company_finds_15_without_the_setting():
    _conn, ledger, cid = company(None)
    made = ledger.add_account(cid, "15", "Tədarük", account_class="asset", account_type="inventory")
    assert ledger.account_role(cid, BATCH_EXPENSES_ACCOUNT) is None
    assert default_account(ledger, cid, LANDED_COST) == made


def test_customs_fees_make_the_account_when_the_chart_has_none():
    """Fees 100.00: 15 +100.00, 51 -100.00; the account is kept for the next time."""
    conn, ledger, cid = company(None)
    bank = ledger.add_account(cid, "51", "Bank", account_class="asset", account_type="bank")
    payable = ledger.add_account(
        cid, "60", "Malsatan", account_class="liability", account_type="payable"
    )
    assert default_account(ledger, cid, LANDED_COST) is None
    ledger.bank.save_customs_payment(
        cid, CustomsPayment("2026-09-22", bank, (), payable, fees=10_000)
    )
    made = ledger.account_role(cid, BATCH_EXPENSES_ACCOUNT)
    assert made is not None
    rows = trial_balance(conn, cid, date(2026, 1, 1), date(2026, 12, 31)).rows
    assert {r.code: r.closing_dt - r.closing_ct for r in rows} == {"15": 10_000, "51": -10_000}


def test_a_typed_expense_starts_on_the_supplier_with_the_account_hidden(qtbot):
    conn, ledger, cid = company()
    session = session_of(conn, ledger, cid)
    page = LandedCostPage(session)
    qtbot.addWidget(page)
    charges = page.charges
    supplier = default_account(ledger, cid, SUPPLIER)
    assert supplier is not None and charges.rows[0].account_id == supplier
    assert charges.accounts_hidden
    assert page.charges_table.isColumnHidden(charges.columns.index(ACCOUNT))
    kind = session.catalog.accounts[supplier].sc_kinds[0]
    assert kind is not None
    header = charges.headerData(charges.columns.index(SC1), Qt.Orientation.Horizontal)
    assert header == session.catalog.kinds[kind]
    source = charges.index(0, charges.columns.index(SOURCE))
    assert source.data() == tr("Вручную") and not charges.editable(0, SOURCE)


def test_the_accounts_come_back_from_the_menu_and_are_remembered(qtbot):
    conn, ledger, cid = company()
    page = LandedCostPage(session_of(conn, ledger, cid))
    qtbot.addWidget(page)
    column = page.charges.columns.index(ACCOUNT)
    page._toggle_accounts()
    assert not page.charges_table.isColumnHidden(column) and prefs().landed_accounts_shown()
    page._toggle_accounts()
    assert page.charges_table.isColumnHidden(column) and not prefs().landed_accounts_shown()
