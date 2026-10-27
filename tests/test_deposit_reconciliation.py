"""The ƏDV deposit account reconciled with the portal for a period (D118). The portal's
operations of 01–03.10.2026 and its balance now 1 000.00 — see test_vat_deposit_import.

All of 01–03.10 loaded (the transfer from the company's bank is a draft), then a fee of
5.00 typed by hand on 03.10. Hand-calculated, 01–03.10:

  portal: in 594.00 + 90.00 + 200.00 = 884.00, out 12.44 + 940.00 = 952.44,
          closing 1 000.00, opening 1 000.00 − 884.00 + 952.44 = 1 068.44
  books:  opening 0 (no opening balance entered), in 594.00 + 90.00 = 684.00 (the draft
          does not move the balance), out 952.44 + 5.00 = 957.44, closing −273.44
  difference 1 000.00 − (−273.44) = 1 273.44 = the opening 1 068.44 + the draft 200.00
          + the fee 5.00
"""

from __future__ import annotations

from datetime import date

import pytest

from modern_gl.application.bank import OUT, TAX, BankLine, BankOperationInput
from modern_gl.application.bank.deposit_reconciliation import (
    BOOKS_ONLY,
    DIFFERENT,
    PORTAL_ONLY,
    SAME,
    Figures,
    changed_since,
    reconcile_deposit,
    reconciled_periods,
)
from modern_gl.i18n import tr
from tests.helpers.deposit import fee
from tests.helpers.qt import tree_item
from tests.helpers.vat_deposit import operations


@pytest.fixture
def firm(deposit_firm):
    return deposit_firm


def test_the_period_by_the_portal_and_by_the_books(ledger, firm):
    cid, place = firm["cid"], firm["place"]
    ledger.bank.import_vat_deposit(cid, place, operations(), 100000)
    fee(ledger, firm)
    seen = reconcile_deposit(
        ledger.conn, cid, place, operations(), 100000, "2026-10-01", "2026-10-03"
    )
    assert seen.portal == Figures(106844, 88400, 95244)
    assert seen.portal.closing == 100000
    assert seen.books == Figures(0, 68400, 95744)
    assert (seen.books.closing, seen.difference) == (-27344, 127344)
    assert [(row.state, row.op.amount if row.op else None) for row in seen.rows] == [
        (SAME, 59400),
        (SAME, 1244),
        (SAME, 94000),
        (SAME, 9000),
        (DIFFERENT, 20000),
        (BOOKS_ONLY, None),
    ]
    assert seen.rows[4].note == tr("в программе черновик — не проведён")
    assert seen.rows[5].line is not None and seen.rows[5].line.money_out == 500
    assert not seen.agreed


def test_a_day_by_the_portal_counts_back_the_later_operations(ledger, firm):
    """02.10 alone, nothing loaded: closing 1 000.00 − 90.00 − 200.00 = 710.00, opening
    710.00 + 12.44 + 940.00 = 1 662.44; both operations only on the portal."""
    cid, place = firm["cid"], firm["place"]
    seen = reconcile_deposit(
        ledger.conn, cid, place, operations(), 100000, "2026-10-02", "2026-10-02"
    )
    assert seen.portal == Figures(166244, 0, 95244)
    assert seen.portal.closing == 71000
    assert [row.state for row in seen.rows] == [PORTAL_ONLY, PORTAL_ONLY]
    assert [op.reference for op in seen.missing()] == ["2619000000000002", "2619000000000003"]


def test_a_payment_typed_by_hand_is_the_portal_s_and_a_wrong_amount_is_said(
    ledger,
    firm,
):
    """Alfa's 12.44 typed by hand on 02.10 (no reference yet) — the same; the budget's
    940.00 typed as 904.00 on 02.10 — another amount, not the portal's."""
    cid, place = firm["cid"], firm["place"]
    fee(ledger, firm, "2026-10-02", 1244)
    fee(ledger, firm, "2026-10-02", 90400)
    seen = reconcile_deposit(
        ledger.conn, cid, place, operations(), 100000, "2026-10-02", "2026-10-02"
    )
    assert [row.state for row in seen.rows] == [SAME, PORTAL_ONLY, BOOKS_ONLY]


def test_loaded_on_another_day_is_said(ledger, firm):
    """Alfa's 12.44 in the books with the portal's reference but dated 05.10: on 02.10 it
    is the portal's with another day, not missing."""
    cid, place = firm["cid"], firm["place"]
    ledger.bank.save_bank_operation(
        cid,
        BankOperationInput(
            doc_date="2026-10-05",
            direction=OUT,
            account_id=place.account_id,
            subconto=place.subconto,
            kind=TAX,
            lines=(BankLine(firm["acc"]["68.2"], 1244),),
            reference="2619000000000002",
        ),
        post=True,
    )
    seen = reconcile_deposit(
        ledger.conn, cid, place, operations(), 100000, "2026-10-02", "2026-10-02"
    )
    assert [(row.state, row.note) for row in seen.rows] == [
        (DIFFERENT, tr("в программе от {day}", day="05.10.2026")),
        (PORTAL_ONLY, ""),
    ]


def test_a_reconciled_period_warns_of_a_change_since(ledger, firm):
    """01–03.10 marked reconciled; then a fee of 5.00 on 02.10 in the books, and the portal
    shows 90.00 of 03.10 gone (another balance now: 910.00)."""
    cid, place = firm["cid"], firm["place"]
    ledger.bank.import_vat_deposit(cid, place, operations(), 100000)
    seen = reconcile_deposit(
        ledger.conn, cid, place, operations(), 100000, "2026-10-01", "2026-10-03"
    )
    ledger.bank.mark_deposit_reconciled(cid, place, seen)
    [period] = reconciled_periods(ledger.conn, cid, place)
    assert (period.date_from, period.date_to) == ("2026-10-01", "2026-10-03")
    assert period.books == Figures(0, 68400, 95244)
    assert changed_since(ledger.conn, cid, place, operations(), 100000, "2026-10-01") == []

    fee(ledger, firm, "2026-10-02")
    fewer = [op for op in operations() if op.amount != 9000]
    assert changed_since(ledger.conn, cid, place, fewer, 91000, "2026-10-01") == [
        tr(
            "{period} сверен, но {side} изменилось: приход {was_in} → {now_in}, расход "
            "{was_out} → {now_out}, на конец {was_end} → {now_end}",
            period="01.10.2026–03.10.2026",
            side=tr("в программе"),
            was_in="684.00",
            now_in="684.00",
            was_out="952.44",
            now_out="957.44",
            was_end="-268.44",
            now_end="-273.44",
        ),
        tr(
            "{period} сверен, но {side} изменилось: приход {was_in} → {now_in}, расход "
            "{was_out} → {now_out}, на конец {was_end} → {now_end}",
            period="01.10.2026–03.10.2026",
            side=tr("на портале"),
            was_in="884.00",
            now_in="794.00",
            was_out="952.44",
            now_out="952.44",
            was_end="1 000.00",
            now_end="910.00",
        ),
    ]
    # the portal read from a later day does not cover the period: not compared
    assert len(changed_since(ledger.conn, cid, place, fewer, 91000, "2026-10-02")) == 1


def test_the_window_reconciles_loads_the_missing_and_marks(qtbot, ledger, firm, deposit_session):
    """01–02.10 loaded; 01–03.10 reconciled: the two of 03.10 only on the portal — loaded
    in one click (the transfer stays a draft), then the period marked reconciled."""
    from modern_gl.desktop.bank_page.deposit_reconcile import DepositReconcileDialog

    s, _messages, token, _portal = deposit_session
    cid, place = firm["cid"], firm["place"]
    ledger.bank.import_vat_deposit(cid, place, operations(), 100000, ("2026-10-01", "2026-10-02"))
    dialog = DepositReconcileDialog(s, place, sign_in=lambda _p: token, today=date(2026, 10, 3))
    qtbot.addWidget(dialog)
    assert dialog.period() == (date(2026, 10, 1), date(2026, 10, 3))
    dialog.reconcile()
    qtbot.waitUntil(lambda: dialog.seen is not None, timeout=5000)
    seen = dialog.seen
    assert seen is not None
    assert [row.state for row in seen.rows] == [SAME, SAME, SAME, PORTAL_ONLY, PORTAL_ONLY]
    assert not dialog.load_missing.isHidden()
    # the closing: portal 1 000.00, books 594.00 − 12.44 − 940.00 = −358.44; the difference
    # 1 358.44 = no opening balance 1 068.44 + the 90.00 and 200.00 of 03.10
    assert dialog.figures.cells[(3, 4)].text() == "1 358.44"

    dialog.load_missing.click()
    assert dialog.changed
    assert dialog.seen is not None
    assert [row.state for row in dialog.seen.rows] == [SAME, SAME, SAME, SAME, DIFFERENT]
    assert dialog.load_missing.isHidden()

    dialog.mark_button.click()
    [period] = reconciled_periods(ledger.conn, cid, place)
    assert (period.date_from, period.date_to) == ("2026-10-01", "2026-10-03")
    assert dialog.history.text() == tr("Сверено с порталом: {periods}.", periods="01.10–03.10.2026")
    dialog.rows.itemDoubleClicked.emit(tree_item(dialog.rows, 0), 0)
    assert dialog.seen is not None and dialog.seen.rows[0].line is not None
    assert dialog.chosen_document == dialog.seen.rows[0].line.document_id
