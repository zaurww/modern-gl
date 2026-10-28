"""Shared from test_bank_ui.py (moved here: other test modules use it too)."""

from __future__ import annotations

from datetime import date

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QLineEdit

from modern_gl.application.catalog import Catalog
from modern_gl.application.chart_csv import apply_chart_template
from modern_gl.application.ledger import Ledger, PostingInput
from modern_gl.desktop import theme
from modern_gl.desktop.bank_operation_page import BankOperationPage
from modern_gl.desktop.session import Session
from modern_gl.domain.currency import parse_rate
from modern_gl.infrastructure.db import connect
from tests.helpers.qt import running_app


def setup_company(ledger: Ledger) -> int:
    """Kapital AZN with 10 000.00 from 01.03, Kapital USD; ALFA (VÖEN 1234567890) with
    its contract."""
    cid = ledger.create_company("ООО Банк")
    apply_chart_template(ledger, cid, "1c77", "ru")
    banks = ledger.subconto_kind_id(cid, "bank_account")
    partners = ledger.subconto_kind_id(cid, "counterparty")
    contracts = ledger.subconto_kind_id(cid, "contract")
    azn = ledger.add_subconto_value(cid, banks, "Kapital AZN")
    usd_bank = ledger.add_subconto_value(cid, banks, "Kapital USD")
    ledger.set_subconto_value_currency(cid, usd_bank, ledger.currency_id(cid, "USD"))
    alfa = ledger.add_subconto_value(cid, partners, "ALFA MMC")
    ledger.set_subconto_value_tax(cid, alfa, "1234567890")
    ledger.add_subconto_value(cid, contracts, "Договор 1", owner_id=alfa)
    owner = ledger.add_subconto_value(cid, partners, "Учредитель")
    ledger.set_rate(cid, "USD", "2026-03-01", parse_rate("1.7"))
    ledger.post_new(
        cid,
        "2026-03-01",
        [
            PostingInput(
                ledger.account_id(cid, "51"), ledger.account_id(cid, "80"), "10000", [azn], [owner]
            )
        ],
    )
    return cid


@pytest.fixture(name="bank_session")
def session(qtbot):
    theme.apply(running_app())
    conn = connect(":memory:")
    ledger = Ledger(conn, actor="test")
    cid = setup_company(ledger)
    messages: list[str] = []
    s = Session(conn, ledger, cid, "ООО Банк", Catalog(conn, cid), notify=messages.append)
    s.working_date = date(2026, 3, 5)
    yield s
    conn.close()


def choose(box, text: str) -> None:
    i = box.findText(text)
    assert i >= 0, text
    box.setCurrentIndex(i)
    box.activated.emit(i)


def acc(session: Session, code: str) -> int:
    return session.catalog.by_code[code].id


def value(session: Session, name: str) -> int:
    return next(
        v.id for k in session.catalog.kinds for v in session.catalog.all_values(k) if v.name == name
    )


def new_page(qtbot, session: Session, prefill=None) -> BankOperationPage:
    page = BankOperationPage(session, prefill=prefill)
    qtbot.addWidget(page)
    return page


def type_text(edit, text: str) -> None:
    edit.setText(text)
    edit.textEdited.emit(text)


def pay_alfa(page: BankOperationPage) -> None:
    """1 180.00 to ALFA found by its VÖEN, e-qaimə MT001."""
    choose(page.sc[0], "Kapital AZN")
    type_text(page.counterparty_edit, "1234567890")
    page.counterparty_edit.editingFinished.emit()
    line = page.line_rows[0]
    type_text(line.amount, "1180")
    type_text(line.invoice, "MT001")


def key(qtbot, k, modifier=Qt.KeyboardModifier.NoModifier) -> None:
    """A key where the user's goes: the open list, or the field with the cursor."""
    popup = QApplication.activePopupWidget()
    target = popup if popup is not None and popup.isVisible() else QApplication.focusWidget()
    assert target is not None
    qtbot.keyClick(target, k, modifier)


def typed(text: str) -> None:
    """Typed into the field with the cursor (keyClicks fails on Azerbaijani letters)."""
    edit = QApplication.focusWidget()
    assert isinstance(edit, QLineEdit)
    edit.selectAll()
    edit.insert(text)
    edit.textEdited.emit(edit.text())


def shown_page(qtbot, session: Session) -> BankOperationPage:
    page = new_page(qtbot, session)
    page.show()
    qtbot.waitExposed(page)
    page.activateWindow()
    qtbot.waitUntil(page.counterparty_edit.hasFocus)
    return page
