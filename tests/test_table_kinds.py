"""Three kinds of table (DESIGN.md §4): a list fills the page (one text column grows), a
report is as wide as its text (the free room on the right), an entry table is edited.
A page builds none of its own."""

from __future__ import annotations

import re
from pathlib import Path

from PySide6.QtCore import QStringListModel, Qt
from PySide6.QtWidgets import QAbstractItemView, QApplication

from modern_gl.desktop.list_table import ListTable
from modern_gl.desktop.reports_page import Column, ReportModel, ReportTable

DESKTOP = Path(__file__).parent.parent / "src" / "modern_gl" / "desktop"

KINDS = {
    "list_table.py": "список",
    "reports_page/report_table.py": "отчёт",
    # entry tables: cells edited from the keyboard as in 1C
    "postings/table.py": "ввод",
    "inventory_document_page/lines_table.py": "ввод",
    "landed_cost_page/table.py": "ввод",
    "eqaime_import_form.py": "ввод",  # the parties and the renames of an import
}

OWN_TABLE = re.compile(r"\bQTable(View|Widget)\(|\(QTable(View|Widget)\)")


def test_no_page_builds_a_table_of_its_own():
    own = [
        str(path.relative_to(DESKTOP))
        for path in DESKTOP.rglob("*.py")
        if OWN_TABLE.search(path.read_text(encoding="utf-8"))
        and path.relative_to(DESKTOP).as_posix() not in KINDS
    ]
    assert own == [], "таблица — ListTable, ReportTable или таблица ввода (DESIGN.md §4)"


def test_a_list_table(qtbot):
    """Rows chosen whole, one at a time, no grid, no row numbers, not edited («Долг» 14)."""
    table = ListTable(QStringListModel(["a", "b"]), 32, wrap=False)
    qtbot.addWidget(table)
    assert table.objectName() == "list"
    assert table.selectionBehavior() == QAbstractItemView.SelectionBehavior.SelectRows
    assert table.selectionMode() == QAbstractItemView.SelectionMode.SingleSelection
    assert table.editTriggers() == QAbstractItemView.EditTrigger.NoEditTriggers
    assert not table.showGrid() and not table.wordWrap()
    assert table.verticalHeader().isHidden()
    assert table.verticalHeader().defaultSectionSize() == 32


def test_no_page_sets_up_a_list_by_hand():
    allowed = {"list_table.py", "reports_page/chart.py"}  # chart: a report styled as a list
    bad = [
        p.relative_to(DESKTOP).as_posix()
        for p in DESKTOP.rglob("*.py")
        if 'setObjectName("list")' in p.read_text(encoding="utf-8")
        and p.relative_to(DESKTOP).as_posix() not in allowed
    ]
    assert not bad, f"таблица-список настраивается вручную: {bad} — ListTable"


def test_enter_opens_a_row_of_a_list(qtbot):
    table = ListTable(QStringListModel(["a", "b"]))
    qtbot.addWidget(table)
    table.setCurrentIndex(table.model().index(1, 0))
    with qtbot.waitSignal(table.doubleClicked) as opened:
        qtbot.keyClick(table, Qt.Key.Key_Return)
    assert opened.args[0].row() == 1


ROWS = [("01.03.2026", "Аренда офиса", 150_000), ("02.03.2026", "Связь", 4_500)]
COLUMNS = [
    Column("Дата", lambda r: r[0], width=110),
    Column("Содержание", lambda r: r[1]),
    Column("Сумма", lambda r: r[2], money=True),
]


def _shown(table, width: int) -> None:
    table.resize(width, 300)
    table.show()
    QApplication.processEvents()


def test_list_fills_the_page_with_its_text_column(qtbot):
    model = ReportModel()
    table = ListTable(model, wrap=False)
    qtbot.addWidget(table)
    model.set(COLUMNS, ROWS)
    _shown(table, 900)
    widths = [table.columnWidth(i) for i in range(3)]
    assert table.fill_column() == 1  # the memo: no width of its own, not an amount
    assert sum(widths) == table.viewport().width()  # no room left, the last column whole
    assert widths[1] > widths[0] and widths[1] > widths[2]
    _shown(table, 1300)
    assert table.columnWidth(1) == widths[1] + 400  # a wider window: the memo grows
    assert table.columnWidth(2) == widths[2]


def test_report_keeps_the_free_room_on_the_right(qtbot):
    model = ReportModel()
    table = ReportTable(model)
    qtbot.addWidget(table)
    model.set(COLUMNS, ROWS)
    table.layout_columns()
    _shown(table, 1300)
    assert sum(table.columnWidth(i) for i in range(3)) < table.viewport().width() - 600
