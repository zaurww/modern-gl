"""The bank module (D47): the statement page and the form of an operation."""

from __future__ import annotations

from datetime import date

import pytest
from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import QApplication, QDialog

from modern_gl.application.bank import (
    IN,
    OUT,
    SUPPLIER,
    TAX,
    BankLine,
    BankOperationInput,
    load_bank_operation,
    next_to_check,
)
from modern_gl.application.catalog import Catalog
from modern_gl.application.ledger import Ledger, PostingInput
from modern_gl.application.queries import load_document
from modern_gl.application.workspace import Workspace
from modern_gl.desktop import theme
from modern_gl.desktop.bank_operation_page import BankOperationPage
from modern_gl.desktop.bank_page import BankPage, BankSettingsDialog
from modern_gl.desktop.conversion_page import ConversionPage
from modern_gl.desktop.document_page import DocumentPage
from modern_gl.desktop.main_window import MainWindow
from modern_gl.desktop.session import Session
from modern_gl.infrastructure.db import connect
from tests.helpers.bank_ui import (
    acc,
    choose,
    key,
    new_page,
    pay_alfa,
    setup_company,
    shown_page,
    type_text,
    typed,
    value,
)
from tests.helpers.qt import running_app

pytestmark = pytest.mark.questions("Yes")  # deleting, posting: yes


@pytest.fixture
def session(bank_session):
    return bank_session


def test_payment_to_a_supplier_found_by_voen(qtbot, session):
    page = new_page(qtbot, session)
    # a new one: money out of the first bank account, to a supplier
    assert page.btn_out.isChecked() and page.kind.currentData() == SUPPLIER
    assert page.bank_info is not None and page.bank_info.code == "51"
    assert page.title() == "Новый расход"
    pay_alfa(page)
    assert page.counterparty_edit.text() == "ALFA MMC"
    assert page.tax_id.text() == "VÖEN 1234567890"
    line = page.line_rows[0]
    # nothing paid to ALFA before: the supplier's account; its only contract is taken
    assert line.account_info is not None and line.account_info.code == "60.1"
    assert line.sc[0].isHidden()  # the counterparty is the operation's
    assert line.sc[1].currentText() == "Договор 1"
    assert page.total.text() == "1 180.00 AZN"
    assert page.memo.placeholderText() == "Оплата поставщику ALFA MMC"

    assert page.save(post=True)
    assert page.doc is not None and page.doc.status == "posted"
    assert page.title() == f"Расход №{page.doc.number}"
    [p] = load_document(session.conn, session.company_id, page.doc.document_id).postings
    assert (p.debit_account_id, p.credit_account_id, p.amount, p.invoice) == (
        acc(session, "60.1"),
        acc(session, "51"),
        118000,
        "MT001",
    )
    assert p.debit_subconto == (value(session, "ALFA MMC"), value(session, "Договор 1"), None)
    assert p.memo == "Оплата поставщику ALFA MMC"
    assert page.btn_unpost.isVisibleTo(page) and not page.btn_save.isVisibleTo(page)


def test_lines_as_last_time_for_the_counterparty(qtbot, session):
    """ALFA was paid an advance from 60.2 last time: the next payment suggests 60.2."""
    cid = session.company_id
    alfa, contract = value(session, "ALFA MMC"), value(session, "Договор 1")
    session.ledger.bank.save_bank_operation(
        cid,
        BankOperationInput(
            doc_date="2026-03-02",
            direction=OUT,
            account_id=acc(session, "51"),
            subconto=(value(session, "Kapital AZN"),),
            kind=SUPPLIER,
            counterparty_id=alfa,
            lines=(BankLine(acc(session, "60.2"), 5000, (None, contract)),),
            memo="Аванс",
        ),
        post=True,
    )
    page = new_page(qtbot, session)
    pay_alfa(page)
    line = page.line_rows[0]
    assert line.account_info is not None and line.account_info.code == "60.2"
    assert line.sc[1].currentData() == contract
    assert line.amount.text() == "1180"


def test_tax_has_no_counterparty(qtbot, session):
    page = new_page(qtbot, session)
    choose(page.kind, "Налоги")
    assert page.counterparty_edit.isHidden()
    assert page.line_rows[0].account_info is not None
    assert page.line_rows[0].account_info.code == "68.1"
    assert page.memo.placeholderText() == "Уплата налогов"
    choose(page.sc[0], "Kapital AZN")
    type_text(page.line_rows[0].amount, "180")
    assert page.save(post=True)
    assert page.doc is not None and page.doc.kind == TAX and page.doc.counterparty_id is None


def test_bank_fee_line_and_a_receipt(qtbot, session):
    """Money in from ALFA (a refund): 100.00, and the bank takes 1.50 of it — in two
    lines: Dt 51 / Ct 60.1 100.00, and the fee line goes the same way."""
    page = new_page(qtbot, session)
    page.btn_in.click()
    assert page.title().startswith("Новый приход")
    pay_alfa(page)
    page.add_fee()
    fee = page.line_rows[1]
    assert fee.account_info is not None and fee.account_info.code == "91.2"
    assert fee.sc[0].currentText() == "Комиссия банка"
    type_text(fee.amount, "1.50")
    assert page.total.text() == "1 181.50 AZN"
    page.line_rows[1].remove.click()
    assert page.total.text() == "1 180.00 AZN"


def test_bank_settings_choose_the_fee_account(qtbot, session):
    """The template puts the fee on 91.2; the user makes 26 the default in «Настройки
    банка», and «+ Комиссия банка» takes 26 from then on."""
    dialog = BankSettingsDialog(session)
    qtbot.addWidget(dialog)
    assert dialog.fee.currentData() == acc(session, "91.2")
    dialog.fee.setCurrentIndex(dialog.fee.findData(acc(session, "26")))
    dialog._save()
    assert dialog.result() == QDialog.DialogCode.Accepted
    page = new_page(qtbot, session)
    page.add_fee()
    fee = page.line_rows[-1]
    assert fee.account_info is not None and fee.account_info.code == "26"


def test_operation_in_dollars_offers_the_rate(qtbot, session):
    page = new_page(qtbot, session)
    choose(page.account, "52  Валютные счета")
    assert page.currency.currentText() == "USD" and not page.currency.isEnabled()
    # the rate is of 01.03, not of the date itself: the official one can be loaded
    assert page.rate_note.isVisibleTo(page)
    session.fetch_rates = lambda day: {"USD": (1_701_000, 1)}
    page.load_rates()
    assert not page.rate_note.isVisibleTo(page)


def test_vat_deposit_offers_only_what_it_may_pay(qtbot, session):
    session.ledger.set_account_type(session.company_id, acc(session, "55"), "vat_deposit")
    session.catalog.reload()
    page = new_page(qtbot, session)
    choose(page.account, "55  Специальные счета в банках")
    kind = page.kind
    hidden = {kind.itemText(i) for i in range(kind.count()) if kind.isItemHidden(i)}
    assert hidden == {"Зарплата", "Комиссия банка", "Прочее"}


def test_the_bank_account_is_one_field(qtbot, session, monkeypatch):
    """The GL account, the bank and its currency are chosen at once: «Kapital USD · 52 ·
    USD» puts 52, the bank and USD; the currency is not asked. A bank never used on an
    account is offered there too (the ƏDV deposit 54 of the template). A bank not in the
    list is added right in the field, under the chosen account, and taken."""
    from modern_gl.desktop.directories_page import ValueDialog

    page = new_page(qtbot, session)
    assert page.bank.currentText() == "Kapital AZN  ·  51  ·  AZN"  # the first bank account
    assert page.currency.isHidden()
    choose(page.bank, "Kapital USD  ·  52  ·  USD")
    assert page.bank_info is not None and page.bank_info.code == "52"
    assert page.bank_subconto()[0] == value(session, "Kapital USD")
    assert page.total.text() == "0.00 USD"
    assert page.deposit.currentText() == "Kapital AZN  ·  54  ·  AZN"  # never used there

    def exec_(dialog):
        dialog.name.setText("Paşa Bank")
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(ValueDialog, "exec", exec_)
    choose(page.bank, "Kapital AZN  ·  51  ·  AZN")
    page.bank.unknown.emit("Paşa")
    paşa = value(session, "Paşa Bank")
    assert page.bank_info is not None and page.bank_info.code == "51"
    assert page.bank_subconto()[0] == paşa
    assert page.bank.currentText() == "Paşa Bank  ·  51  ·  AZN"


def test_no_stray_windows_of_the_page(qtbot, session):
    """The captions of the held bank subconto are not shown as windows of their own (the
    «Bank hesabları» box at the top left of the screen)."""
    page = new_page(qtbot, session)
    page.show()
    choose(page.bank, "Kapital USD  ·  52  ·  USD")
    stray = [
        w
        for w in QApplication.topLevelWidgets()
        if w.isVisible() and w is not page and not isinstance(w, QDialog)
    ]
    assert stray == []


def test_errors_stay_on_the_page_and_a_draft_is_saved(qtbot, session):
    page = new_page(qtbot, session)
    choose(page.sc[0], "Kapital AZN")
    assert not page.save(post=True)
    assert page.error.text() == "строка 1: нулевая сумма"  # the supplier's line
    type_text(page.line_rows[0].amount, "abc")
    assert not page.save(post=True)
    assert page.error.isVisibleTo(page)
    type_text(page.line_rows[0].amount, "10")
    assert page.save(post=False)
    assert page.doc is not None and page.doc.status == "draft"


def test_bank_page_goes_from_the_accounts_to_a_statement(qtbot, session):
    """The accounts by group → the statements of Kapital AZN → the day 01.03 with its line
    (10 000.00 in); the bank's balance typed in reconciles it; Backspace goes back up."""
    page = BankPage(session)
    qtbot.addWidget(page)
    assert [r.title for r in page.model.rows] == [
        "Расчётные счета",
        "Kapital AZN",
        "Валютные счета",
        "Kapital USD",
    ]
    assert page.place is not None and page.place.name == "Kapital AZN"  # the cursor
    page.drill(page.model.rows[1])
    assert page.level == "journal"
    assert [(s.date_from, s.closing, s.status) for s in page.model.rows] == [
        ("2026-03-01", 1_000_000, "open")
    ]
    page.drill(page.model.rows[0])
    assert page.level == "statement" and page.model.rowCount() == 1
    assert page.reconcile.figures["closing"].text() == "10 000.00"
    page.reconcile.bank.setText("10 000")
    page.reconcile.bank.editingFinished.emit()
    assert page.current is not None and page.current.status == "ok"
    assert "Сверена" in page.reconcile.verdict.text()

    emitted: list[BankOperationInput] = []
    page.new_bank_operation.connect(emitted.append)
    page.new_operation(IN)
    [prefill] = emitted
    assert (prefill.direction, prefill.account_id, prefill.doc_date) == (
        IN,
        acc(session, "51"),
        "2026-03-01",  # the statement's day
    )
    assert prefill.subconto[0] == value(session, "Kapital AZN")
    # the form takes what is known: the account and its bank account
    form = new_page(qtbot, session, prefill)
    assert form.btn_in.isChecked() and form.sc[0].currentText() == "Kapital AZN"
    assert not form.is_dirty()

    page.up()
    assert page.level == "journal" and page.model.rows[0].status == "ok"
    page.up()
    assert page.level == "accounts" and page.place is not None
    assert page.place.name == "Kapital AZN"  # back where it came from


def test_a_large_company_reads_the_statements_in_the_background(qtbot, tmp_path):
    """Debt 6: the same levels, read by a worker; the entry line gets the cursor only once
    the statement it belongs to is shown."""
    theme.apply(running_app())
    path = tmp_path / "bank.gl"
    conn = connect(path)
    ledger = Ledger(conn, actor="test")
    cid = setup_company(ledger)
    s = Session(conn, ledger, cid, "ООО Банк", Catalog(conn, cid), path=path, large=True)
    s.working_date = date(2026, 3, 5)
    page = BankPage(s)
    qtbot.addWidget(page)
    page.show()
    try:
        qtbot.waitUntil(lambda: page.model.rowCount() == 4)  # 2 groups, 2 accounts
        assert page.place is not None and page.place.name == "Kapital AZN"
        page.drill(page.model.rows[1])
        qtbot.waitUntil(lambda: page.level == "journal" and page.model.rowCount() == 1)
        started: list[bool] = []
        page.entry.start = lambda: started.append(True)  # type: ignore[method-assign]
        page.drill(page.model.rows[0])
        assert not started  # not before the lines are read
        qtbot.waitUntil(lambda: started == [True])
        assert page.level == "statement" and page.model.rowCount() == 1
        assert page.reconcile.figures["closing"].text() == "10 000.00"
    finally:
        s.background.wait()
        conn.close()


def test_a_new_statement_and_a_new_card(qtbot, session, monkeypatch):
    """«+ Выписка» opens the next working day after the last statement (01.03 is a Sunday:
    02.03); a card on 55 goes to its own group."""
    page = BankPage(session)
    qtbot.addWidget(page)
    page.open_account(page.model.rows[1].place.key)
    page.new_statement()
    assert page.level == "statement" and page.current is not None
    assert (page.current.date_from, page.current.opening) == ("2026-03-02", 1_000_000)
    session.ledger.bank.add_bank_account(
        session.company_id, "ABB Visa", acc(session, "55"), "card", card_digits="4417"
    )
    page.go("accounts")
    titles = [r.title for r in page.model.rows]
    assert titles[-2:] == ["Бизнес-карты", "ABB Visa ·· 4417"]


def test_the_journal_opens_the_operation(qtbot, tmp_path):
    theme.apply(running_app())
    workspace = Workspace(tmp_path / "data")
    conn = connect(workspace.new_path("ООО Банк"))
    setup_company(Ledger(conn))
    conn.close()
    win = MainWindow(workspace)
    qtbot.addWidget(win)
    win.start()
    win.open_session.working_date = date(2026, 3, 5)
    try:
        win.show_place(("bank",))
        bank = win.pages[("bank",)]
        assert isinstance(bank, BankPage)
        bank.new_operation(OUT)
        page = win.stack.currentWidget()
        assert isinstance(page, BankOperationPage)
        pay_alfa(page)
        account, bank_value = page.account.currentData(), page.bank_subconto()
        assert page.save(post=True)
        doc = page.doc
        assert doc is not None
        bank.open_account(bank.place.key if bank.place else (account, bank_value[0]))
        assert [s.date_from for s in bank.model.rows] == ["2026-03-01", "2026-03-05"]
        # the next one of the statement opens in its place: the same account and day
        following = win.stack.currentWidget()
        assert isinstance(following, BankOperationPage) and following is not page
        assert following.doc is None and ("bank_op", doc.id) not in win.pages
        assert following.account.currentData() == account
        assert following.bank_subconto() == bank_value
        assert following.date.date() == page.date.date()
        assert following.line_rows[0].amount.text() == "" and not following.is_dirty()

        win.close_current()  # Esc / Ctrl+W: back to the statement
        assert win.stack.currentWidget() is bank
        win.open_document(doc.document_id)  # from the journal or a report
        operation = win.stack.currentWidget()
        assert isinstance(operation, BankOperationPage)
        operation.btn_gl.click()
        gl = win.stack.currentWidget()
        assert isinstance(gl, DocumentPage) and gl.model.read_only

        win.copy_document(doc.document_id)  # F9: a new operation like this one
        copy = win.stack.currentWidget()
        assert isinstance(copy, BankOperationPage) and copy.doc is None
        assert copy.line_rows[0].amount.text() == "1 180.00"
        assert copy.line_rows[0].invoice.text() == ""
        session = win.open_session
        assert load_bank_operation(session.conn, session.company_id, doc.id).total == 118000

        bank.new_conversion.emit()  # the conversion moved here from the journal
        assert isinstance(win.stack.currentWidget(), ConversionPage)
    finally:
        win.shutdown()


def test_an_operation_is_typed_and_posted_without_the_mouse(qtbot, session):
    """D49: name → Enter → e-qaimə → Enter → amount → Enter → ƏDV from the deposit (D69,
    the template has the deposit 54) → Enter → «Провести» → Enter; the bank, day and kind
    are set before, the line as last time is folded into one."""
    page = shown_page(qtbot, session)
    choose(page.sc[0], "Kapital AZN")
    assert page.bank.currentText().startswith("Kapital AZN")
    page.counterparty_edit.setFocus()
    typed("alfa")
    key(qtbot, Qt.Key.Key_Return)  # the highlighted one is taken, on to the e-qaimə
    assert page.counterparty == value(session, "ALFA MMC")
    line = page.line_rows[0]
    assert line.account_info is not None and line.account_info.code == "60.1"
    assert page.folded and not line.isVisible()
    assert "Договор 1" in page.summary_text.text()
    assert page.invoice.hasFocus()
    typed("MT005")
    key(qtbot, Qt.Key.Key_Return)
    assert page.amount.hasFocus()
    typed("500")
    key(qtbot, Qt.Key.Key_Return)
    assert page.vat_amount.hasFocus()  # left empty: the deposit pays later
    key(qtbot, Qt.Key.Key_Return)
    assert page.btn_post.hasFocus()
    key(qtbot, Qt.Key.Key_Return)
    assert page.doc is not None and page.doc.status == "posted"
    assert [(x.amount, x.invoice) for x in page.doc.lines] == [(50_000, "MT005")]


def test_the_lines_unfold_with_a_fee_or_by_hand(qtbot, session):
    """One line is folded; F6 adds the fee line and shows both with their columns."""
    page = shown_page(qtbot, session)
    assert page.folded and page.summary.isVisible() and not page.lines_header.isVisible()
    page.amount.setFocus()
    typed("100")
    assert page.line_rows[0].amount.text() == "100"
    key(qtbot, Qt.Key.Key_F6)
    assert len(page.line_rows) == 2 and not page.folded
    assert page.lines_header.isVisible() and page.line_rows[0].amount.text() == "100"
    assert page.line_rows[1].amount.hasFocus()
    key(qtbot, Qt.Key.Key_Delete, Qt.KeyboardModifier.ControlModifier)
    assert len(page.line_rows) == 1 and not page.folded  # unfolded by hand: stays
    other = shown_page(qtbot, session)
    other.btn_unfold.click()
    assert not other.folded and other.line_rows[0].account.hasFocus()


def test_an_operation_written_opens_unfolded(qtbot, session):
    """A draft (or a posted one) opened again shows its line at once: it is opened to
    check the account, without «Развернуть» each time."""
    page = shown_page(qtbot, session)
    choose(page.sc[0], "Kapital AZN")
    page.counterparty_edit.setFocus()
    typed("alfa")
    key(qtbot, Qt.Key.Key_Return)
    page.amount.setFocus()
    typed("100")
    page.btn_save.click()
    assert page.doc is not None and page.doc.status == "draft"
    again = new_page(qtbot, session)
    again.load(page.doc.id)
    again.show()
    qtbot.waitExposed(again)
    assert not again.folded and again.line_rows[0].isVisible()
    assert not again.btn_unfold.isVisible() and not again.summary.isVisible()


def saved_draft(qtbot, session, amount: str, day: str = "") -> int:
    page = shown_page(qtbot, session)
    choose(page.sc[0], "Kapital AZN")
    if day:
        page.date.setDate(QDate.fromString(day, "yyyy-MM-dd"))
    page.counterparty_edit.setFocus()
    typed("alfa")
    key(qtbot, Qt.Key.Key_Return)
    page.amount.setFocus()
    typed(amount)
    page.btn_save.click()
    assert page.doc is not None and page.doc.status == "draft"
    return page.doc.id


def test_a_draft_posted_hands_over_to_the_next_one(qtbot, session):
    """Drafts of a bank account are checked one after another: after the first one posted,
    the later one; after it, the one before (opened out of order); then none — the page
    goes back."""
    cid = session.company_id
    first = saved_draft(qtbot, session, "100", "2026-02-03")
    second = saved_draft(qtbot, session, "200", "2026-02-03")
    third = saved_draft(qtbot, session, "300", "2026-02-04")
    assert next_to_check(session.conn, cid, second) == third
    assert next_to_check(session.conn, cid, third) == first  # nothing later: from the start
    page = new_page(qtbot, session)
    page.load(second)
    with qtbot.waitSignal(page.draft_requested) as handed:
        page.btn_post.click()
    assert handed.args == [third]
    for op_id in (third, first):
        page = new_page(qtbot, session)
        page.load(op_id)
        page.btn_post.click()
    with qtbot.assertNotEmitted(page.draft_requested):
        page.load(first)
        page.btn_post.click()  # posted already: an edit of it hands over nothing
    assert next_to_check(session.conn, cid, first) is None


def test_lines_with_keys_insert_copy_and_remove(qtbot, session):
    page = shown_page(qtbot, session)
    line = page.line_rows[0]
    line.amount.setFocus()
    typed("100")
    key(qtbot, Qt.Key.Key_F9)  # a copy: the same account, the amount to change
    assert len(page.line_rows) == 2
    copy = page.line_rows[1]
    assert copy.account.currentData() == line.account.currentData()
    assert copy.amount.text() == "100.00"
    key(qtbot, Qt.Key.Key_Insert)  # an empty one, the cursor on its account
    assert len(page.line_rows) == 3 and page.line_rows[2].account.hasFocus()
    key(qtbot, Qt.Key.Key_Delete, Qt.KeyboardModifier.ControlModifier)
    assert len(page.line_rows) == 2 and copy.account.hasFocus()
    assert page.total.text() == "200.00 AZN"


def test_a_new_counterparty_is_added_right_in_the_operation(qtbot, session, monkeypatch):
    """Not in the directory: its window opens with what was typed, no trip to
    «Справочники»; a VÖEN typed goes to the VÖEN field."""
    from modern_gl.desktop.directories_page import ValueDialog

    seen = []

    def exec_(dialog):
        seen.append((dialog.name.text(), dialog.tax_id.text()))
        dialog.name.setText("BETA MMC")
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(ValueDialog, "exec", exec_)
    page = shown_page(qtbot, session)
    typed("9876543210")
    key(qtbot, Qt.Key.Key_Return)
    qtbot.waitUntil(lambda: page.counterparty is not None)
    assert seen == [("", "9876543210")]
    beta = value(session, "BETA MMC")
    assert page.counterparty == beta
    assert session.catalog.value(beta).tax_id == "9876543210"
    assert page.tax_id.text() == "VÖEN 9876543210"
    assert page.invoice.hasFocus()  # on with the payment


def test_a_name_nothing_is_called_stays_in_the_field(qtbot, session):
    page = shown_page(qtbot, session)
    page.kind.setFocus()
    typed("xyz")
    key(qtbot, Qt.Key.Key_Return)
    assert page.kind.hasFocus() and page.kind.currentData() == SUPPLIER
    qtbot.waitUntil(page.error.isVisible)
    assert page.error.text() == "«xyz» нет в списке"


def owe_alfa(session: Session) -> None:
    """ALFA's e-qaimə: MT1 of 02.03 1 416.00 (paid 416.00 on 03.03, so 1 000.00 left),
    MT2 of 04.03 1 239.00; a sale MT9 to ALFA is owed the other way and is not offered."""
    ledger, cid = session.ledger, session.company_id
    alfa, contract = value(session, "ALFA MMC"), value(session, "Договор 1")
    supplier = (alfa, contract)
    rent = (ledger.add_subconto_value(cid, ledger.subconto_kind_id(cid, "cost_item"), "Аренда"),)
    for day, amount, number in (("2026-03-02", "1416", "MT1"), ("2026-03-04", "1239", "MT2")):
        ledger.post_new(
            cid,
            day,
            [
                PostingInput(
                    acc(session, "26"), acc(session, "60.1"), amount, rent, supplier, invoice=number
                )
            ],
        )
    ledger.post_new(
        cid,
        "2026-03-03",
        [
            PostingInput(
                acc(session, "60.1"),
                acc(session, "51"),
                "416",
                supplier,
                (value(session, "Kapital AZN"),),
                invoice="MT1",
            )
        ],
    )
    ledger.post_new(
        cid,
        "2026-03-04",
        [
            PostingInput(
                acc(session, "62.1"),
                acc(session, "90.1"),
                "500",
                (alfa, contract),
                (),
                invoice="MT9",
            )
        ],
    )
    session.catalog.reload()


def test_the_unpaid_e_qaime_of_the_counterparty_are_offered(qtbot, session):
    """Paying ALFA on 05.03: the list offers MT1 1 000.00 and MT2 1 239.00 (oldest first),
    not the sale MT9; ↓ Enter takes MT1 with what is left on it."""
    owe_alfa(session)
    page = shown_page(qtbot, session)
    choose(page.sc[0], "Kapital AZN")
    typed("alfa")
    key(qtbot, Qt.Key.Key_Return)
    assert [(i.invoice, i.amount) for i in page.open_invoices] == [
        ("MT1", 100_000),
        ("MT2", 123_900),
    ]
    line = page.line_rows[0]
    assert page.invoice.hasFocus()  # the list opens by itself
    qtbot.waitUntil(lambda: QApplication.activePopupWidget() is not None)
    key(qtbot, Qt.Key.Key_Down)
    key(qtbot, Qt.Key.Key_Return)
    assert line.invoice.text() == "MT1" and line.amount.text() == "1 000.00"
    assert page.invoice.text() == "MT1" and page.amount.text() == "1 000.00"
    assert page.amount.hasFocus()


def test_one_payment_over_several_e_qaime(qtbot, session, monkeypatch):
    """2 000.00 typed, then «several»: MT1 1 000.00 in full, MT2 the other 1 000.00
    (of 1 239.00); posted, MT1 is closed and MT2 has 239.00 left."""
    from modern_gl.application.invoices import open_invoices
    from modern_gl.desktop.invoice_picker import InvoicePicker

    owe_alfa(session)
    monkeypatch.setattr(
        InvoicePicker, "exec", lambda dialog: (dialog._done(), QDialog.DialogCode.Accepted)[1]
    )
    page = shown_page(qtbot, session)
    choose(page.sc[0], "Kapital AZN")
    typed("alfa")
    key(qtbot, Qt.Key.Key_Return)
    type_text(page.amount, "2000")
    several = page.invoice.findText("Несколько e-qaimə…")
    assert several == page.invoice.count() - 1  # after the e-qaimə themselves
    page.invoice._choose(several)
    qtbot.waitUntil(lambda: len(page.line_rows) == 2)
    assert [(r.invoice.text(), r.amount.text()) for r in page.line_rows] == [
        ("MT1", "1 000.00"),
        ("MT2", "1 000.00"),
    ]
    assert page.line_rows[1].account_info is not None
    assert page.line_rows[1].account_info.code == "60.1"
    assert page.save(post=True), page.error.text()
    left = open_invoices(
        session.conn, session.company_id, value(session, "ALFA MMC"), True, "2026-03-05"
    )
    assert [(i.invoice, i.amount) for i in left] == [("MT2", 23_900)]


def test_the_vat_part_goes_from_the_deposit_account(qtbot, session):
    """D69. MT7 of 02.03 to ALFA: 1 000.00 + ƏDV 180.00. Paying on 05.03: the e-qaimə
    from the list puts 1 000.00 from the bank and 180.00 from the ƏDV deposit (55,
    500.00 on it since 01.03); «Провести» makes two operations, MT7 is paid in full."""
    from modern_gl.application.invoices import open_invoices

    ledger, cid = session.ledger, session.company_id
    ledger.set_account_type(cid, acc(session, "55"), "vat_deposit")
    banks = ledger.subconto_kind_id(cid, "bank_account")
    deposit = ledger.add_subconto_value(cid, banks, "ƏDV depozit")
    alfa, contract = value(session, "ALFA MMC"), value(session, "Договор 1")
    owner = value(session, "Учредитель")
    rent = (ledger.add_subconto_value(cid, ledger.subconto_kind_id(cid, "cost_item"), "Аренда"),)
    ledger.post_new(
        cid,
        "2026-03-01",
        [PostingInput(acc(session, "55"), acc(session, "80"), "500", [deposit], [owner])],
    )
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
                invoice="MT7",
            ),
            PostingInput(
                acc(session, "19.4"),
                acc(session, "60.1"),
                "180",
                (alfa,),
                (alfa, contract),
                invoice="MT7",
            ),
        ],
    )
    session.catalog.reload()
    page = shown_page(qtbot, session)
    choose(page.sc[0], "Kapital AZN")
    assert page.deposit_shown and page.deposit.currentText().startswith("ƏDV depozit")
    typed("alfa")
    key(qtbot, Qt.Key.Key_Return)
    assert page.invoice.hasFocus()
    qtbot.waitUntil(lambda: QApplication.activePopupWidget() is not None)
    key(qtbot, Qt.Key.Key_Down)
    key(qtbot, Qt.Key.Key_Return)
    assert (page.amount.text(), page.vat_amount.text()) == ("1 000.00", "180.00")
    assert page.amount_caption.text() == "Из банка"
    assert page.check.text().endswith("e-qaimə оплачивается полностью")
    page.line_rows[0].invoice.setText("№ mt 7")  # typed by hand: as the portal writes it
    page._show_check()
    assert page.check.isVisibleTo(page)
    page.line_rows[0].invoice.setText("MT7")
    assert page.save(post=True), page.error.text()
    assert page.doc is not None
    bank_lines = [(x.account_id, x.amount, x.invoice) for x in page.doc.lines]
    assert bank_lines == [(acc(session, "60.1"), 100_000, "MT7")]
    on_deposit = session.conn.execute(
        "SELECT p.credit_account_id, p.amount, p.invoice FROM postings p "
        "JOIN documents d ON d.id = p.document_id "
        "WHERE d.status = 'posted' AND p.debit_account_id = ? AND p.credit_account_id = ?",
        (acc(session, "60.1"), acc(session, "55")),
    ).fetchall()
    assert [tuple(r) for r in on_deposit] == [(acc(session, "55"), 18_000, "MT7")]
    left = open_invoices(session.conn, cid, alfa, True, "2026-03-05")
    assert [i.invoice for i in left] == []


def test_viewing_only_shows_the_statements_and_changes_nothing(qtbot, session):
    """A company open for viewing (D80): no entry line, no new money, the bank's
    balance is read, not typed."""
    session.read_only = True
    page = BankPage(session)
    qtbot.addWidget(page)
    page.show()
    page.open_account(page.model.rows[1].place.key)
    page.drill(page.model.rows[0])
    assert page.level == "statement"
    assert page.entry.isHidden() and page.money_in.isHidden() and page.money_out.isHidden()
    assert page.reconcile.bank.isReadOnly()
    titles = [item[0] for item in page.more_items() if item]  # only to Excel
    assert "Реквизиты счёта…" not in titles and "В Excel…" in titles


def test_rates_not_loaded_leave_the_note_and_tell_why(qtbot, session):
    """One «Загрузить курс ЦБА» for the document, the bank operation and the conversion
    (desktop/rate_note): an error is shown on the form, no toast; then a toast with how
    many rates came."""
    from modern_gl.infrastructure.cbar import RatesUnavailableError

    page = new_page(qtbot, session)
    choose(page.account, "52  Валютные счета")
    told: list[str] = []
    session.notify = told.append

    def unavailable(day):
        raise RatesUnavailableError("cbar.az не отвечает")

    session.fetch_rates = unavailable
    page.load_rates()
    assert page.rate_note.isVisibleTo(page)
    assert page.error.isVisibleTo(page) and page.error.text() == "cbar.az не отвечает"
    assert told == []
    session.fetch_rates = lambda day: {"USD": (1_701_000, 1)}
    page.load_rates()
    assert not page.rate_note.isVisibleTo(page)
    assert told == ["Курсы ЦБА на 05.03.2026 загружены: 1"]
