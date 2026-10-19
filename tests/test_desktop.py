"""UI behaviour: keyboard entry flow, saving/posting from the form, navigation, reports."""

from datetime import date

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QCompleter, QMessageBox

from modern_gl.application.ledger import Ledger, PostingInput
from modern_gl.demo_data import create_demo_company
from modern_gl.desktop import theme
from modern_gl.desktop.document_page import DocumentPage
from modern_gl.desktop.main_window import PLACE_KEYS, MainWindow, NavDelegate
from modern_gl.desktop.postings import AMOUNT, CT, DT, MEMO, PostingRow
from modern_gl.infrastructure.db import connect
from modern_gl.infrastructure.workspace import TRASH, Workspace
from modern_gl.reporting.reports import trial_balance


@pytest.fixture(autouse=True)
def no_modal_dialogs(monkeypatch):
    """A modal dialog would block a headless test forever: answer 'discard/no'."""
    monkeypatch.setattr(
        QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Discard)
    )


@pytest.fixture
def workspace(tmp_path):
    ws = Workspace(tmp_path / "data")
    path = ws.new_path("ДЕМО ООО")
    conn = connect(path)
    create_demo_company(Ledger(conn))
    conn.close()
    return ws


@pytest.fixture
def window(qtbot, workspace):
    theme.apply(QApplication.instance())
    win = MainWindow(workspace)
    qtbot.addWidget(win)
    win.start()
    win.session.working_date = date(2026, 3, 5)
    win.show()
    yield win
    win.shutdown()


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
    assert page.model.rowCount() == 11
    assert window.windowTitle().startswith("ДЕМО ООО")


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
    type_into_cell(qtbot, page, 0, DT, "60")
    assert page.model.rows[0].debit is None
    assert "60.1, 60.2" in page.error.text()


def test_changing_account_clears_incompatible_subconto(window):
    window.new_document()
    page = current_page(window)
    m, cat = page.model, window.session.catalog
    m.setData(m.index(0, CT), cat.by_code["60.1"].id)
    alfa = next(v.id for v in cat.values(cat.by_code["60.1"].sc_kinds[0]) if "Альфа" in v.name)
    m.setData(m.index(0, CT + 1), alfa)
    m.setData(m.index(0, CT), cat.by_code["62.1"].id)  # same kind: counterparty stays
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
    assert page.model.read_only
    assert window.sidebar.find(("doc", page.doc_id)).text() == "Документ №12"

    journal = window.pages[("journal",)]
    assert journal.model.docs[-1].memo == "Пополнение кассы"
    osv = trial_balance(window.conn, window.session.company_id, "2026-03-01", "2026-03-31")
    assert {r.code: r.turnover_dt for r in osv.rows}["50"] == 50000


def test_post_errors_are_shown_and_nothing_is_lost(window):
    window.new_document()
    page = current_page(window)
    cat = window.session.catalog
    page.model.rows = [
        PostingRow(debit=cat.by_code["26"].id, credit=cat.by_code["50"].id, amount=100)
    ]  # 26 needs a cost item
    assert not page.save(post=True)
    assert "не заполнено субконто" in page.error.text()
    assert page.doc is None
    assert page.model.rows[0].amount == 100


def test_reverse_from_document_opens_storno(window, monkeypatch):
    journal = window.pages[("journal",)]
    first = journal.model.docs[0]
    window.open_document(first.id)
    page = current_page(window)
    monkeypatch.setattr(
        "modern_gl.desktop.document_page.ask_date", lambda *a, **k: date(2026, 3, 5)
    )
    page.reverse()
    storno = current_page(window)
    assert storno.doc.reversal_of == first.id
    assert storno.status.text() == "Сторно"
    assert page.status.text() == "Сторнирован"


def test_osv_drill_down_to_card_and_document(window):
    window.show_place(("osv",))
    osv = current_page(window)
    osv.date_from.setDate(date(2026, 2, 1))
    osv.date_to.setDate(date(2026, 2, 28))
    osv.refresh()
    assert osv.footer.text().startswith("Дебет и кредит сходятся")
    row = next(r for r in osv.model.rows if r.code == "51")
    osv.drill(row)
    card = current_page(window)
    assert card.title() == "Карточка счёта 51"
    assert len(card.model.rows) == 2
    card.drill(card.model.rows[0])
    assert isinstance(current_page(window), DocumentPage)


def test_books_switch_in_osv(window):
    window.show_place(("osv",))
    osv = current_page(window)
    osv.date_from.setDate(date(2026, 2, 1))
    osv.date_to.setDate(date(2026, 2, 28))
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
    monkeypatch.setattr(window, "_confirm_close", lambda p: asked.append(p) or False)
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
    page.model.setData(page.model.index(0, CT), cat.by_code["60.1"].id)

    editor, completer = open_cell_editor(page, 0, CT + 1)
    popup = completer.popup()
    all_counterparties = len(cat.values(cat.by_code["60.1"].sc_kinds[0]))
    assert popup.isVisible()
    assert completer.model().rowCount() == all_counterparties  # whole directory, like 1C

    type_text(editor, "б")  # first letter already filters
    assert popup.isVisible()
    assert completer.model().stringList() == ["Бета Сервис"]
    assert popup.currentIndex().row() == 0  # best match preselected

    qtbot.keyClick(popup, Qt.Key.Key_Return)
    assert page.model.data(page.model.index(0, CT + 1)) == "Бета Сервис"


def test_account_list_appears_while_typing(window, qtbot):
    window.new_document()
    page = current_page(window)
    editor, completer = open_cell_editor(page, 0, DT)
    assert not completer.popup().isVisible()  # empty account cell: no noise
    qtbot.keyClicks(editor, "60")
    assert completer.model().stringList()[:2] == [
        "60.1  Расчёты с поставщиками и подрядчиками",
        "60.2  Авансы выданные",
    ]


def test_osv_top_level_only(window):
    window.show_place(("osv",))
    osv = current_page(window)
    osv.date_from.setDate(date(2026, 2, 1))
    osv.date_to.setDate(date(2026, 2, 28))
    osv.top_only.setChecked(True)
    codes = [r.code for r in osv.model.rows]
    assert "10" in codes and "10.1" not in codes and "60.1" not in codes
    total = osv.model.rows[-1]
    assert osv.model.data(osv.model.index(len(osv.model.rows) - 1, 2)) == "0.00" or (
        total.opening_dt != 0
    )


def test_close_cross_in_sidebar(window, qtbot):
    window.new_document()
    page = current_page(window)
    nav = window.sidebar.nav
    item = window.sidebar.find(page.key)
    cross = NavDelegate.close_rect(nav.visualItemRect(item)).center()
    qtbot.mouseClick(nav.viewport(), Qt.MouseButton.LeftButton, pos=cross)
    assert window.sidebar.find(page.key) is None
    assert current_page(window).title() == "Журнал"
    places = [window.sidebar.find(k) for k in PLACE_KEYS]
    assert all(places)  # places can't be closed


def test_switch_language_rebuilds_interface(window):
    window.set_ui_language("az")
    try:
        assert current_page(window).title() == "Jurnal"
        assert window.sidebar.find(("osv",)).text() == "Dövriyyə-qalıq"
        assert window.sidebar.hint.text().startswith("Ctrl+N  yeni sənəd")
    finally:
        window.set_ui_language("ru")
    assert current_page(window).title() == "Журнал"


def test_osv_sections_by_class(window):
    window.show_place(("osv",))
    osv = current_page(window)
    osv.date_from.setDate(date(2026, 2, 1))
    osv.date_to.setDate(date(2026, 2, 28))
    osv.sections.setChecked(True)
    rows = osv.model.rows
    headers = [r for r in rows if id(r) in osv._section_rows]
    assert [h.name for h in headers] == ["Активы", "Обязательства", "Капитал", "Расходы"]
    total = rows[-1]
    assert sum(h.closing_dt for h in headers) == total.closing_dt
    assert sum(h.closing_ct for h in headers) == total.closing_ct
    assert not osv.menu_actions(headers[0])  # a section header is not an account


def test_change_class_from_chart_menu(window):
    window.show_place(("chart",))
    chart = current_page(window)
    acc = window.session.catalog.by_code["76.5"]
    menu = dict(e for e in chart.menu_actions(acc) if e is not None)
    submenu = dict(e for e in menu["Класс счёта"] if e is not None)
    submenu["     Активы"]()
    assert window.session.catalog.by_code["76.5"].account_class == "asset"
    row = next(a for a in chart.model.rows if a.code == "76.5")
    assert chart.model.data(chart.model.index(chart.model.rows.index(row), 3)) == "Активы"


def test_open_reports_are_translated_in_sidebar(window):
    window.set_ui_language("az")
    try:
        osv = window.pages.get(("osv",)) or (window.show_place(("osv",)) or current_page(window))
        window.open_report("card", "51", osv.params)
        assert window.sidebar.find(("card", "51")).text() == "Hesab kartı 51"
        assert current_page(window).header.title.text() == "Hesab kartı 51"
    finally:
        window.set_ui_language("ru")


def test_osv_expanded_by_subconto(window):
    window.show_place(("osv",))
    osv = current_page(window)
    osv.date_from.setDate(date(2026, 2, 1))
    osv.date_to.setDate(date(2026, 2, 28))
    osv.expand.setChecked(True)
    rows = osv.model.rows
    i = next(i for i, r in enumerate(rows) if r.code == "60.1")
    under = [r.name.strip() for r in rows[i + 1 : i + 3]]
    assert under == ["Альфа Трейд", "Бета Сервис"]
    assert sum(r.closing_ct for r in rows[i + 1 : i + 3]) == rows[i].closing_ct
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
    chart.edit_account(None, "52")
    assert cat.by_code["52"].is_group
    assert cat.by_code["52.1"].parent_id == cat.by_code["52"].id
    assert cat.by_code["52.1"].account_class == "asset"  # inherited

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
    osv.date_from.setDate(date(2026, 2, 1))
    osv.date_to.setDate(date(2026, 2, 28))
    osv.refresh()
    i = next(i for i, r in enumerate(osv.model.rows) if r.code == "50")
    closing_ct = osv.model.index(i, 7)
    assert osv.model.data(closing_ct) == "3 250.00"
    assert osv.model.data(closing_ct, Qt.ItemDataRole.ForegroundRole).name() == "#dc4446"
    assert "дебетовое" in osv.model.data(closing_ct, Qt.ItemDataRole.ToolTipRole)
    assert "50" in osv.footer.text()


def test_companies_are_files_and_can_be_switched(window, workspace, monkeypatch):
    monkeypatch.setattr(
        "modern_gl.desktop.main_window.QInputDialog.getText",
        staticmethod(lambda *a, **k: ("Yeni MMC", True)),
    )
    assert window.create_company()
    assert window.session.company_name == "Yeni MMC"
    assert window.company_path == workspace.folder / "Yeni MMC.gl"
    assert current_page(window).model.rowCount() == 0  # new company: empty journal
    assert [c.name for c in workspace.companies()] == ["Yeni MMC", "ДЕМО ООО"]
    demo = next(c for c in workspace.companies() if c.name == "ДЕМО ООО")
    window.open_company(demo.path)
    assert current_page(window).model.rowCount() == 11


def test_delete_company_needs_typed_name(window, workspace, monkeypatch):
    path = window.company_path
    monkeypatch.setattr("modern_gl.desktop.main_window.confirm_delete", lambda *a: False)
    window.delete_company()
    assert path.exists()  # not confirmed: nothing happens

    monkeypatch.setattr("modern_gl.desktop.main_window.confirm_delete", lambda *a: True)
    monkeypatch.setattr(
        "modern_gl.desktop.main_window.QInputDialog.getText",
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
        "modern_gl.desktop.document_page.ask_date", lambda *a, **k: date(2026, 3, 5)
    )
    current_page(window).reverse()
    storno_page = current_page(window)
    assert storno_page.btn_delete.isVisible() and not storno_page.btn_unpost.isVisible()
    monkeypatch.setattr(
        QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
    )
    storno_page.delete()
    assert window.sidebar.find(storno_page.key) is None
    window.open_document(original.id)
    page = current_page(window)
    page.load(original.id)
    assert page.status.text() == "Проведён"  # no longer "Сторнирован"


def test_unpost_from_page_makes_it_editable(window):
    doc = window.pages[("journal",)].model.docs[1]
    window.open_document(doc.id)
    page = current_page(window)
    assert page.model.read_only
    page.unpost()
    assert not page.model.read_only
    assert page.status.text() == "Черновик"
    assert window.pages[("journal",)].model.docs[1].status == "draft"
