"""A two-sided act as an .xlsx to print and sign (акт сверки): a title and a few lines
about the parties over the table; the table — a line per document with the amounts as
each side keeps them, their captions over the pairs of Dt / Kt; the balance lines bold;
the words about the debt under it; two signatures at the bottom. Unlike a report
(`report_file`), this is a form: merged title cells, thin borders, one page wide."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from modern_gl.infrastructure.report_file import MONEY_FORMAT, amount, sheet_name

if TYPE_CHECKING:
    from openpyxl.worksheet.worksheet import Worksheet

TEXT_COLUMNS = 3  # №, date, document — then two pairs of Dt / Kt
WIDTHS = (5, 11, 44, 14, 14, 14, 14)
LAST = "G"  # the letter of the last column
SIGNATURE_COLUMNS = (3, 6)  # under each side's pair


@dataclass
class ActRow:
    """A line of the table: three texts, then the four amounts (minor units or None)."""

    cells: list[object]
    bold: bool = False


@dataclass
class ActSheet:
    """The act ready to be written: its words, its table and who signs it."""

    title: str
    heading: list[str]  # the lines under the title: the parties, the period
    sides: tuple[str, str]  # over the pairs: «по данным …» of each side
    columns: list[str]  # the seven captions
    rows: list[ActRow] = field(default_factory=list[ActRow])
    summary: list[str] = field(default_factory=list[str])  # the words about the debt
    signatures: tuple[str, str] = ("", "")  # who signs on each side


def write_act_xlsx(act: ActSheet, path: str | Path) -> None:
    """Write the act as one printable sheet: title, heading, the table, the summary and
    the signatures; the header rows repeat on every printed page."""
    from openpyxl import Workbook
    from openpyxl.utils import get_column_letter

    book = Workbook()
    sheet = book.worksheets[0]
    sheet.title = sheet_name(act.title)
    for i, width in enumerate(WIDTHS, start=1):
        sheet.column_dimensions[get_column_letter(i)].width = width
    _merged_line(sheet, act.title, bold=True, size=14)
    for line in act.heading:
        _merged_line(sheet, line)
    sheet.append([])
    top = _table(sheet, act)
    sheet.append([])
    for line in act.summary:
        _merged_line(sheet, line, bold=True, centered=False)
    _signatures(sheet, act.signatures)
    sheet.page_setup.orientation = "portrait"
    sheet.page_setup.fitToWidth = 1
    sheet.page_setup.fitToHeight = 0
    if sheet.sheet_properties.pageSetUpPr is not None:
        sheet.sheet_properties.pageSetUpPr.fitToPage = True
    sheet.print_title_rows = f"{top}:{top + 1}"
    book.properties.title = act.title
    book.save(str(path))


def _merged_line(
    sheet: Worksheet, text: str, bold: bool = False, size: int = 11, centered: bool = True
) -> None:
    from openpyxl.styles import Alignment, Font

    sheet.append([text])
    row = sheet.max_row
    sheet.merge_cells(f"A{row}:{LAST}{row}")
    sheet.cell(row, 1).font = Font(bold=bold, size=size)
    sheet.cell(row, 1).alignment = Alignment(
        horizontal="center" if centered else "left", wrap_text=True
    )


def _table(sheet: Worksheet, act: ActSheet) -> int:
    """The two header rows and the lines; answers the row of the first header."""
    from openpyxl.styles import Alignment, Border, Font, Side

    thin = Side(style="thin")
    box = Border(left=thin, right=thin, top=thin, bottom=thin)
    center = Alignment(horizontal="center", vertical="center", wrap_text=True)
    sheet.append([*act.columns[:TEXT_COLUMNS], act.sides[0], "", act.sides[1], ""])
    top = sheet.max_row
    sheet.merge_cells(start_row=top, start_column=4, end_row=top, end_column=5)
    sheet.merge_cells(start_row=top, start_column=6, end_row=top, end_column=7)
    sheet.append(act.columns)
    for row in (top, top + 1):
        for col in range(1, len(WIDTHS) + 1):
            cell = sheet.cell(row, col)
            cell.font = Font(bold=True)
            cell.alignment = center
            cell.border = box
    for col in range(1, TEXT_COLUMNS + 1):  # the text captions span both header rows
        sheet.merge_cells(start_row=top, start_column=col, end_row=top + 1, end_column=col)
    for r in act.rows:
        sheet.append(
            [
                (str(v) if v not in (None, "") else None) if i < TEXT_COLUMNS else amount(v)
                for i, v in enumerate(r.cells)
            ]
        )
        row = sheet.max_row
        for col in range(1, len(WIDTHS) + 1):
            cell = sheet.cell(row, col)
            cell.border = box
            if col > TEXT_COLUMNS:
                cell.number_format = MONEY_FORMAT
            if r.bold:
                cell.font = Font(bold=True)
        sheet.cell(row, TEXT_COLUMNS).alignment = Alignment(wrap_text=True, vertical="top")
    return top


def _signatures(sheet: Worksheet, signatures: tuple[str, str]) -> None:
    from openpyxl.styles import Alignment, Font

    sheet.append([])
    sheet.append([])
    sheet.append(["", "", signatures[0], "", "", signatures[1], ""])
    row = sheet.max_row
    for col in SIGNATURE_COLUMNS:
        sheet.merge_cells(start_row=row, start_column=col, end_row=row, end_column=col + 1)
        sheet.cell(row, col).font = Font(bold=True)
        sheet.cell(row, col).alignment = Alignment(wrap_text=True, vertical="top")
    sheet.append([])
    sheet.append(["", "", "_______________________", "", "", "_______________________", ""])
