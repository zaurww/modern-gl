"""Pieces of a printed form in Excel (cash orders, the cash book, the advance report):
a line across the page, a captioned field, a boxed table, one page wide. Five columns
(`WIDTHS`), the words in the language of documents."""

from __future__ import annotations

from typing import TYPE_CHECKING

from modern_gl.i18n import document_language, trd

if TYPE_CHECKING:
    from openpyxl.worksheet.worksheet import Worksheet

WIDTHS = (12, 34, 14, 16, 16)
LAST = "E"


def upper(text: str) -> str:
    """Capitals of the language of documents: Azerbaijani i → İ, ı → I."""
    if document_language() == "az":
        text = text.replace("i", "İ").replace("ı", "I")
    return text.upper()


def company_line(company: str, tax_id: str) -> str:
    """«Xəzər Ofis MMC  ·  VÖEN 1234567890» — the head of a paper."""
    tin = f"  ·  {trd('VÖEN')} {tax_id}" if tax_id else ""
    return f"{company}{tin}"


def widths(sheet: Worksheet, sizes: tuple[int, ...] = WIDTHS) -> None:
    """The widths of the columns."""
    from openpyxl.utils import get_column_letter

    for i, width in enumerate(sizes, start=1):
        sheet.column_dimensions[get_column_letter(i)].width = width


def line(sheet: Worksheet, text: str, bold: bool = False, size: int = 11) -> None:
    """A line across the page: merged, so a long one is not cut by the columns."""
    from openpyxl.styles import Alignment, Font

    sheet.append([text])
    row = sheet.max_row
    sheet.merge_cells(f"A{row}:{LAST}{row}")
    cell = sheet.cell(row, 1)
    cell.font = Font(bold=bold, size=size)
    cell.alignment = Alignment(wrap_text=True, vertical="top")


def field(sheet: Worksheet, caption: str, value: str) -> None:
    """«Основание:  Оплата от BETA» — the caption, the value over the rest of the line."""
    from openpyxl.styles import Alignment

    sheet.append([f"{caption}:", value])
    row = sheet.max_row
    sheet.merge_cells(f"B{row}:{LAST}{row}")
    sheet.cell(row, 2).alignment = Alignment(wrap_text=True, vertical="top")


def boxed(sheet: Worksheet, top: int, bottom: int, columns: int) -> None:
    """Thin borders around the cells of a table."""
    from openpyxl.styles import Border, Side

    thin = Side(style="thin")
    for row in range(top, bottom + 1):
        for col in range(1, columns + 1):
            sheet.cell(row, col).border = Border(left=thin, right=thin, top=thin, bottom=thin)


def page(sheet: Worksheet) -> None:
    """One page wide, as long as it takes."""
    from openpyxl.worksheet.properties import PageSetupProperties

    sheet.page_setup.orientation = "portrait"
    sheet.page_setup.fitToWidth = 1
    sheet.page_setup.fitToHeight = 0
    sheet.sheet_properties.pageSetUpPr = PageSetupProperties(fitToPage=True)
