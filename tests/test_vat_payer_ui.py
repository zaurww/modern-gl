"""The payment form pays a supplier's ƏDV from the current account straight to their
deposit (D145): the ƏDV part is a line of its own, marked ƏDV, and is credited."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from modern_gl.application.bank import load_bank_operation
from modern_gl.application.ledger import PostingInput
from modern_gl.application.vat import credit_events, purchase_facts, rule_for
from modern_gl.desktop.bank_operation_page.common import FROM_BANK
from tests.test_bank_ui import acc, choose, key, no_modal_dialogs, session, shown_page, typed, value

__all__ = ["no_modal_dialogs", "session"]  # the fixtures of the bank's form tests


def test_the_payment_form_pays_the_vat_from_the_bank(qtbot, session):
    """MT8 of 02.03 to ALFA: 1 000 + ƏDV 180. Beside the deposit accounts the form
    offers the ƏDV part «С этого счёта — на депозит поставщика»; chosen, the e-qaimə
    from the list puts 1 000 from the bank and 180 as the ƏDV; «Провести» makes one
    operation of two lines, the second marked ƏDV — 180 credited on 05.03. Opened
    again, the second line shows its mark."""
    ledger, cid = session.ledger, session.company_id
    alfa, contract = value(session, "ALFA MMC"), value(session, "Договор 1")
    rent = (ledger.add_subconto_value(cid, ledger.subconto_kind_id(cid, "cost_item"), "Аренда"),)
    ledger.post_new(
        cid,
        "2026-03-02",
        [
            PostingInput(
                acc(session, "26"),
                acc(session, "60.1"),
                "1000",
                rent,
                (alfa, contract),
                invoice="MT8",
            ),
            PostingInput(
                acc(session, "19.4"),
                acc(session, "60.1"),
                "180",
                (alfa,),
                (alfa, contract),
                invoice="MT8",
            ),
        ],
    )
    session.catalog.reload()
    page = shown_page(qtbot, session)
    choose(page.sc[0], "Kapital AZN")
    choose(page.deposit, "С этого счёта — на депозит поставщика")
    typed("alfa")
    key(qtbot, Qt.Key.Key_Return)
    assert page.deposit_shown and page.deposit.currentData() == FROM_BANK
    qtbot.waitUntil(lambda: QApplication.activePopupWidget() is not None)
    key(qtbot, Qt.Key.Key_Down)
    key(qtbot, Qt.Key.Key_Return)
    assert (page.amount.text(), page.vat_amount.text()) == ("1 000.00", "180.00")
    assert page.vat_caption.text() == "ƏDV поставщику" and page.deposit_date.isHidden()
    assert page.save(post=True), page.error.text()
    assert page.doc is not None
    lines = [(x.amount, x.invoice, x.pays_vat) for x in page.doc.lines]
    assert lines == [(100_000, "MT8", False), (18_000, "MT8", True)]
    (facts,) = purchase_facts(session.conn, cid, "2026-03-31")
    assert [(e.day, e.amount) for e in credit_events(facts, rule_for("2026-03-01"))] == [
        ("2026-03-05", 18_000)
    ]
    page.load(page.doc.id)
    assert [row.vat.isChecked() for row in page.line_rows] == [False, True]
    again = load_bank_operation(session.conn, cid, page.doc.id)
    assert [x.pays_vat for x in again.lines] == [False, True]


def test_the_payer_day_is_asked_and_the_reports_say_it(qtbot, session, monkeypatch):
    """«Плательщик ƏDV с…»: «15.03.2026» typed — stored; «ƏDV продаж к уплате» for March
    says the company pays from 15.03; for April, nothing. Emptied — a payer all along."""
    from datetime import date

    from PySide6.QtWidgets import QInputDialog

    from modern_gl.application.vat import payer_from
    from modern_gl.desktop.reports_page import ReportParams, VatLiabilityPage
    from modern_gl.desktop.vat_payer import edit_vat_payer

    answers = iter([("15.03.2026", True), ("", True)])
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: next(answers)))
    assert edit_vat_payer(None, session)  # type: ignore[arg-type]
    assert payer_from(session.conn, session.company_id) == "2026-03-15"
    page = VatLiabilityPage(session, ReportParams(date(2026, 3, 1), date(2026, 3, 31)))
    qtbot.addWidget(page)
    assert "Плательщик ƏDV с 15.03.2026" in page.footer.text()
    page.period.set_period(date(2026, 4, 1), date(2026, 4, 30))
    page.refresh()
    assert "Плательщик" not in page.footer.text()
    assert edit_vat_payer(None, session)  # type: ignore[arg-type]
    assert payer_from(session.conn, session.company_id) == ""
