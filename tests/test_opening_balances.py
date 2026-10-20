from __future__ import annotations

import pytest

from modern_gl.application.catalog import Catalog
from modern_gl.application.ledger import PostingInput
from modern_gl.application.queries import opening_document
from modern_gl.domain.accounts import OPENING_BALANCE
from modern_gl.domain.errors import ValidationError
from modern_gl.reporting.reports import trial_balance


def test_opening_balances_become_report_opening_and_control_closes(ledger, conn):
    cid = ledger.create_company("Новая фирма")
    cash = ledger.add_account(cid, "50", "Касса", account_class="asset")
    capital = ledger.add_account(cid, "85", "Капитал", account_class="equity")
    control = ledger.opening_account(cid)

    doc_id = ledger.save_opening_balances(
        cid,
        "2026-01-01",
        [
            PostingInput(cash, control, "1000"),
            PostingInput(control, capital, "1000"),
        ],
        post=True,
        memo="Начальные остатки",
    )

    marker = opening_document(conn, cid)
    assert marker is not None
    assert (marker.document_id, marker.effective_date) == (doc_id, "2026-01-01")
    rows = {row.code: row for row in trial_balance(conn, cid, "2026-01-01", "2026-01-31").rows}
    assert (rows["50"].opening_dt, rows["85"].opening_ct) == (100_000, 100_000)
    assert all(row.account_id != control for row in rows.values())

    catalog = Catalog(conn, cid)
    assert control in catalog.accounts
    assert control not in {account.id for account in catalog.leaf_accounts}

    same_id = ledger.save_opening_balances(
        cid,
        "2026-01-01",
        [
            PostingInput(cash, control, "1200"),
            PostingInput(control, capital, "1200"),
        ],
        post=True,
        memo="Начальные остатки",
    )
    assert same_id == doc_id
    rows = {row.code: row for row in trial_balance(conn, cid, "2026-01-01", "2026-01-31").rows}
    assert (rows["50"].opening_dt, rows["85"].opening_ct) == (120_000, 120_000)


def test_difference_stays_on_account_00(ledger, conn):
    cid = ledger.create_company("Новая фирма")
    cash = ledger.add_account(cid, "50", "Касса", account_class="asset")
    capital = ledger.add_account(cid, "85", "Капитал", account_class="equity")
    control = ledger.opening_account(cid)

    # Dt 50 1000 and Kt 85 900: 00 is credited 1000 and debited 900 -> Kt 100 remains
    ledger.save_opening_balances(
        cid,
        "2026-01-01",
        [PostingInput(cash, control, "1000"), PostingInput(control, capital, "900")],
        post=True,
        memo="Начальные остатки",
    )

    rows = {row.code: row for row in trial_balance(conn, cid, "2026-01-01", "2026-01-31").rows}
    assert (rows["50"].opening_dt, rows["85"].opening_ct) == (100_000, 90_000)
    assert (rows["00"].opening_dt, rows["00"].opening_ct) == (0, 10_000)
    assert rows["00"].account_id == control


def test_old_counter_account_without_code_becomes_00(ledger):
    cid = ledger.create_company("Новая фирма")
    old = ledger.add_account(cid, None, "Технический счёт", account_class="equity")
    ledger.set_account_role(cid, OPENING_BALANCE, old)

    assert ledger.opening_account(cid) == old
    assert Catalog(ledger.conn, cid).accounts[old].code == "00"


def test_control_account_only_in_opening_balances(ledger):
    cid = ledger.create_company("Новая фирма")
    cash = ledger.add_account(cid, "50", "Касса", account_class="asset")
    capital = ledger.add_account(cid, "85", "Капитал", account_class="equity")
    control = ledger.opening_account(cid)
    doc_id = ledger.save_opening_balances(
        cid,
        "2026-01-01",
        [PostingInput(cash, control, "500"), PostingInput(control, capital, "500")],
        post=True,
        memo="Начальные остатки",
    )

    with pytest.raises(ValidationError, match="счёт ввода начальных остатков"):
        ledger.post_new(cid, "2026-01-05", [PostingInput(cash, control, "10")])
    # a storno would leave the opening document with nothing to correct: edit it instead
    with pytest.raises(ValidationError, match="счёт ввода начальных остатков"):
        ledger.reverse(cid, doc_id, "2026-01-05")
