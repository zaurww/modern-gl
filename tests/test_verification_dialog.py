"""The window of «Проверка книги» (D-new): what it shows, the rebuild, viewing (D80).
The figures are those of tests/test_verification.py: a fee of 2.00 USD is 3.40 at 1.70
and 3.50 once the rate of 07.03 is 1.75."""

from __future__ import annotations

from dataclasses import replace

import pytest

from modern_gl.application.bank import load_bank_operation
from modern_gl.application.catalog import Catalog
from modern_gl.application.queries import load_document
from modern_gl.desktop.session import Session
from modern_gl.desktop.verification_dialog import VerificationDialog
from modern_gl.domain.currency import parse_rate
from tests.helpers.bank import usd_fee

pytestmark = pytest.mark.questions("Yes")


def window(qtbot, session: Session, opened: list[int] | None = None) -> VerificationDialog:
    dialog = VerificationDialog(session, (opened if opened is not None else []).append)
    qtbot.addWidget(dialog)
    return dialog


def bank_session(ledger, firm) -> tuple[Session, int]:
    cid = firm["cid"]
    op_id = ledger.bank.save_bank_operation(cid, usd_fee(firm), post=True)
    ledger.set_rate(cid, "USD", "2026-03-07", parse_rate("1.75"))
    doc_id = load_bank_operation(ledger.conn, cid, op_id).document_id
    return Session(ledger.conn, ledger, cid, "Bank", Catalog(ledger.conn, cid)), doc_id


def test_a_sound_company(qtbot, demo):
    s = Session(
        demo.ledger.conn,
        demo.ledger,
        demo.company_id,
        "Test",
        Catalog(demo.ledger.conn, demo.company_id),
    )
    dialog = window(qtbot, s)
    assert dialog.title.text() == "Всё сходится"
    assert not dialog.rebuild.isVisibleTo(dialog)


def test_findings_open_their_document_and_the_rebuild_puts_them_right(qtbot, ledger, bank_firm):
    s, doc_id = bank_session(ledger, bank_firm)
    opened: list[int] = []
    dialog = window(qtbot, s, opened)
    assert dialog.title.text() == "Найдено расхождений: 1"
    assert dialog.rebuild.isVisibleTo(dialog)
    [link] = [b for b in dialog.findChildren(type(dialog.rebuild)) if b.objectName() == "crumb"]
    assert "проводки отличаются от документа раздела «Банк»" in link.text()

    dialog.rebuild.click()
    assert [p.amount for p in load_document(ledger.conn, s.company_id, doc_id).postings] == [350]
    assert dialog.changed == [doc_id]
    assert dialog.title.text() == "Всё сходится"
    assert not dialog.rebuild.isVisibleTo(dialog)


def test_a_finding_opens_its_document(qtbot, ledger, bank_firm):
    s, doc_id = bank_session(ledger, bank_firm)
    opened: list[int] = []
    dialog = window(qtbot, s, opened)
    [link] = [b for b in dialog.findChildren(type(dialog.rebuild)) if b.objectName() == "crumb"]
    link.click()
    assert opened == [doc_id]


def test_viewing_shows_the_findings_without_the_rebuild(qtbot, ledger, bank_firm):
    s, _ = bank_session(ledger, bank_firm)
    dialog = window(qtbot, replace(s, read_only=True))
    assert dialog.title.text() == "Найдено расхождений: 1"
    assert not dialog.rebuild.isVisibleTo(dialog)
