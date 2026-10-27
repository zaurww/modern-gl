"""UI behaviour: keyboard entry flow, saving/posting from the form, navigation, reports."""

from datetime import date

import pytest
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QApplication,
    QCompleter,
    QDialog,
    QInputDialog,
    QMessageBox,
    QPushButton,
)

from modern_gl.application.ledger import PostingInput
from modern_gl.application.queries import load_document
from modern_gl.application.workspace import TRASH
from modern_gl.desktop import theme
from modern_gl.desktop.directories_page import DirectoriesPage
from modern_gl.desktop.document_page import DocumentPage
from modern_gl.desktop.main_window import SIDEBAR_KEYS, NavDelegate
from modern_gl.desktop.opening_balances_page import CREDIT_AMOUNT, OpeningBalancesPage
from modern_gl.desktop.postings import AMOUNT, CT, DT, MEMO, PostingRow
from modern_gl.desktop.reports_page import NAME_MAX, NAME_MIN, OsvPage, SectionRow, figure
from modern_gl.reporting.reports import trial_balance


@pytest.fixture
def workspace(desktop_workspace):
    return desktop_workspace


@pytest.fixture
def window(desktop_window):
    return desktop_window


def current_page(win):
    return win.stack.currentWidget()


def type_into_cell(qtbot, page: DocumentPage, row: int, col: int, text: str) -> None:
    table = page.table
    idx = page.model.index(row, col)
    table.setCurrentIndex(idx)
    table.edit(idx)
    editor = QApplication.focusWidget()
    editor.setText(text)
    qtbot.keyClick(editor, Qt.Key.Key_Return)


def test_opens_on_journal_with_demo_documents(window):
    page = current_page(window)
    assert page.title() == "Журнал"
    assert page.model.rowCount() == 13
    assert window.windowTitle().startswith("ДЕМО ООО")


def test_opening_balances_have_their_own_page(window):
    window.show_place(("opening",))
    page = current_page(window)
    assert isinstance(page, OpeningBalancesPage)
    cat = window.session.catalog

    model = page.model
    model.setData(model.index(0, DT), cat.by_code["50"].id)
    model.setData(model.index(0, AMOUNT), 100_000)
    model.insert_row()
    model.setData(model.index(1, DT), cat.by_code["80"].id)
    assert model.rows[1].on_credit  # a capital account starts in "Кредит"
    model.setData(model.index(1, CREDIT_AMOUNT), 100_000)
    assert model.totals() == (100_000, 100_000)
    assert page.btn_difference.isHidden()

    assert page.save(post=True)
    assert page.status.text() == "Проведён"
    reloaded = [(r.debit, r.amount, r.on_credit) for r in page.model.rows]
    assert reloaded == [
        (cat.by_code["50"].id, 100_000, False),
        (cat.by_code["80"].id, 100_000, True),
    ]
    rows = {
        row.code: row
        for row in trial_balance(
            window.session.conn, window.session.company_id, "2026-01-01", "2026-01-31"
        ).rows
    }
    assert rows["50"].opening_dt == 100_000
    assert rows["80"].opening_ct == 100_000
    assert page.doc_id is not None
    window.copy_document(page.doc_id)
    assert current_page(window) is page


def test_opening_balances_paste_from_trial_balance_and_close_difference(window):
    window.show_place(("opening",))
    page = current_page(window)
    assert isinstance(page, OpeningBalancesPage)
    cat = window.session.catalog
    QApplication.clipboard().setText("Счёт\tДебет\tКредит\n50\t1 500,00\t\n80\t\t1000\n")

    page.paste()

    model = page.model
    rows = [r for r in model.rows if not r.is_empty()]
    assert [(r.debit, r.amount, r.on_credit) for r in rows] == [
        (cat.by_code["50"].id, 150_000, False),
        (cat.by_code["80"].id, 100_000, True),
    ]
    assert page.difference.text() == "500.00"
    assert not page.btn_difference.isHidden()

    page.close_difference()  # Kt 500 on a line whose account is still to choose
    last = model.rows[-1]
    assert (last.amount, last.on_credit) == (50_000, True)
    model.setData(model.index(len(model.rows) - 1, DT), cat.by_code["80"].id)
    assert model.totals() == (150_000, 150_000)


def test_keyboard_entry_skips_subconto_cells_that_do_not_apply(window, qtbot):
    window.new_document()
    page = current_page(window)
    model, table = page.model, page.table

    type_into_cell(qtbot, page, 0, DT, "26")  # 26 has one subconto: cost item
    assert model.rows[0].debit == window.session.catalog.by_code["26"].id
    assert table.currentIndex().column() == DT + 1  # moved to its subconto

    editor = QApplication.focusWidget()
    editor.setText("аренда")
    qtbot.keyClick(editor, Qt.Key.Key_Return)
    assert model.data(model.index(0, DT + 1)) == "Аренда офиса"
    assert table.currentIndex().column() == CT  # subconto 2 of 26 is skipped

    editor = QApplication.focusWidget()
    editor.setText("50")
    qtbot.keyClick(editor, Qt.Key.Key_Return)  # 50 has no subconto
    assert table.currentIndex().column() == AMOUNT

    editor = QApplication.focusWidget()
    editor.setText("1 234,50")
    qtbot.keyClick(editor, Qt.Key.Key_Return)
    assert model.rows[0].amount == 123450
    assert table.currentIndex().column() == MEMO

    editor = QApplication.focusWidget()
    qtbot.keyClick(editor, Qt.Key.Key_Return)  # Enter on the last cell: new row
    assert model.rowCount() == 2
    assert table.currentIndex() == model.index(1, DT)
    assert page.total.text() == "1 234.50"


def test_group_account_is_refused_with_a_hint(window, qtbot):
    window.new_document()
    page = current_page(window)
    type_into_cell(qtbot, page, 0, DT, "68")
    assert page.model.rows[0].debit is None
    assert "68 — группа: выберите субсчёт" in page.error.text()


def test_changing_account_clears_incompatible_subconto(window):
    window.new_document()
    page = current_page(window)
    m, cat = page.model, window.session.catalog
    m.setData(m.index(0, CT), cat.by_code["60"].id)
    alfa = next(v.id for v in cat.values(cat.by_code["60"].sc_kinds[0]) if "Альфа" in v.name)
    m.setData(m.index(0, CT + 1), alfa)
    m.setData(m.index(0, CT), cat.by_code["62"].id)  # same kind: counterparty stays
    assert m.rows[0].credit_sc[0] == alfa
    m.setData(m.index(0, CT), cat.by_code["26"].id)  # cost item: cleared
    assert m.rows[0].credit_sc == [None, None, None]
    assert not m.flags(m.index(0, CT + 2)) & Qt.ItemFlag.ItemIsEnabled


def test_post_from_form_updates_journal_and_reports(window):
    window.new_document()
    page = current_page(window)
    cat = window.session.catalog
    page.memo.setText("Пополнение кассы")
    page.model.rows = [
        PostingRow(
            debit=cat.by_code["50"].id,
            credit=cat.by_code["51"].id,
            credit_sc=[cat.values(cat.by_code["51"].sc_kinds[0])[0].id, None, None],
            amount=50000,
        )
    ]
    assert page.save(post=True)
    assert page.status.text() == "Проведён"
    assert not page.model.read_only  # edited in place, as in 1C
    assert page.btn_save.isHidden()  # no "draft" for a posted document
    assert window.sidebar.item_for(("doc", page.doc_id)).text() == "Документ №14"

    journal = window.pages[("journal",)]
    assert journal.model.docs[-1].memo == "Пополнение кассы"
    osv = trial_balance(window.conn, window.session.company_id, "2026-03-01", "2026-03-31")
    assert {r.code: r.turnover_dt for r in osv.rows}["50"] == 50000


def test_posting_says_so_in_a_toast_and_undo_makes_a_draft_again(window):
    """D86: no status bar — a toast at the bottom; «Undo» takes the posting back."""
    window.new_document()
    page = current_page(window)
    cat = window.session.catalog
    page.model.rows = [
        PostingRow(
            debit=cat.by_code["50"].id,
            credit=cat.by_code["51"].id,
            credit_sc=[cat.values(cat.by_code["51"].sc_kinds[0])[0].id, None, None],
            amount=50000,
        )
    ]
    assert page.save(post=True)
    assert window.toast.message() == "Документ №14 проведён"
    assert window.toast.undo_button.isVisibleTo(window.toast)
    assert window.statusBar().currentMessage() == ""
    doc_id = page.doc_id
    window.toast.undo_button.click()
    assert load_document(window.conn, window.session.company_id, doc_id).status == "draft"
    assert page.status.text() == "Черновик"
    assert not window.toast.message()

    assert page.save(post=True)  # posted again; corrected in place has no «Undo»
    page.memo.setText("Исправлено")
    assert page.save(post=True)
    assert not window.toast.undo_button.isVisibleTo(window.toast)


def test_post_errors_are_shown_and_nothing_is_lost(window):
    window.new_document()
    page = current_page(window)
    cat = window.session.catalog
    page.model.rows = [
        PostingRow(debit=cat.by_code["26"].id, credit=cat.by_code["50"].id, amount=100)
    ]  # 26 needs a cost item
    assert not page.save(post=True)
    assert "не заполнено «" in page.error.text()
    assert page.doc is None
    assert page.model.rows[0].amount == 100


def test_reverse_from_document_opens_storno(window, monkeypatch):
    journal = window.pages[("journal",)]
    first = journal.model.docs[0]
    window.open_document(first.id)
    page = current_page(window)
    monkeypatch.setattr(
        "modern_gl.desktop.document_page.page.ask_date", lambda *a, **k: date(2026, 3, 5)
    )
    page.reverse()
    storno = current_page(window)
    assert storno.doc.reversal_of == first.id
    assert storno.status.text() == "Сторно"
    assert page.status.text() == "Сторнирован"


def test_osv_drill_down_to_card_and_document(window):
    window.show_place(("osv",))
    osv = current_page(window)
    osv.period.set_period(date(2026, 2, 1), date(2026, 2, 28))
    osv.refresh()
    assert osv.footer.text().startswith("Дебет и кредит сходятся")
    row = next(r for r in osv.model.rows if r.code == "51")
    osv.drill(row)
    card = current_page(window)
    assert card.title() == "Карточка счёта 51"
    assert len(card.model.rows) == 5  # opening balance, 3 lines, turnovers and closing
    card.drill(card.model.rows[0])  # the balance row opens nothing
    assert current_page(window) is card
    card.drill(card.model.rows[1])
    assert isinstance(current_page(window), DocumentPage)


def test_books_switch_in_osv(window):
    window.show_place(("osv",))
    osv = current_page(window)
    osv.period.set_period(date(2026, 2, 1), date(2026, 2, 28))
    totals = []
    for book in (0, 1):
        osv.book.setCurrentIndex(book)
        osv.refresh()
        totals.append(next(r for r in osv.model.rows if r.code == "26").closing_dt)
    assert totals == [55000, 60000]


def test_closing_dirty_document_asks(window, monkeypatch):
    window.new_document()
    page = current_page(window)
    page.memo.setText("x")
    page.memo.textEdited.emit("x")
    assert page.is_dirty()
    asked = []
    monkeypatch.setattr(window.page_stack, "_confirm_close", lambda p: asked.append(p) or False)
    window.close_current()
    assert asked == [page]
    assert current_page(window) is page


def type_text(editor, text):
    """Type like a user would. (QTest.keyClicks crashes PySide on Windows for non-Latin
    characters, so Cyrillic/Azerbaijani letters are inserted and announced directly.)"""
    editor.insert(text)
    editor.textEdited.emit(editor.text())


def open_cell_editor(page, row, col):
    QApplication.processEvents()  # let the new document finish focusing its title first
    idx = page.model.index(row, col)
    page.table.setCurrentIndex(idx)
    page.table.edit(idx)
    QApplication.processEvents()  # the list opens on the next event loop turn
    editor = QApplication.focusWidget()
    return editor, editor.findChild(QCompleter)


def test_subconto_list_opens_at_once_and_filters_from_first_letter(window, qtbot):
    window.new_document()
    page = current_page(window)
    cat = window.session.catalog
    page.model.setData(page.model.index(0, CT), cat.by_code["60"].id)

    editor, completer = open_cell_editor(page, 0, CT + 1)
    popup = completer.popup()
    all_counterparties = len(cat.values(cat.by_code["60"].sc_kinds[0]))
    assert popup.isVisible()
    assert completer.model().rowCount() == all_counterparties  # whole directory, like 1C

    type_text(editor, "б")  # first letter already filters
    assert popup.isVisible()
    # a name not in the directory is offered last, to add it
    assert completer.model().stringList() == ["Бета Сервис", "+ Добавить «б»"]
    assert popup.currentIndex().row() == 0  # best match preselected

    qtbot.keyClick(popup, Qt.Key.Key_Return)
    assert page.model.data(page.model.index(0, CT + 1)) == "Бета Сервис"


def test_account_list_appears_while_typing(window, qtbot):
    window.new_document()
    page = current_page(window)
    editor, completer = open_cell_editor(page, 0, DT)
    assert not completer.popup().isVisible()  # empty account cell: no noise
    qtbot.keyClicks(editor, "68")
    assert completer.model().stringList()[:2] == [
        "68.1  Подоходный налог",
        "68.2  Налог на добавленную стоимость",
    ]


def test_group_typed_in_full_lists_its_accounts_and_enter_takes_none(window, qtbot):
    window.new_document()
    page = current_page(window)
    errors = []
    page.delegate.error.connect(errors.append)
    cat = window.session.catalog
    subs = [a.label for a in cat.subaccounts(cat.by_code["68"])]

    editor, completer = open_cell_editor(page, 0, DT)
    popup = completer.popup()
    qtbot.keyClicks(editor, "68")
    assert completer.model().stringList() == subs
    assert not popup.currentIndex().isValid()  # not 68.1 behind the user's back

    qtbot.keyClick(popup, Qt.Key.Key_Return)  # stays in the cell, the list again
    QApplication.processEvents()
    assert page.model.rows[0].debit is None
    assert QApplication.focusWidget() is editor
    assert errors == ["68 — группа: выберите субсчёт из списка"]
    assert popup.isVisible() and popup.currentIndex().row() == 0

    qtbot.keyClick(popup, Qt.Key.Key_Down)
    qtbot.keyClick(popup, Qt.Key.Key_Return)
    assert page.model.rows[0].debit == cat.by_code["68.2"].id


def test_group_found_by_code_name_or_label_only_in_full(window):
    cat = window.session.catalog
    group = cat.by_code["68"]
    for text in ("68", " расчёты С БЮДЖЕТОМ ", "68  Расчёты с бюджетом"):
        assert cat.group_named(text) == group
    for text in ("6", "Расчёты", "68.2", ""):  # a part, or a postable account
        assert cat.group_named(text) is None
    assert [a.code for a in cat.subaccounts(group)] == ["68.1", "68.2", "68.3", "68.9"]


def test_osv_top_level_only(window):
    window.show_place(("osv",))
    osv = current_page(window)
    osv.period.set_period(date(2026, 2, 1), date(2026, 2, 28))
    osv.top_only.setChecked(True)
    codes = [r.code for r in osv.model.rows]
    assert "68" in codes and "68.2" not in codes
    total = osv.model.rows[-1]
    assert osv.model.data(osv.model.index(len(osv.model.rows) - 1, 2)) == "" or (
        total.opening_dt != 0
    )


def test_close_cross_in_sidebar(window, qtbot):
    window.new_document()
    page = current_page(window)
    nav = window.sidebar.nav
    item = window.sidebar.item_for(page.key)
    cross = NavDelegate.close_rect(nav.visualItemRect(item)).center()
    qtbot.mouseClick(nav.viewport(), Qt.MouseButton.LeftButton, pos=cross)
    assert window.sidebar.item_for(page.key) is None
    assert current_page(window).title() == "Журнал"
    places = [window.sidebar.item_for(k) for k in SIDEBAR_KEYS]
    assert all(places)  # places can't be closed


def test_switch_language_rebuilds_interface(window):
    window.set_ui_language("az")
    try:
        assert current_page(window).title() == "Jurnal"
        assert window.sidebar.item_for(("osv",)).text() == "Dövriyyə-qalıq"
        assert "Ctrl+N  yeni sənəd" in window.sidebar.hint.text()
    finally:
        window.set_ui_language("ru")
    assert current_page(window).title() == "Журнал"


def test_osv_sections_by_class(window):
    window.show_place(("osv",))
    osv = current_page(window)
    osv.period.set_period(date(2026, 2, 1), date(2026, 2, 28))
    osv.sections.setChecked(True)
    rows = osv.model.rows
    headers = [r for r in rows if isinstance(r, SectionRow)]
    assert [h.name for h in headers] == ["Активы", "Обязательства", "Капитал", "Доходы", "Расходы"]
    total = rows[-1]
    assert sum(h.closing_dt for h in headers) == total.closing_dt
    assert sum(h.closing_ct for h in headers) == total.closing_ct
    assert not osv.menu_actions(headers[0])  # a section header is not an account


def test_chart_fits_the_window_without_sideways_scrolling(window):
    window.show_place(("chart",))
    chart = current_page(window)
    assert [c.title for c in chart.model.columns][:4] == ["Код", "Наименование", "Тип", "Сальдо"]
    for width, subconto_shown in ((1500, True), (1000, False)):
        window.resize(width, 820)
        window.show()
        QApplication.processEvents()
        assert chart.table.isColumnHidden(4) is not subconto_shown
        bar = chart.table.horizontalScrollBar()
        assert bar.maximum() == 0, width  # the type is never pushed off the edge
    window.resize(1900, 820)
    QApplication.processEvents()
    table = chart.table
    used = sum(table.columnWidth(i) for i in range(5))
    assert used < table.viewport().width() - 200  # the free room on the right, not after the name
    assert table.columnWidth(1) == table.content_width(1)  # the name as wide as its text


def test_change_type_from_chart_menu(window):
    window.show_place(("chart",))
    chart = current_page(window)
    acc = window.session.catalog.by_code["76"]
    menu = dict(e for e in chart.menu_actions(acc) if e is not None)
    types = dict(e for e in menu["Тип счёта"] if e is not None)
    assets = dict(e for e in types["     Активы"] if e is not None)
    assets["     Прочая дебиторская задолженность"]()
    changed = window.session.catalog.by_code["76"]
    assert (changed.account_class, changed.account_type) == ("asset", "other_receivable")
    row = next(a for a in chart.model.rows if a.code == "76")
    cell = chart.model.data(chart.model.index(chart.model.rows.index(row), 2))
    assert cell == "Прочая дебиторская задолженность"
    types = dict(e for e in chart.menu_actions(changed) if e is not None)["Тип счёта"]
    assets = dict(e for e in dict(e for e in types if e is not None)["✓  Активы"] if e)
    assets["     Активы"]()  # the class alone: the type is cleared, the class stays
    changed = window.session.catalog.by_code["76"]
    assert (changed.account_class, changed.account_type) == ("asset", None)


def test_open_reports_are_translated_in_sidebar(window):
    window.set_ui_language("az")
    try:
        osv = window.pages.get(("osv",)) or (window.show_place(("osv",)) or current_page(window))
        bank = window.session.catalog.by_code["51"].id
        window.open_report("card", bank, osv.params)
        assert window.sidebar.item_for(("card", bank)).text() == "Hesab kartı 51"
        assert current_page(window).header.title.text() == "Hesab kartı 51"
    finally:
        window.set_ui_language("ru")


def test_osv_expanded_by_subconto(window):
    window.show_place(("osv",))
    osv = current_page(window)
    osv.period.set_period(date(2026, 2, 1), date(2026, 2, 28))
    osv.expand.setChecked(True)
    rows = osv.model.rows
    i = next(i for i, r in enumerate(rows) if r.code == "60")
    under = [r for r in rows[i + 1 :] if r.account_id == rows[i].account_id and r.subconto]
    parties = [r for r in under if len(r.subconto) == 1]  # their contracts under them (D110)
    assert [r.name.strip() for r in parties] == ["Альфа Трейд", "Бета Сервис"]
    assert any(len(r.subconto) == 2 for r in under)
    assert sum(r.closing_ct for r in parties) == rows[i].closing_ct
    assert rows[-1].closing_dt == rows[-1].closing_ct  # totals unchanged


def test_account_dialog_adds_subaccount_and_renames(window, monkeypatch):
    from modern_gl.desktop.account_dialog import AccountDialog

    window.show_place(("chart",))
    chart = current_page(window)
    cat = window.session.catalog

    def run(dialog_setup):
        def fake_exec(self):
            dialog_setup(self)
            self.save()
            return self.result()

        monkeypatch.setattr(AccountDialog, "exec", fake_exec)

    # 52 has no postings in the demo: its first subaccount turns it into a group
    def add_bank(d):
        assert d.code.text() == "52.1"
        d.name.setText("Kapital Bank USD")

    run(add_bank)
    chart.edit_account(None, cat.by_code["52"].id)
    assert cat.by_code["52"].is_group
    assert cat.by_code["52.1"].parent_id == cat.by_code["52"].id
    assert cat.by_code["52.1"].account_class == "asset"  # inherited
    assert cat.by_code["52.1"].account_type == "bank"

    def make_loan(d):  # the type picker: the class follows the type
        d.account_type.setCurrentIndex(d.account_type.findData("short_term_loan"))

    run(make_loan)
    chart.edit_account(cat.by_code["52.1"])
    loan = window.session.catalog.by_code["52.1"]
    assert (loan.account_class, loan.account_type) == ("liability", "short_term_loan")

    def rename(d):
        d.name.setText("Kassa (AZN)")

    run(rename)
    chart.edit_account(cat.by_code["50"])
    assert window.session.catalog.by_code["50"].name == "Kassa (AZN)"

    def bad(d):
        d.group.setChecked(True)  # 51 has postings

    run(bad)
    chart.edit_account(cat.by_code["51"])
    assert not cat.by_code["51"].is_group


def test_osv_highlights_balance_on_wrong_side(window):
    led, s = window.ledger, window.session
    cat = s.catalog
    cost_item = cat.values(cat.by_code["26"].sc_kinds[0])[0].id
    # Spend 5 000 in cash when the cash box holds 1 750: Kassa goes into credit.
    led.post_new(
        s.company_id,
        "2026-02-27",
        [PostingInput(cat.by_code["26"].id, cat.by_code["50"].id, "5000", [cost_item])],
    )
    window.show_place(("osv",))
    osv = current_page(window)
    osv.period.set_period(date(2026, 2, 1), date(2026, 2, 28))
    osv.refresh()
    i = next(i for i, r in enumerate(osv.model.rows) if r.code == "50")
    closing_ct = osv.model.index(i, 7)
    assert osv.model.data(closing_ct) == "3 250.00"
    assert osv.model.data(closing_ct, Qt.ItemDataRole.ForegroundRole).name() == "#dc4446"
    assert "дебетовое" in osv.model.data(closing_ct, Qt.ItemDataRole.ToolTipRole)
    assert "50" in osv.footer.text()


def test_companies_are_files_and_can_be_switched(window, workspace, monkeypatch):
    monkeypatch.setattr(
        "modern_gl.desktop.main_window.company_files.QInputDialog.getText",
        staticmethod(lambda _w, _t, label, *a, **k: ("" if "VÖEN" in label else "Yeni MMC", True)),
    )
    monkeypatch.setattr(  # the whole program, not a warehouse only (D90)
        "modern_gl.desktop.main_window.company_files.QInputDialog.getItem",
        staticmethod(lambda _w, _t, _l, kinds, *a, **k: (kinds[0], True)),
    )
    offered = []
    monkeypatch.setattr(  # the file goes where it is offered: the data folder
        "modern_gl.desktop.main_window.company_files.QFileDialog.getSaveFileName",
        staticmethod(lambda _w, _t, path, _f: (offered.append(path) or path, "")),
    )
    assert window.create_company()
    assert offered == [str(workspace.folder / "Yeni MMC.gl")]
    assert window.session.company_name == "Yeni MMC"
    assert window.company_path == workspace.folder / "Yeni MMC.gl"
    assert current_page(window).title() == "Сегодня"  # a company opens on «Bu gün»
    window.show_place(("journal",))
    assert current_page(window).model.rowCount() == 0  # new company: empty journal
    assert [c.name for c in workspace.companies()] == ["Yeni MMC", "ДЕМО ООО"]
    demo = next(c for c in workspace.companies() if c.name == "ДЕМО ООО")
    window.open_company(demo.path)
    window.show_place(("journal",))
    assert current_page(window).model.rowCount() == 13
    # no page is left over from the company that was closed (its file is closed too)
    assert all(getattr(p, "s", window.session) is window.session for p in window.pages.values())
    window.show_place(("osv",))
    assert current_page(window).model.rowCount() > 0


def test_delete_company_needs_typed_name(window, workspace, monkeypatch):
    path = window.company_path
    monkeypatch.setattr(
        "modern_gl.desktop.main_window.company_files.confirm_delete", lambda *a: False
    )
    window.delete_company()
    assert path.exists()  # not confirmed: nothing happens

    monkeypatch.setattr(
        "modern_gl.desktop.main_window.company_files.confirm_delete", lambda *a: True
    )
    monkeypatch.setattr(
        "modern_gl.desktop.main_window.company_files.QInputDialog.getText",
        staticmethod(lambda *a, **k: ("", False)),  # user declines to create a new one
    )
    window.delete_company()
    assert not path.exists()
    assert len(list((workspace.folder / TRASH).glob("*.gl"))) == 1
    assert window.session is None
    assert window.sidebar.company.text().startswith("Нет компании")


def test_confirm_delete_dialog_unlocks_only_on_exact_name(qtbot, monkeypatch):
    from PySide6.QtWidgets import QDialog, QLineEdit, QPushButton

    from modern_gl.desktop.main_window import confirm_delete

    seen = {}

    def fake_exec(dialog):
        edit = dialog.findChild(QLineEdit)
        button = next(
            b for b in dialog.findChildren(QPushButton) if b.objectName() == "dangerSolid"
        )
        edit.setText("ДЕМО")
        seen["partial"] = button.isEnabled()
        edit.setText("ДЕМО ООО")
        seen["exact"] = button.isEnabled()
        return QDialog.DialogCode.Rejected

    monkeypatch.setattr(QDialog, "exec", fake_exec)
    assert confirm_delete(None, "ДЕМО ООО") is False
    assert seen == {"partial": False, "exact": True}


def test_delete_mistaken_storno_from_its_page(window, monkeypatch):
    journal = window.pages[("journal",)]
    original = journal.model.docs[0]
    window.open_document(original.id)
    monkeypatch.setattr(
        "modern_gl.desktop.document_page.page.ask_date", lambda *a, **k: date(2026, 3, 5)
    )
    current_page(window).reverse()
    storno_page = current_page(window)
    actions = [item[0] for item in storno_page.menu_items() if item]
    assert "Удалить" in actions and "Отменить проведение" not in actions
    monkeypatch.setattr(
        QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
    )
    storno_page.delete()
    assert window.sidebar.item_for(storno_page.key) is None
    window.open_document(original.id)
    page = current_page(window)
    page.load(original.id)
    assert page.status.text() == "Проведён"  # no longer "Сторнирован"


def test_unpost_from_page_makes_it_editable(window):
    # The second demo document is now generated by inventory and must be corrected
    # through the warehouse module; use an ordinary GL document for this workflow.
    doc = window.pages[("journal",)].model.docs[0]
    window.open_document(doc.id)
    page = current_page(window)
    assert not page.model.read_only  # posted, but editable in place
    page.unpost()
    assert not page.model.read_only
    assert page.status.text() == "Черновик"
    assert window.pages[("journal",)].model.docs[0].status == "draft"


def test_add_two_banks_in_directories(window, monkeypatch):
    window.show_place(("directories",))
    page = current_page(window)
    cat = window.session.catalog
    banks = cat.by_code["51"].sc_kinds[0]
    row = next(
        i
        for i in range(page.kinds.count())
        if page.kinds.item(i).data(Qt.ItemDataRole.UserRole) == banks
    )
    page.kinds.setCurrentRow(row)
    assert "51" in page.used_in.text()

    # banks are used on 52 (in currency): the dialog asks for a currency too
    from modern_gl.desktop.directories_page import ValueDialog

    answers = iter([("Kapital Bank USD", "USD"), ("ABB", None), ("ABB (AZN)", None)])

    def fill(dialog: ValueDialog) -> int:
        name, code = next(answers)
        dialog.name.setText(name)
        assert dialog.currency is not None
        dialog.currency.setCurrentIndex(
            next(
                i for i in range(dialog.currency.count()) if dialog.currency.itemText(i)[:3] == code
            )
            if code
            else 0
        )
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(ValueDialog, "exec", fill)
    page.add_value()
    page.add_value()
    cat = window.session.catalog
    names = {v.name: v.currency_id for v in cat.values(banks)}
    assert names["Kapital Bank USD"] == window.session.ledger.currency_id(
        window.session.company_id, "USD"
    )
    assert names["ABB"] is None

    # rename keeps history: postings reference the element by id
    abb = next(v for v in window.session.catalog.values(banks) if v.name == "ABB")
    page.rename_value(abb)
    assert window.session.catalog.value(abb.id).name == "ABB (AZN)"

    # hidden: not offered for entry any more, still known by id
    page.toggle_value(window.session.catalog.value(abb.id))
    assert "ABB (AZN)" not in [v.name for v in window.session.catalog.values(banks)]
    assert window.session.catalog.value(abb.id).name == "ABB (AZN)"
    assert window.session.catalog.resolve_value(banks, "ABB") is None


def test_add_directory_value_through_button_and_dialog(window, qtbot):
    """Regression: the visible button and its real input dialog add an item."""
    window.show_place(("directories",))
    page = current_page(window)
    kind_id = window.session.ledger.add_subconto_kind(window.session.company_id, None, "Проекты")
    window.session.catalog.reload()
    page.refresh(select_kind=kind_id)
    assert page.kind_id() == kind_id
    before = {v.id for v in window.session.catalog.all_values(kind_id)}

    def accept_dialog():
        dialog = next(w for w in QApplication.topLevelWidgets() if isinstance(w, QInputDialog))
        dialog.setTextValue("Новый элемент")
        dialog.accept()

    add = next(b for b in page.findChildren(QPushButton) if b.text() == "+ Новый элемент")
    QTimer.singleShot(0, accept_dialog)
    qtbot.mouseClick(add, Qt.MouseButton.LeftButton)

    values = window.session.catalog.all_values(kind_id)
    created = [v for v in values if v.id not in before]
    assert [v.name for v in created] == ["Новый элемент"]
    assert page.model.rowCount() == len(values)


def test_new_user_directory(window, monkeypatch):
    window.show_place(("directories",))
    page = current_page(window)
    monkeypatch.setattr(
        "modern_gl.desktop.directories_page.page.QInputDialog.getText",
        staticmethod(lambda *a, **k: ("Проекты", True)),
    )
    before = len(window.session.catalog.kinds)
    page.add_kind()
    assert len(window.session.catalog.kinds) == before + 1
    assert page.kind_title.text() == "Проекты"
    assert "не используется" in page.used_in.text()


@pytest.mark.parametrize("key", [Qt.Key.Key_Return, Qt.Key.Key_Tab])
def test_pick_from_open_list_with_arrows(window, qtbot, key):
    """Regression: arrows then Enter/Tab must take the highlighted item, not the empty text."""
    window.new_document()
    page = current_page(window)
    cat = window.session.catalog
    page.model.setData(page.model.index(0, CT), cat.by_code["60"].id)
    editor, completer = open_cell_editor(page, 0, CT + 1)
    popup = completer.popup()
    assert popup.isVisible() and editor.text() == ""
    qtbot.keyClick(popup, Qt.Key.Key_Down)
    qtbot.keyClick(popup, Qt.Key.Key_Down)
    picked = popup.currentIndex().data()
    qtbot.keyClick(popup, key)
    assert page.model.data(page.model.index(0, CT + 1)) == picked == "Бета Сервис"
    assert page.table.currentIndex().column() == CT + 2  # moved on to the contract


def test_f9_copies_row_and_ctrl_s_saves_while_a_cell_is_edited(window, qtbot):
    window.new_document()
    page = current_page(window)
    type_into_cell(qtbot, page, 0, DT, "50")
    editor = QApplication.focusWidget()  # 1C-style entry: the next cell is already open
    editor.setText("51")
    qtbot.keyClick(editor, Qt.Key.Key_F9)  # what was typed is kept, then the row copied
    assert page.model.rowCount() == 2
    bank = window.session.catalog.by_code["51"].id
    assert page.model.rows[0].credit == page.model.rows[1].credit == bank

    for row in page.model.rows:
        row.amount = 10000
    page.table.edit(page.model.index(1, MEMO))
    qtbot.keyClick(QApplication.focusWidget(), Qt.Key.Key_S, Qt.KeyboardModifier.ControlModifier)
    assert page.doc is not None, page.error.text()  # saved as a draft
    assert page.status.text() == "Черновик"


def test_document_from_template_follows_operation_amount(window, qtbot):
    window.show_place(("templates",))
    templates = current_page(window)
    sale = next(t for t in templates.model.rows if t.name == "Реализация с НДС")
    templates.use_template.emit(sale.id)
    page = current_page(window)
    assert isinstance(page, DocumentPage)
    assert page.memo.text() == "Реализация с НДС"
    assert page.amount.isVisible()

    type_text(page.amount, "1 180,00")
    assert [r.amount for r in page.model.rows] == [118000, 18000]
    page.model.setData(page.model.index(1, AMOUNT), 17000)  # typed by hand: stays
    page.amount.clear()
    type_text(page.amount, "2360")
    assert [r.amount for r in page.model.rows] == [236000, 17000]

    cat = window.session.catalog
    kinds = cat.by_code["62"].sc_kinds
    page.model.rows[0].debit_sc = [cat.values(kinds[0])[0].id, cat.values(kinds[1])[0].id, None]
    assert page.save(post=True), page.error.text()
    osv = trial_balance(window.conn, window.session.company_id, "2026-03-01", "2026-03-31")
    assert {r.code: r.turnover_ct for r in osv.rows}["68.2"] == 17000


def test_make_template_from_document_and_edit_formula(window, monkeypatch):
    monkeypatch.setattr(
        "modern_gl.desktop.document_page.templates.QInputDialog.getText",
        staticmethod(lambda *a, **k: ("Kassaya mədaxil", True)),
    )
    window.new_document()
    page = current_page(window)
    cat = window.session.catalog
    bank = cat.values(cat.by_code["51"].sc_kinds[0])[0].id
    page.model.rows = [
        PostingRow(
            debit=cat.by_code["50"].id,
            credit=cat.by_code["51"].id,
            credit_sc=[bank, None, None],
            amount=50000,
        ),
        PostingRow(debit=cat.by_code["26"].id, credit=cat.by_code["50"].id, amount=1500),
    ]
    page.save_as_template()
    editor = current_page(window)
    assert editor.name.text() == "Kassaya mədaxil"
    assert [r.formula for r in editor.model.rows] == ["S", "15.00"]
    assert editor.model.rows[0].credit_sc[0] == bank  # subconto kept

    editor.model.setData(editor.model.index(1, AMOUNT), "S*3/100")
    assert "1 000.00" in editor.preview.text() and "30.00" in editor.preview.text()
    assert editor.save()
    templates = current_page(window)
    assert templates.title() == "Шаблоны"
    saved = next(t for t in templates.model.rows if t.name == "Kassaya mədaxil")
    assert [ln.formula for ln in saved.lines] == ["S", "S*3/100"]


def test_osv_amounts_stand_next_to_the_names(window, qtbot):
    """Jon Moon: a table as wide as its content, not the window; a narrow window cuts
    the names first; nothing is an empty cell, a negative is in brackets."""
    page = OsvPage(window.session)
    qtbot.addWidget(page)
    page.resize(1600, 700)
    page.show()
    qtbot.waitUntil(lambda: page.table.viewport().width() > 1400)
    table = page.table
    names = next(i for i, c in enumerate(page.model.columns) if not c.width and not c.money)
    assert table.horizontalHeader().length() < table.viewport().width() - 200
    assert table.columnWidth(names) <= NAME_MAX
    wide = table.columnWidth(names)
    page.table.setMaximumWidth(700)  # the table of a narrow window
    qtbot.waitUntil(lambda: table.columnWidth(names) < wide)
    assert table.columnWidth(names) >= min(wide, NAME_MIN)
    assert [figure(None), figure(0), figure(12345), figure(-12345)] == [
        "",
        "",
        "123.45",
        "(123.45)",
    ]
    # no zebra rows unless turned on (D103); then soft ones, the total not banded
    from modern_gl.desktop.reports_page.table import set_zebra

    rows = len(page.model.rows)
    assert not any(page.model.banded)
    set_zebra(True)
    page.refresh()
    qtbot.waitUntil(lambda: any(page.model.banded))
    assert page.model.banded == [i % 2 == 1 for i in range(rows - 1)] + [False]


def test_report_grid_and_currency_rows(window, qtbot):
    """D127: the pale grid is on until turned off; a row in a currency has its own
    color, not the grey of a subaccount."""
    from modern_gl.desktop.reports_page.osv import CurrencyLine
    from modern_gl.desktop.reports_page.table import grid, set_grid

    assert grid()
    page = OsvPage(window.session)
    qtbot.addWidget(page)
    set_grid(False)
    assert not grid()
    set_grid(True)
    line = CurrencyLine(name="USD", depth=1)
    assert page.model.tone(line) == "currency"
    assert page.model.tone(page.model.rows[0]) is None


def test_theme_switches_at_once_and_keeps_the_company(window):

    try:
        window.set_ui_theme("craft")
        assert theme.current_theme() == "craft"
        assert theme.P.canvas == theme.THEMES["craft"][1]["canvas"]
        assert window.session.company_name == "ДЕМО ООО"  # the same company, pages anew
        assert current_page(window).model.rowCount() == 13
    finally:
        theme.set_theme(theme.DEFAULT_THEME)
    assert theme.P.canvas == "#FFFFFF"


def test_system_theme_follows_the_system_light_or_dark(window, monkeypatch):
    """«As the system» (the default, D86): Things when the system is light, Catppuccin
    Mocha when it turns dark — at once, the company stays open."""

    dark = False
    monkeypatch.setattr(theme, "system_is_dark", lambda: dark)
    try:
        assert theme.DEFAULT_THEME == theme.SYSTEM_THEME
        window.set_ui_theme("craft")
        window.set_ui_theme(theme.SYSTEM_THEME)
        assert theme.shown_theme() == "things"
        assert theme.P.canvas == "#FFFFFF"
        dark = True
        window.follow_system_theme()
        assert theme.current_theme() == theme.SYSTEM_THEME
        assert theme.shown_theme() == "catppuccin_mocha"
        assert theme.P.window == theme.THEMES["catppuccin_mocha"][1]["window"]
        assert current_page(window).model.rowCount() == 13
        window.set_ui_theme("craft")
        window.follow_system_theme()  # a chosen theme does not follow the system
        assert theme.shown_theme() == "craft"
    finally:
        theme.set_theme(theme.DEFAULT_THEME)


def test_every_theme_colors_the_whole_stylesheet():
    """A theme names only palette colors, and the stylesheet takes every color from the
    palette: no hardcoded white or grey is left in a dark theme."""
    import re
    from dataclasses import fields

    names = {f.name for f in fields(theme.Palette)}
    try:
        for name, (_, changes) in theme.THEMES.items():
            assert set(changes) <= names, name
            theme.set_theme(name)
            palette = {getattr(theme.P, n).upper() for n in names}
            used = {c.upper() for c in re.findall(r"#[0-9A-Fa-f]{6}", theme.stylesheet())}
            assert used <= palette, (name, used - palette)
    finally:
        theme.set_theme(theme.DEFAULT_THEME)


def test_posted_document_is_corrected_in_place(window):
    """From the journal (or a report) a posted document opens editable; posting it again
    keeps its number."""
    doc = window.pages[("journal",)].model.docs[0]
    window.open_document(doc.id)
    page = current_page(window)
    number = page.doc.number
    page.memo.setText("Исправлено")
    assert page.save(post=True)
    assert (page.doc.number, page.doc.status, page.doc.memo) == (number, "posted", "Исправлено")


def test_warehouse_postings_open_the_warehouse_document(window):
    s = window.session
    linked = s.conn.execute(
        "SELECT id, gl_document_id FROM inventory_documents WHERE gl_document_id IS NOT NULL"
    ).fetchone()
    if linked is None:
        pytest.skip("demo company has no warehouse documents")
    window.open_document(linked["gl_document_id"])
    assert current_page(window).key == ("inventory_doc", linked["id"])
    window.show_document(linked["gl_document_id"])
    page = current_page(window)
    assert page.model.read_only and not page.btn_source.isHidden()


def test_escape_returns_to_the_list_the_document_was_opened_from(window, qtbot):
    from modern_gl.desktop.trade_page import TradePage

    window.show_place(("purchases",))
    purchases = current_page(window)
    assert isinstance(purchases, TradePage)
    purchases.new_button.click()
    page = current_page(window)
    assert page is not purchases
    table = page.table
    table.setFocus()
    table.setCurrentIndex(table.model().index(0, 0))
    table.edit(table.currentIndex())
    editor = QApplication.focusWidget()
    qtbot.keyClick(editor, Qt.Key.Key_Escape)  # the first Esc only leaves the cell
    assert current_page(window) is page
    qtbot.keyClick(table, Qt.Key.Key_Escape)
    assert current_page(window) is purchases
    assert window.sidebar.item_for(page.key) is None


def test_cut_cell_text_is_shown_whole_under_the_mouse(window, monkeypatch):
    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QHelpEvent
    from PySide6.QtWidgets import QToolTip

    window.new_document()
    table = current_page(window).table
    model = table.model()
    model.setData(model.index(0, MEMO), "Очень длинное содержание операции " * 4)
    model.setData(model.index(0, AMOUNT), 500)
    shown = []
    monkeypatch.setattr(QToolTip, "showText", lambda _pos, text, *_a: shown.append(text))
    monkeypatch.setattr(QToolTip, "hideText", lambda: shown.append(None))

    def hover(column):
        pos = table.visualRect(model.index(0, column)).center()
        event = QHelpEvent(QEvent.Type.ToolTip, pos, table.viewport().mapToGlobal(pos))
        QApplication.sendEvent(table.viewport(), event)

    table.setColumnWidth(MEMO, 80)
    hover(MEMO)
    hover(AMOUNT)
    assert shown == ["Очень длинное содержание операции " * 4, None]


def test_directories_show_counterparties_added_elsewhere_on_return(window):
    """Drafts from the portal add counterparties while the directories page is open
    already: going back to it shows them at once, the row chosen stays chosen."""
    s = window.session
    window.show_place(("directories",))
    page = current_page(window)
    assert isinstance(page, DirectoriesPage)
    kind = s.ledger.subconto_kind_id(s.company_id, "counterparty")
    page.refresh(select_kind=kind)
    page.table.setCurrentIndex(page.model.index(0, 0))
    chosen = page._current_value()
    assert chosen is not None
    window.show_place(("journal",))

    new_id = s.ledger.add_subconto_value(s.company_id, kind, "Portal MMC")
    s.catalog.reload()  # as the e-qaimə import does
    window.show_place(("directories",))

    assert page.kind_id() == kind
    names = [page.model.index(r, 0).data() for r in range(page.model.rowCount())]
    assert "Portal MMC" in names
    assert new_id in {v.id for v in s.catalog.all_values(kind)}
    current = page._current_value()
    assert current is not None and current.id == chosen.id


def test_journal_done_rows_quieter_no_italics(window):
    """D86: a posted row's text is a bit quieter than a draft's; nothing in italics."""
    from modern_gl.desktop.journal_page import MEMO as JOURNAL_MEMO
    from modern_gl.desktop.journal_page import TOTAL
    from modern_gl.desktop.theme import P

    model = current_page(window).model
    draft = next(i for i, d in enumerate(model.docs) if d.status == "draft")
    posted = next(i for i, d in enumerate(model.docs) if d.status == "posted")
    fg = Qt.ItemDataRole.ForegroundRole
    for col in (JOURNAL_MEMO, TOTAL):
        assert model.data(model.index(posted, col), fg).name().upper() == P.muted.upper()
        assert model.data(model.index(draft, col), fg) is None
        assert model.data(model.index(draft, col), Qt.ItemDataRole.FontRole) is None


def test_sidebar_shows_the_last_open_pages_and_all_under_a_menu(window):
    """D86: «Open» keeps a few last pages; more — one item «All (N)…»."""
    from modern_gl.desktop.main_window.sidebar import ALL_OPEN, KEY_ROLE, OPEN_SHOWN

    docs = window.pages[("journal",)].model.docs
    for d in docs[:7]:
        window.open_document(d.id)
    nav = window.sidebar.nav
    items = [nav.item(i) for i in range(nav.count())]
    open_items = [i for i in items if NavDelegate.closable(i.data(KEY_ROLE))]
    assert len(open_items) == 7
    shown = [i.data(KEY_ROLE) for i in open_items if not i.isHidden()]
    assert len(shown) == OPEN_SHOWN
    assert set(shown) == set(window.recent[:OPEN_SHOWN])
    newest, oldest = window.recent[0], window.recent[-1]
    assert newest in shown and oldest not in shown
    all_item = window.sidebar.item_for(ALL_OPEN)
    assert all_item is not None and "7" in all_item.text()
    assert items[-1] is all_item
    # an old page shown again comes back among the visible ones
    window.page_stack.activate(oldest)
    assert not window.sidebar.item_for(oldest).isHidden()
    # closing down to the limit removes «All»
    for key in window.recent[OPEN_SHOWN:]:
        window.close_page(key, ask=False)
    assert window.sidebar.item_for(ALL_OPEN) is None


def test_sidebar_open_heading_only_with_open_pages(window):
    """With nothing open the heading «Open» is not shown; it comes with the first page."""
    nav = window.sidebar.nav
    heading = next(nav.item(i) for i in range(nav.count()) if nav.item(i).text() == "Открытые")
    for key in list(window.recent):
        window.close_page(key, ask=False)
    assert heading.isHidden()
    window.open_document(window.pages[("journal",)].model.docs[0].id)
    assert not heading.isHidden()


def test_closing_a_page_does_not_open_the_all_menu(window, monkeypatch):
    """Closing moves the current item; landing on «All (N)…» must not pop its menu."""
    from PySide6.QtWidgets import QMenu

    shown = []
    monkeypatch.setattr(QMenu, "exec", lambda *a, **k: shown.append(1))
    for d in window.pages[("journal",)].model.docs[:7]:
        window.open_document(d.id)
    window.close_current()
    assert shown == []


def test_closing_a_page_opens_only_the_page_it_came_from(window):
    """Esc on a card opened from the reports: back to the report, nothing else is built on
    the way. Taking the closed item out of the sidebar moved its current item to the next
    one (the warehouse…), which was opened and read first — Esc took seconds."""
    from modern_gl.desktop.main_window.navigator import Navigator

    window.show_place(("osv",))
    doc = window.pages[("journal",)].model.docs[0]
    window.open_document(doc.id)
    before = set(window.pages)
    made = []
    original = Navigator._make_place
    Navigator._make_place = lambda self, key: made.append(key) or original(self, key)
    try:
        window.close_current()
    finally:
        Navigator._make_place = original
    assert made == []
    assert window.page_stack.key_of(window.stack.currentWidget()) == ("osv",)
    assert set(window.pages) <= before
