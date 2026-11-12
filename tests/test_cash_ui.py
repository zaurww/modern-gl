"""The cash desk on the page «Банк и касса» (D-new-cash): a cash desk once money moved on it,
its days without a bank to reconcile with, the form without a deposit or a bank fee, the
papers in Excel. 02.03: 500.00 from the founder to the cash desk (Dt 50 / Ct 80)."""

from __future__ import annotations

import openpyxl
import pytest
from PySide6.QtWidgets import QFileDialog

from modern_gl.application.bank import FEE, IN, BankLine, BankOperationInput
from modern_gl.desktop.bank_page import BankPage, cash_papers
from tests.helpers.bank_ui import acc, new_page, value


@pytest.fixture
def session(bank_session):
    s = bank_session
    data = BankOperationInput(
        doc_date="2026-03-02",
        direction=IN,
        account_id=acc(s, "50"),
        kind="other",
        lines=(BankLine(acc(s, "80"), 50000, (value(s, "Учредитель"),)),),
        memo="Взнос учредителя",
    )
    s.ledger.bank.save_bank_operation(s.company_id, data, post=True)
    return s


@pytest.fixture
def saved(monkeypatch, tmp_path):
    """Where «Сохранить» writes: the file chosen, nothing opened in Excel."""
    target = tmp_path / "paper.xlsx"
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(target), ""))
    )
    monkeypatch.setattr(cash_papers.QDesktopServices, "openUrl", staticmethod(lambda url: True))
    return target


def test_the_cash_desk_and_its_day(qtbot, session, saved):
    page = BankPage(session)
    qtbot.addWidget(page)
    titles = [r.title for r in page.model.rows]
    assert titles[:2] == ["Касса", "Касса"]  # its group, then the desk itself
    page.drill(page.model.rows[1])
    assert page.level == "journal"
    assert "С банком" not in [c.title for c in page.model.columns]
    assert page.model.columns[0].title == "День"
    menu = dict(i for i in page.more_items() if i is not None)
    assert "Загрузить выписку из файла…" not in menu and "Реквизиты счёта…" not in menu
    menu["Кассовая книга в Excel…"]()
    rows = [r[1] for r in openpyxl.load_workbook(saved).worksheets[0].values]
    assert "Остаток на начало дня" in rows and "Остаток на конец дня" in rows

    page.drill(page.model.rows[0])
    assert page.level == "statement"
    assert page.reconcile.bank.isHidden() and page.reconcile.verdict.isHidden()
    assert page.reconcile.figures["closing"].text() == "500.00"
    page.table.setCurrentIndex(page.model.index(0, 0))
    menu = dict(i for i in page.more_items() if i is not None)
    menu["Кассовый ордер в Excel…"]()
    texts = [c for r in openpyxl.load_workbook(saved).worksheets[0].values for c in r]
    assert "Пятьсот манатов 00 копеек" in texts
    assert "Учредитель" in texts


def test_the_form_of_a_cash_desk(qtbot, session):
    prefill = BankOperationInput(doc_date="2026-03-05", direction=IN, account_id=acc(session, "50"))
    page = new_page(qtbot, session, prefill)
    assert page.is_cash and page.bank_caption.text() == "Касса"
    assert page.reference.isHidden()
    assert not page.deposit_shown
    fee = page.kind.findData(FEE)
    assert fee in page.kind._hidden  # no bank fee in cash
    assert "F6" not in page.keys_hint.text()
