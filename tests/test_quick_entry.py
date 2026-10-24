"""Quick entry: a document typed as one line of text."""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from fractions import Fraction

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from modern_gl.application.catalog import Catalog
from modern_gl.application.chart_csv import apply_chart_template
from modern_gl.application.ledger import Ledger, PostingInput
from modern_gl.application.queries import list_templates, load_document, past_postings
from modern_gl.application.quick_entry import describe, parse
from modern_gl.application.quick_entry.card import card
from modern_gl.application.quick_entry.marks import marks
from modern_gl.application.quick_entry.past import past_lines
from modern_gl.desktop import theme
from modern_gl.desktop.quick_entry_bar import QuickEntryBar
from modern_gl.desktop.session import Session
from modern_gl.domain.currency import parse_rate
from modern_gl.domain.errors import ValidationError
from modern_gl.domain.money import from_minor
from modern_gl.infrastructure.db import connect

TODAY = date(2026, 3, 5)


@pytest.fixture
def books():
    conn = connect(":memory:")
    ledger = Ledger(conn, actor="test")
    cid = ledger.create_company("Firma")
    apply_chart_template(ledger, cid, "classic", "ru")
    values = {}
    for kind, name in (
        ("counterparty", "Альфа Трейд"),
        ("counterparty", "Бета Сервис"),
        ("contract", "Договор №1"),
        ("cost_item", "Аренда офиса"),
        ("bank_account", "Kapital Bank"),
        ("bank_account", "Kapital Bank USD"),
    ):
        values[name] = ledger.add_subconto_value(cid, ledger.subconto_kind_id(cid, kind), name)
    usd = ledger.currency_id(cid, "USD")
    ledger.set_subconto_value_currency(cid, values["Kapital Bank USD"], usd)
    ledger.set_rate(cid, "USD", "2026-03-01", parse_rate("1.7"))
    yield conn, ledger, cid, Catalog(conn, cid), values
    conn.close()


def rate(_currency, _day):
    return Fraction(17, 10)


def test_posting_with_subconto_amount_and_memo(books):
    _conn, _, _cid, cat, v = books
    entry = parse("26 аренда / 60 альфа, договор 400 Аренда за март", cat, today=TODAY)
    [ln] = entry.lines
    assert (ln.debit, ln.credit, ln.amount, ln.memo) == (
        cat.by_code["26"].id,
        cat.by_code["60"].id,
        40_000,
        "Аренда за март",
    )
    assert ln.debit_sc[0] == v["Аренда офиса"]
    assert ln.credit_sc[:2] == [v["Альфа Трейд"], v["Договор №1"]]
    assert entry.memo == "Аренда за март" and entry.doc_date is None and not entry.missing
    text = describe(entry, cat)
    assert "26 · Аренда офиса" in text and "60 · Альфа Трейд, Договор №1" in text
    assert "400.00" in text


def test_date_several_postings_and_missing_subconto(books):
    _, _, _, cat, _ = books
    entry = parse("05.03 50 / 51 kapital bank 2000 В кассу; 71 / 50 1234,50", cat, today=TODAY)
    assert entry.doc_date == date(2026, 3, 5)
    assert [ln.amount for ln in entry.lines] == [200_000, 123_450]
    assert entry.missing == ["Дт 71: Сотрудники"]  # employee not given yet
    assert parse("1.2.25 50 / 80 1", cat, today=TODAY).doc_date == date(2025, 2, 1)


def test_errors_say_what_to_do(books):
    _, _, _, cat, _ = books
    for text, message in (
        ("26 60 400", "разделяются «/»"),
        ("26 аренда / 60 альфа", "не указана сумма"),
        ("999 / 50 10", "999"),
        ("26 реклама / 50 10", r"напишите \+реклама"),
        ("50 / 80 x, y 10", "субконто 0"),
    ):
        with pytest.raises(ValidationError, match=message):
            parse(text, cat, today=TODAY)


def test_new_element_with_plus(books):
    _, _, _, cat, _ = books
    entry = parse("26 +Реклама / 50 10", cat, today=TODAY)
    [new] = entry.new_values
    assert new.name == "Реклама" and new.cells == [(0, "debit", 0)]
    assert "+Реклама" in describe(entry, cat)


def test_currency_line_is_in_currency(books):
    _, _, _, cat, v = books
    entry = parse(
        "52 kapital bank usd / 51 kapital bank 1000 Покупка валюты", cat, rate_for=rate, today=TODAY
    )
    [ln] = entry.lines
    usd = cat.value(v["Kapital Bank USD"]).currency_id
    assert (ln.currency_id, ln.currency_amount, ln.amount) == (usd, 100_000, 170_000)
    assert "1 000.00 USD × 1.7000 = 1 700.00" in describe(entry, cat)
    with pytest.raises(ValidationError, match="нет курса"):
        parse("52 kapital bank usd / 51 kapital bank 1000", cat, today=TODAY)
    with pytest.raises(ValidationError, match="без валютного учёта"):
        parse("50 / 80 10 usd", cat, rate_for=rate, today=TODAY)


def test_template_with_amount_and_subconto(books):
    conn, _, cid, cat, v = books
    templates = list_templates(conn, cid)
    entry = parse("#реализация 1180 бета, договор", cat, templates, today=TODAY)
    assert [ln.amount for ln in entry.lines] == [118_000, 18_000]  # 1180 × 18/118 = 180
    assert entry.lines[0].debit_sc[:2] == [v["Бета Сервис"], v["Договор №1"]]
    assert entry.memo == "Реализация с НДС"
    # 1180 with 18% VAT inside: 180 VAT, 1000 goods; supplier filled on every line
    entry = parse("#покупка тов 1180 альфа, договор", cat, templates, today=TODAY)
    assert [ln.amount for ln in entry.lines] == [100_000, 18_000]
    assert entry.lines[1].debit_sc[0] == v["Альфа Трейд"]  # 19 by counterparty
    assert all(ln.credit_sc[:2] == [v["Альфа Трейд"], v["Договор №1"]] for ln in entry.lines)
    assert any("41" in m for m in entry.missing)  # item and warehouse: in the form
    with pytest.raises(ValidationError, match="нескольким шаблонам"):
        parse("#покупка 10", cat, templates, today=TODAY)


@pytest.fixture
def bar(qtbot, books):
    theme.apply(QApplication.instance())
    conn, ledger, cid, cat, _ = books
    messages: list[str] = []
    s = Session(conn, ledger, cid, "Firma", cat, notify=messages.append)
    s.working_date = TODAY
    widget = QuickEntryBar(s)
    qtbot.addWidget(widget)
    return widget


def test_enter_posts_and_clears(bar, qtbot):
    bar.edit.setText("26 аренда / 60 альфа, договор 400 Аренда за март")
    assert "Аренда офиса" in bar.card.text.text() and bar.card.isVisibleTo(bar)
    posted = []
    bar.posted.connect(posted.append)
    qtbot.keyClick(bar.edit, Qt.Key.Key_Return)
    doc = load_document(bar.s.conn, bar.s.company_id, posted[0])
    assert (doc.status, doc.doc_date, doc.memo) == ("posted", "2026-03-05", "Аренда за март")
    assert bar.edit.text() == ""
    qtbot.keyClick(bar.edit, Qt.Key.Key_Up)  # the last line comes back
    assert bar.edit.text().startswith("26 аренда")


def test_amount_after_a_counterparty_from_the_list_posts_with_enter(bar, qtbot):
    """Taking «Альфа Трейд» adds ", " for the contract; the amount typed there is the
    amount: Enter posts, it does not add a contract «400»."""
    bar.show()
    qtbot.waitExposed(bar)
    bar.edit.setFocus()
    bar.edit.setText("26 Аренда офиса / 60 ")
    bar.edit.textEdited.emit(bar.edit.text())
    bar.take(next(i.label for i in bar._found.items if "Альфа" in i.label))
    assert bar.edit.text() == "26 Аренда офиса / 60 Альфа Трейд, "
    bar.edit.insert("400")
    bar.edit.textEdited.emit(bar.edit.text())
    posted = []
    bar.posted.connect(posted.append)
    popup = bar.completer.popup()  # an open list gets the keys first, as on the screen
    qtbot.keyClick(popup if popup.isVisible() else bar.edit, Qt.Key.Key_Return)
    [doc_id] = posted
    doc = load_document(bar.s.conn, bar.s.company_id, doc_id)
    assert doc.postings[0].amount == 40_000
    assert [v.name for v in bar.s.catalog.values(bar.s.catalog.by_code["60"].sc_kinds[1])] == [
        "Договор №1"
    ]  # no contract «400»


def test_enter_on_an_open_list_with_nothing_chosen_is_the_line_s(bar, qtbot, books):
    """«60 12345» finds Альфа by its VÖEN, but nothing is chosen: Enter posts the line
    (here it is refused — 60 needs a counterparty), it does not take Альфа."""
    _conn, ledger, cid, _cat, v = books
    ledger.set_subconto_value_tax(cid, v["Альфа Трейд"], "1234567890")
    bar.s.catalog.reload()
    bar.show()
    qtbot.waitExposed(bar)
    bar.edit.setFocus()
    bar.edit.setText("26 Аренда офиса / 60 Альфа Трейд, ")  # the list had a choice before
    bar.edit.textEdited.emit(bar.edit.text())
    bar.edit.setText("26 Аренда офиса / 60 12345")
    bar.edit.textEdited.emit(bar.edit.text())
    popup = bar.completer.popup()
    assert popup.isVisible() and not popup.currentIndex().isValid()
    qtbot.keyClick(popup, Qt.Key.Key_Return)
    assert bar.edit.text() == "26 Аренда офиса / 60 12345"
    assert bar.preview.objectName() == "error"


def test_a_word_brings_back_the_last_posting_with_its_amount_to_type_over(bar, qtbot):
    """hledger add / QuickFill: «альф» → the rent posting of last time, 400 selected;
    typing 450 replaces it and Enter posts."""
    bar.edit.setText("26 аренда / 60 альфа, договор 400 Аренда за март")
    qtbot.keyClick(bar.edit, Qt.Key.Key_Return)
    bar.edit.insert("альф")
    bar.edit.textEdited.emit(bar.edit.text())
    first = bar._found.items[0]
    assert first.label.startswith("26 Аренда офиса / 60 Альфа Трейд, Договор №1")
    assert bar._found.typed  # Enter takes it
    bar.take(first.label)
    assert bar.edit.text() == "26 Аренда офиса / 60 Альфа Трейд, Договор №1 400 Аренда за март"
    assert bar.edit.selectedText() == "400"
    bar.edit.insert("450")
    assert bar.edit.text().endswith("Договор №1 450 Аренда за март")
    posted = []
    bar.posted.connect(posted.append)
    qtbot.keyClick(bar.edit, Qt.Key.Key_Return)
    doc = load_document(bar.s.conn, bar.s.company_id, posted[0])
    assert (doc.postings[0].amount, doc.memo) == (45_000, "Аренда за март")


def test_past_postings_found_by_every_word_newest_first(books):
    conn, ledger, cid, cat, v = books
    rent = PostingInput(
        cat.by_code["26"].id,
        cat.by_code["60"].id,
        from_minor(40_000),
        (v["Аренда офиса"], None, None),
        (v["Альфа Трейд"], v["Договор №1"], None),
        "Аренда",
    )
    ledger.post_new(cid, TODAY, [rent], "Аренда")
    ledger.post_new(cid, TODAY, [replace(rent, amount=from_minor(42_000))], "Аренда")
    cash = PostingInput(cat.by_code["50"].id, cat.by_code["80"].id, from_minor(100_000))
    ledger.post_new(cid, TODAY, [cash], "Вклад")
    history = past_postings(conn, cid)
    assert [p.amount for p in history] == [100_000, 42_000]  # one per Dt/Kt and subconto
    assert [line for _, line, _ in past_lines("альфа ар", cat, history)] == [
        "26 Аренда офиса / 60 Альфа Трейд, Договор №1 420 Аренда"
    ]
    assert past_lines("бета", cat, history) == []
    assert past_lines("26", cat, history) == []  # an account code: the accounts list
    [(_, line, (a, b))] = past_lines("вкл", cat, history)
    assert line[a:b] == "1000"


def test_shift_enter_saves_a_draft_and_plus_adds_elements(bar, qtbot):
    bar.edit.setText("26 +Реклама / 50 15")
    posted = []
    bar.posted.connect(posted.append)
    qtbot.keyClick(bar.edit, Qt.Key.Key_Return, Qt.KeyboardModifier.ShiftModifier)
    doc = load_document(bar.s.conn, bar.s.company_id, posted[0])
    assert doc.status == "draft"
    assert bar.s.catalog.value(doc.postings[0].debit_subconto[0]).name == "Реклама"


def test_problem_is_shown_and_nothing_is_saved(bar, qtbot):
    bar.edit.setText("71 / 50 100")  # 71 needs an employee
    qtbot.keyClick(bar.edit, Qt.Key.Key_Return)
    assert "не заполнено" in bar.preview.text()
    assert bar.edit.text() == "71 / 50 100"  # kept to fix
    assert bar.preview.objectName() == "error"


def test_ctrl_enter_opens_the_form(bar, qtbot):
    bar.edit.setText("71 / 50 100 Под отчёт")
    forms = []
    bar.open_form.connect(forms.append)
    qtbot.keyClick(bar.edit, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)
    [doc] = forms
    assert doc.memo == "Под отчёт" and doc.postings[0].amount == 10_000


def test_in_the_window_ctrl_l_and_enter_post_without_opening_a_document(
    qtbot, tmp_path, monkeypatch
):
    from PySide6.QtWidgets import QMessageBox

    from modern_gl.demo_data import create_demo_company
    from modern_gl.desktop.main_window import MainWindow
    from modern_gl.infrastructure.workspace import Workspace

    monkeypatch.setattr(
        QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Discard)
    )
    ws = Workspace(tmp_path / "data")
    path = ws.new_path("Demo")
    c = connect(path)
    create_demo_company(Ledger(c))
    c.close()
    theme.apply(QApplication.instance())
    win = MainWindow(ws)
    qtbot.addWidget(win)
    win.start()
    win.session.working_date = TODAY
    win.show_place(("journal",))
    win.show()
    win.activateWindow()
    qtbot.waitUntil(win.isActiveWindow)
    journal = win.pages[("journal",)]
    before = journal.model.rowCount()
    qtbot.keyClick(win, Qt.Key.Key_L, Qt.KeyboardModifier.ControlModifier)
    assert QApplication.focusWidget() is journal.quick.edit
    journal.quick.edit.setText("50 / 80 10 Тест")
    qtbot.keyClick(journal.quick.edit, Qt.Key.Key_Return)
    assert journal.model.rowCount() == before + 1
    assert win.stack.currentWidget() is journal  # no document page was opened
    win.shutdown()


def marked(text: str, cat: Catalog) -> list[tuple[str, str]]:
    return [(text[m.start : m.end], m.kind) for m in marks(text, cat, today=TODAY)]


def test_parts_of_the_line_are_marked_where_they_are(books):
    *_, cat, _v = books
    assert marked("05.03 26 аренда / 60 альфа, +Новый 1234,50 USD Аренда за март", cat) == [
        ("05.03", "date"),
        ("26", "account"),
        ("аренда", "value"),
        ("60", "account"),
        ("альфа", "value"),
        ("+Новый", "new"),
        ("1234,50", "amount"),
        ("USD", "currency"),
    ]  # the memo is not marked
    assert marked("26 нечто / 999 400", cat) == [
        ("26", "account"),
        ("нечто", "unknown"),
        ("999", "unknown"),
    ]
    assert marked("26 аренда / 60 Альфа Трейд, 400", cat)[-1] == ("400", "amount")
    assert marked("26 ар", cat) == [("26", "account"), ("ар", "value")]  # a unique part
    assert marked("50 / 51 1; 26 аренда / 50 2", cat)[-1] == ("2", "amount")


def test_colouring_the_line_keeps_its_text_cursor_and_selection(bar, qtbot):
    bar.show()
    qtbot.waitExposed(bar)
    bar.edit.setText("26 аренда / 60 альфа, договор 400 Аренда")
    bar.edit.setSelection(30, 3)
    bar._paint(bar.edit.text())
    assert bar.edit.text() == "26 аренда / 60 альфа, договор 400 Аренда"
    assert bar.edit.selectedText() == "400"


def test_card_shows_what_is_missing_and_what_is_new_in_place(books):
    *_, cat, _v = books
    entry = parse("26 аренда / 60 +Дельта 400; 71 / 50 15 Такси", cat, today=TODAY)
    rent, taxi = card(entry, cat)
    assert [(p.text, p.kind) for p in rent.credit] == [
        ("60", "account"),
        ("+Дельта", "new"),
        ("Договоры", "missing"),
    ]
    assert (rent.amount.text, taxi.memo) == ("400.00", "")  # «Такси» is the document's memo
    assert [p.kind for p in taxi.debit] == ["account", "missing"]
    entry = parse("52 kapital bank usd / 51 kapital bank 100 USD", cat, (), rate, TODAY)
    [usd] = card(entry, cat)
    assert (usd.amount.text, usd.in_manat) == ("100.00 USD", "× 1.7000 = 170.00")


def test_free_order_line_is_the_posting_of_last_time(books):
    """«альфа 450»: no "/", the words of a posting typed before and the amount."""
    conn, ledger, cid, cat, v = books
    rent = PostingInput(
        cat.by_code["26"].id,
        cat.by_code["60"].id,
        from_minor(40_000),
        (v["Аренда офиса"], None, None),
        (v["Альфа Трейд"], v["Договор №1"], None),
        "Аренда за март",
    )
    ledger.post_new(cid, TODAY, [rent], "Аренда за март")
    history = past_postings(conn, cid)
    [ln] = parse("альфа 450", cat, today=TODAY, history=history).lines
    assert (ln.debit, ln.credit, ln.amount, ln.memo) == (
        rent.debit_account_id,
        rent.credit_account_id,
        45_000,
        "Аренда за март",
    )
    assert ln.credit_sc[:2] == [v["Альфа Трейд"], v["Договор №1"]]
    [ln] = parse(
        "05.04 аренд альф 450,50 Аренда за апрель", cat, today=TODAY, history=history
    ).lines
    assert (ln.amount, ln.memo) == (45_050, "Аренда за апрель")
    with pytest.raises(ValidationError, match="разделяются"):
        parse("бета 450", cat, today=TODAY, history=history)  # nothing like it before
    assert marked_with(history, "альфа 450 Аренда", cat) == [
        ("альфа", "value"),
        ("450", "amount"),
    ]


def marked_with(history, text: str, cat: Catalog) -> list[tuple[str, str]]:
    return [(text[m.start : m.end], m.kind) for m in marks(text, cat, (), TODAY, history)]


def test_free_order_posts_with_enter_and_a_grey_place_opens_the_form(bar, qtbot):
    bar.edit.setText("26 аренда / 60 альфа, договор 400 Аренда за март")
    qtbot.keyClick(bar.edit, Qt.Key.Key_Return)
    bar.edit.setText("альфа 420")
    posted = []
    bar.posted.connect(posted.append)
    qtbot.keyClick(bar.edit, Qt.Key.Key_Return)
    doc = load_document(bar.s.conn, bar.s.company_id, posted[0])
    assert (doc.postings[0].amount, doc.memo) == (42_000, "Аренда за март")
    bar.edit.setText("71 / 50 100")  # 71 waits for an employee: grey, a link
    assert 'href="form"' in bar.card.text.text()
    forms = []
    bar.open_form.connect(forms.append)
    bar.card.text.linkActivated.emit("form")
    assert forms[0].postings[0].amount == 10_000
