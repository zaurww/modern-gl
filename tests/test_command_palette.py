"""Ctrl+K (D86): one window to find commands, places, accounts, counterparties and
documents; letters folded (ş = s, ə = e)."""

from __future__ import annotations

from datetime import date

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from modern_gl.application.queries import find_documents, list_documents
from modern_gl.application.workspace import Workspace
from modern_gl.desktop import theme
from modern_gl.desktop.command_palette import CommandPalette
from modern_gl.desktop.directories_page import DirectoriesPage
from modern_gl.desktop.main_window import MainWindow


@pytest.fixture
def window(qtbot, tmp_path, make_demo):
    make_demo(tmp_path / "ДЕМО ООО.gl")
    theme.apply(QApplication.instance())
    win = MainWindow(Workspace(tmp_path))
    qtbot.addWidget(win)
    win.start()
    win.session.working_date = date(2026, 2, 28)
    win.show()
    yield win
    win.shutdown()


def palette(window) -> CommandPalette:
    p = window.command_palette()
    assert p is not None
    return p


def titles(p: CommandPalette, group: str) -> list[str]:
    return [e.title for e in p.entries_shown() if e.group == group]


def test_find_documents_by_number_and_by_folded_words(window):
    s = window.session
    docs = list_documents(s.conn, s.company_id)
    first = docs[0]
    assert [d.id for d in find_documents(s.conn, s.company_id, str(first.number))] == [first.id]
    assert [d.id for d in find_documents(s.conn, s.company_id, f"№{first.number}")] == [first.id]
    assert find_documents(s.conn, s.company_id, "99999") == []
    # «Оплата поставщику» typed in small letters, two of three documents — the latest first
    word = docs[2].memo.split()[0]
    found = find_documents(s.conn, s.company_id, word.lower())
    expected = [d for d in docs if word.lower() in d.memo.lower()]
    assert len(expected) >= 1
    assert [d.id for d in found] == [
        d.id for d in sorted(expected, key=lambda d: (d.doc_date, d.number), reverse=True)
    ]
    assert len(find_documents(s.conn, s.company_id, "", limit=3)) == 0
    assert len(find_documents(s.conn, s.company_id, " ", limit=3)) == 0


def test_empty_palette_offers_commands_and_places(window):
    p = palette(window)
    groups = [e.group for e in p.entries_shown()]
    assert groups[0] == "Команды"
    assert "Новый документ" in titles(p, "Команды")
    assert "Журнал" in titles(p, "Разделы")
    assert "ОСВ" in titles(p, "Отчёты")
    assert p.current_entry() == p.entries_shown()[0]


def test_typing_an_account_code_opens_its_card(window, qtbot):
    p = palette(window)
    p.search.setText("60")
    shown = titles(p, "Счета")
    assert shown[0].startswith("60  ")  # the code typed comes first
    while p.current_entry().group != "Счета":
        qtbot.keyClick(p.search, Qt.Key.Key_Down)
    qtbot.keyClick(p.search, Qt.Key.Key_Return)
    page = window.stack.currentWidget()
    assert page.title().startswith("Карточка счёта 60")
    assert not p.isVisible()


def test_counterparty_opens_in_its_directory_folded_letters(window):
    cat = window.session.catalog
    kind = next(k for k in cat.kinds if cat.has_tax_id(k))
    value = next(v for v in cat.values(kind) if not v.is_group)
    p = palette(window)
    p.search.setText(value.name[:5].upper())
    entry = next(e for e in p.entries_shown() if e.group == "Контрагенты")
    assert entry.title == value.name
    entry.run()
    page = window.pages[("directories",)]
    assert isinstance(page, DirectoriesPage)
    assert page.kind_id() == kind
    assert page._current_value().id == value.id


def test_document_found_by_number_opens(window):
    s = window.session
    doc = list_documents(s.conn, s.company_id)[-1]  # the draft rent: a journal document
    p = palette(window)
    p.search.setText(f"№{doc.number}")
    entry = next(e for e in p.entries_shown() if e.group == "Документы")
    assert entry.title.startswith(f"№{doc.number}")
    entry.run()
    assert window.stack.currentWidget().doc.id == doc.id


def test_escape_closes_and_read_only_has_no_new_commands(window, qtbot):
    p = palette(window)
    qtbot.keyClick(p.search, Qt.Key.Key_Escape)
    assert not p.isVisible()
    window.session.read_only = True
    p = palette(window)
    assert "Новый документ" not in titles(p, "Команды")
    assert "Журнал" in titles(p, "Разделы")
