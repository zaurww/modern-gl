"""Any report to Excel (D104): «⋯ → В Excel…» saves the table as a file Excel likes,
Ctrl+C puts it on the clipboard. The table is read from what the page shows — its
columns and rows — so every report has it without code of its own: amounts as numbers,
the depth of a line (the 6-space steps the pages indent names by) as Excel's grouping."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QLocale, QStandardPaths, QUrl
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import QFileDialog, QMessageBox

from modern_gl.desktop.reports_page.table import DASH, ReportModel
from modern_gl.i18n import tr
from modern_gl.infrastructure.report_file import (
    ReportColumn,
    ReportRow,
    ReportTable,
    to_tsv,
    write_xlsx,
)

if TYPE_CHECKING:
    from modern_gl.desktop.reports_page.view import ReportPage

STEP = 6  # spaces of one level of a name in a report


def report_table(model: ReportModel, title: str, about: list[tuple[str, str]]) -> ReportTable:
    columns = [
        ReportColumn(c.title, c.money or c.value is not None, c.group) for c in model.columns
    ]
    rows = []
    for i, r in enumerate(model.rows):
        level = 0
        cells: list[object] = []
        for j, c in enumerate(model.columns):
            if c.money or c.value is not None:
                cells.append(c.value(r) if c.value is not None else c.get(r))
                continue
            text = model.data(model.index(i, j))
            text = "" if text is None or text == DASH else str(text)
            if j == 0:  # the first column: its indent is the depth
                level = (len(text) - len(text.lstrip(" "))) // STEP
            cells.append(text.strip())
        rows.append(ReportRow(cells, level, model.emphasis(r) or model.total(r)))
    return ReportTable(title, columns, rows, about)


def page_table(page: ReportPage) -> ReportTable:
    about = [(tr("Компания"), page.s.company_name)] if page.s.company_name else []
    if page.has_period:
        about.append((tr("Период"), page.params.describe(page.s.parallel_books)))
    about.append((tr("Сформирован"), date.today().strftime("%d.%m.%Y")))
    return report_table(page.model, page.export_title(), about)


def save_to_excel(page: ReportPage) -> None:
    folder = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation)
    p = page.params
    name = f"{page.export_title()} {p.date_from:%d.%m}-{p.date_to:%d.%m.%Y}.xlsx"
    target, _ = QFileDialog.getSaveFileName(
        page, tr("Сохранить в Excel"), str(Path(folder) / file_name(name)), "Excel (*.xlsx)"
    )
    if not target:
        return
    try:
        write_xlsx(page_table(page), target)
    except OSError as e:
        QMessageBox.warning(page, tr("В Excel"), tr("Не удалось сохранить файл: {e}", e=e))
        return
    QDesktopServices.openUrl(QUrl.fromLocalFile(target))  # straight into Excel


def copy_to_clipboard(page: ReportPage) -> None:
    """The selected rows, or the whole report when one row (or none) is selected."""
    table = page_table(page)
    chosen = sorted({i.row() for i in page.table.selectionModel().selectedRows()})
    rows = [table.rows[i] for i in chosen] if len(chosen) > 1 else None
    QGuiApplication.clipboard().setText(to_tsv(table, rows, QLocale.system().decimalPoint() or "."))
    page.s.notify(tr("Скопировано — вставьте в Excel (Ctrl+V)"))


def file_name(name: str) -> str:
    return "".join("_" if ch in '<>:"/\\|?*' else ch for ch in name)
