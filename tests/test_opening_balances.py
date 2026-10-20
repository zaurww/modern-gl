from __future__ import annotations

import pytest

from modern_gl.application.catalog import Catalog
from modern_gl.application.ledger import PostingInput
from modern_gl.application.opening_balances import (
    ensure_opening_account,
    opening_document,
    save_opening_document,
)
from modern_gl.domain.errors import ValidationError
from modern_gl.reporting.reports import trial_balance


def test_opening_balances_become_report_opening_and_control_closes(ledger, conn):
    cid = ledger.create_company("Новая фирма")
    cash = ledger.add_account(cid, "50", "Касса", account_class="asset")
    capital = ledger.add_account(cid, "85", "Капитал", account_class="equity")
    control = ensure_opening_account(ledger, cid)

    doc_id = save_opening_document(
        ledger,
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

    same_id = save_opening_document(
        ledger,
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


def test_opening_balances_must_balance(ledger):
    cid = ledger.create_company("Новая фирма")
    cash = ledger.add_account(cid, "50", "Касса", account_class="asset")
    capital = ledger.add_account(cid, "85", "Капитал", account_class="equity")
    control = ensure_opening_account(ledger, cid)

    with pytest.raises(ValidationError, match="не сходятся"):
        save_opening_document(
            ledger,
            cid,
            "2026-01-01",
            [
                PostingInput(cash, control, "1000"),
                PostingInput(control, capital, "900"),
            ],
            post=True,
            memo="Начальные остатки",
        )
