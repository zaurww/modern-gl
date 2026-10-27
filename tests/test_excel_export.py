"""A report for Excel (D104): read back with openpyxl, the file is a plain table — numbers
are numbers, codes are text, the depth is Excel's grouping, nothing is merged; Ctrl+C
gives the same table tab-separated."""

from __future__ import annotations

from decimal import Decimal

import openpyxl
import pytest

from modern_gl.infrastructure.report_file import (
    ReportColumn,
    ReportRow,
    ReportTable,
    sheet_name,
    to_tsv,
    write_xlsx,
)


@pytest.fixture
def window(statements_window):
    return statements_window


@pytest.fixture
def table() -> ReportTable:
    return ReportTable(
        "Прибыли и убытки",
        [ReportColumn("Счёт"), ReportColumn("Сумма", money=True)],
        [
            ReportRow(["Операционные расходы", -1_700_000], 1),
            ReportRow(["01  Основные средства", -1_400_000], 2),
            ReportRow(["Аренда", -1_000_000], 3),
            ReportRow(["Итого", 2_130_000], 0, bold=True),
            ReportRow(["Пусто", None]),
        ],
        [("Период", "01.03.2026 — 31.03.2026")],
    )


def test_the_file_is_a_table_excel_likes(table, tmp_path):
    path = tmp_path / "pl.xlsx"
    write_xlsx(table, path)
    book = openpyxl.load_workbook(path)
    sheet = book.worksheets[0]
    assert sheet.title == "Прибыли и убытки"
    assert [c.value for c in sheet[1]] == ["Счёт", "Сумма", "Уровень"]
    assert sheet.freeze_panes == "A2"
    assert sheet.auto_filter.ref == "A1:C6"
    assert not sheet.merged_cells.ranges
    amounts = [sheet.cell(r, 2).value for r in range(2, 7)]
    assert amounts[:4] == [-17000, -14000, -10000, 21300]
    assert all(isinstance(v, int | float | Decimal) for v in amounts[:4])
    assert amounts[4] is None
    assert sheet.cell(3, 1).value == "01  Основные средства"  # text, not the number 1
    assert sheet.cell(2, 2).number_format.startswith("#,##0.00")
    assert [sheet.row_dimensions[r].outline_level for r in range(2, 6)] == [1, 2, 3, 0]
    assert sheet.cell(5, 1).font.bold
    about = book.worksheets[1]
    assert [about.cell(r, 2).value for r in (1, 2)] == [
        "Прибыли и убытки",
        "01.03.2026 — 31.03.2026",
    ]


def test_the_clipboard_gets_plain_numbers(table):
    lines = to_tsv(table, decimal=",").splitlines()
    assert lines[0] == "Счёт\tСумма"
    assert lines[1] == "Операционные расходы\t-17000,00"
    assert lines[4] == "Итого\t21300,00"
    assert lines[5] == "Пусто\t"
    assert to_tsv(table, table.rows[2:3]).splitlines()[1] == "Аренда\t-10000.00"


def test_a_sheet_name_excel_accepts():
    assert sheet_name("ОСВ: 60/62 [декабрь] и ещё очень длинное название") == (
        "ОСВ  60 62  декабрь  и ещё очен"
    )


def test_every_report_goes_to_excel(qtbot, tmp_path, monkeypatch, window):
    """The statements page by accounts: the levels and the numbers behind the text."""
    from PySide6.QtWidgets import QApplication, QFileDialog

    from modern_gl.desktop.reports_page import StatementsPage, export

    target = tmp_path / "out.xlsx"
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(target), ""))
    )
    monkeypatch.setattr(export.QDesktopServices, "openUrl", staticmethod(lambda url: True))
    window.show_place(("statements",))
    page = window.stack.currentWidget()
    assert isinstance(page, StatementsPage)
    page.profit_button.click()
    page.detail_buttons["items"].click()  # a line of one account opens into its items (D108)
    qtbot.waitUntil(lambda: any(r.kind == "item" for r in page.model.rows))
    save = dict(i for i in page.more_items() if i is not None)
    save["В Excel…"]()
    sheet = openpyxl.load_workbook(target).worksheets[0]
    assert sheet.title == "Прибыли и убытки"
    rows = list(sheet.iter_rows(min_row=2, values_only=True))
    assert rows[-1][0] == "Чистая прибыль (убыток)"
    assert isinstance(rows[-1][1], int | float | Decimal)
    assert {r[2] for r in rows} >= {0, 1, 2}  # «Уровень»: lines and what is under them
    export.copy_to_clipboard(page)
    assert QApplication.clipboard().text().splitlines()[-1].startswith("Чистая прибыль")
