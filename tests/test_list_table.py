"""A read-only list (journal, directories, stock…) is set up in one place — `list_table`
(«Долг» 14): rows chosen whole, one at a time, no grid, no row numbers, not edited."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QStringListModel
from PySide6.QtWidgets import QAbstractItemView

from modern_gl.desktop.widgets import list_table

DESKTOP = Path(__file__).parent.parent / "src" / "modern_gl" / "desktop"


def test_a_list_table(qtbot):
    table = list_table(QStringListModel(["a", "b"]), 32, wrap=False)
    qtbot.addWidget(table)
    assert table.objectName() == "list"
    assert table.selectionBehavior() == QAbstractItemView.SelectionBehavior.SelectRows
    assert table.selectionMode() == QAbstractItemView.SelectionMode.SingleSelection
    assert table.editTriggers() == QAbstractItemView.EditTrigger.NoEditTriggers
    assert not table.showGrid() and not table.wordWrap()
    assert table.verticalHeader().isHidden()
    assert table.verticalHeader().defaultSectionSize() == 32


def test_no_page_sets_up_a_list_by_hand():
    allowed = {"widgets.py", "reports_page/chart.py"}  # chart: a tree of a report, styled as a list
    bad = [
        p.relative_to(DESKTOP).as_posix()
        for p in DESKTOP.rglob("*.py")
        if 'setObjectName("list")' in p.read_text(encoding="utf-8")
        and p.relative_to(DESKTOP).as_posix() not in allowed
    ]
    assert not bad, f"таблица-список настраивается вручную: {bad} — widgets.list_table"
