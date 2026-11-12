"""A report as Excel likes it (D104): a plain table from A1 — one header row, frozen and
filtered, a row per line, no merged cells and no colors. Amounts are numbers (manat with
two decimals, negatives red), dates are dates, codes stay text («01» is not 1); the depth
of a line is Excel's own row grouping (+/−) and a «Уровень» column to filter by, not
spaces. What the report is — its title, period, book — is on a second sheet, so nothing
sits above the table and it can go straight into a pivot or a filter. A flat table meant
for a pivot (`as_table`) is an Excel table, so a pivot on it grows with the next export.
The same table, tab-separated, is what Ctrl+C puts on the clipboard."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from modern_gl.i18n import tr
from modern_gl.infrastructure.report_formulas import formulas

MONEY_FORMAT = "#,##0.00;[Red]-#,##0.00"
DATE_FORMAT = "DD.MM.YYYY"
SHEET_NAME_BAD = "[]:*?/\\"
MAX_WIDTH = 60


@dataclass
class ReportColumn:
    """A column of a report file; a money column holds minor units, a date column ISO
    dates, a number column plain integers (a year, a document number) — the rest is text."""

    title: str
    money: bool = False  # cells are minor units (int) or None
    group: str = ""  # «Начальное сальдо» over its Dt and Kt: «Начальное сальдо · Дт»
    date: bool = False  # cells are ISO dates ("2026-03-01") or None
    number: bool = False  # cells are plain integers or None
    # what a money column is in a trial balance («opening», «turnover_dt», «closing_ct»…):
    # its closing balance is then a formula of the others (report_formulas)
    role: str = ""

    @property
    def caption(self) -> str:
        """The header of the column: with its group («Начальное сальдо · Дт»)."""
        return f"{self.group} · {self.title}" if self.group else self.title

    def cell(self, value: object) -> Any:
        """What goes into the cell: a Decimal, a date, an int, or text."""
        if self.money:
            return amount(value)
        if self.date:
            return date.fromisoformat(value) if isinstance(value, str) and value else None
        if self.number:
            return value if isinstance(value, int) else None
        return "" if value is None else str(value)

    def shown(self, value: object) -> str:
        """The cell as Excel shows it, to size the column."""
        if self.money:
            return f"{amount(value):,.2f}" if isinstance(value, int) else ""
        if self.date:
            return "00.00.0000" if value else ""
        return "" if value is None else str(value)


@dataclass
class ReportRow:
    """A line of a report file: its cells, depth (Excel outline) and whether it is a total."""

    cells: list[object]  # text, or minor units in a money column
    level: int = 0
    bold: bool = False  # a subtotal or a total
    total: bool = False  # a total of the lines above it (a rule over it in the report)


@dataclass
class ReportTable:
    """A report ready to be written as a file: columns, rows and what it was made for."""

    title: str
    columns: list[ReportColumn]
    rows: list[ReportRow] = field(default_factory=list[ReportRow])
    # («Период», «01.10 — …»)
    about: list[tuple[str, str]] = field(default_factory=list[tuple[str, str]])
    as_table: bool = False  # an Excel table (ListObject): a pivot's source that grows
    with_formulas: bool = True  # totals and closing balances as formulas (report_formulas)

    @property
    def leveled(self) -> bool:
        """Whether lines have depth (then Excel shows them as an outline)."""
        return any(r.level for r in self.rows)


def amount(minor: object) -> Decimal | None:
    """Minor units as manat for a cell (kopecks / 100); None for anything else."""
    return Decimal(minor) / 100 if isinstance(minor, int) else None


def write_xlsx(table: ReportTable, path: str | Path, more: Sequence[ReportTable] = ()) -> None:
    """Write the report as an .xlsx: the table on the first sheet (header frozen, amounts as
    numbers, lines as an outline), `more` tables each on a sheet of their own, the
    report's parameters on «Параметры»."""
    from openpyxl import Workbook

    book = Workbook()
    _write_sheet(book.worksheets[0], table)  # a new book has one sheet
    for extra in more:
        _write_sheet(book.create_sheet(sheet_name(extra.title)), extra)
    about = book.create_sheet(sheet_name(tr("Параметры")))
    for key, value in [(tr("Отчёт"), table.title), *table.about]:
        about.append([key, value])
    about.column_dimensions["A"].width = 18
    about.column_dimensions["B"].width = 60
    book.properties.title = table.title
    book.calculation.fullCalcOnLoad = True  # formulas are written without their values
    book.save(str(path))


def _write_sheet(sheet: Any, table: ReportTable) -> None:
    from openpyxl.styles import Font
    from openpyxl.utils import get_column_letter
    from openpyxl.worksheet.properties import Outline
    from openpyxl.worksheet.table import Table, TableStyleInfo

    sheet.title = sheet_name(table.title)
    level_column = table.leveled
    headers = [c.caption for c in table.columns] + ([tr("Уровень")] if level_column else [])
    sheet.append(headers)
    for cell in sheet[1]:
        cell.font = Font(bold=True)
    found = (
        formulas(
            [c.role for c in table.columns],
            [c.money for c in table.columns],
            table.rows,
            lambda j: get_column_letter(j + 1),
        )
        if table.with_formulas
        else {}
    )
    for k, r in enumerate(table.rows):
        values = [
            found.get((k, j)) or c.cell(v)
            for j, (c, v) in enumerate(zip(table.columns, r.cells, strict=True))
        ]
        sheet.append(values + ([r.level] if level_column else []))
        row = sheet.max_row
        if r.level:
            sheet.row_dimensions[row].outline_level = min(r.level, 7)
        for i, c in enumerate(table.columns, start=1):
            cell = sheet.cell(row, i)
            if c.money:
                cell.number_format = MONEY_FORMAT
            elif c.date:
                cell.number_format = DATE_FORMAT
            if r.bold:
                cell.font = Font(bold=True)
    sheet.sheet_properties.outlinePr = Outline(summaryBelow=False)  # a line above its detail
    sheet.freeze_panes = "A2"
    if table.as_table and table.rows:
        style = TableStyleInfo(name="TableStyleLight1", showRowStripes=False)
        sheet.add_table(
            Table(displayName=_table_name(table.title), ref=sheet.dimensions, tableStyleInfo=style)
        )
    else:
        sheet.auto_filter.ref = sheet.dimensions
    for i, c in enumerate(table.columns, start=1):
        longest = max([len(c.caption)] + [len(c.shown(r.cells[i - 1])) for r in table.rows])
        sheet.column_dimensions[get_column_letter(i)].width = min(longest + 2, MAX_WIDTH)


def to_tsv(table: ReportTable, rows: list[ReportRow] | None = None, decimal: str = ".") -> str:
    """Tab-separated, with the header: amounts as plain numbers without spaces (1234.56,
    -12.00; `decimal` — the system's separator, as Excel reads a paste) — numbers there."""

    def cell(value: object, money: bool) -> str:
        if money:
            return f"{amount(value):.2f}".replace(".", decimal) if isinstance(value, int) else ""
        return ("" if value is None else str(value)).replace("\t", " ")

    lines = ["\t".join(c.caption for c in table.columns)]
    lines.extend(
        "\t".join(cell(v, c.money) for c, v in zip(table.columns, r.cells, strict=True))
        for r in (table.rows if rows is None else rows)
    )
    return "\n".join(lines) + "\n"


def sheet_name(title: str) -> str:
    """Excel's sheet name: at most 31 characters, none of []:*?/\\."""
    clean = "".join(" " if ch in SHEET_NAME_BAD else ch for ch in title).strip()
    return clean[:31] or "Sheet"


def _table_name(title: str) -> str:
    """An Excel table name: letters, digits and underscores, not starting with a digit."""
    clean = "".join(ch if ch.isalnum() else "_" for ch in title).strip("_")
    return ("T_" + clean if not clean or clean[0].isdigit() else clean)[:255]
