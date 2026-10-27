"""Excel files the tests write and read."""

from __future__ import annotations

from openpyxl.workbook.workbook import Workbook
from openpyxl.worksheet.worksheet import Worksheet


def active_sheet(book: Workbook) -> Worksheet:
    """The sheet a new or loaded book opens on (openpyxl types it as optional)."""
    sheet = book.active
    assert isinstance(sheet, Worksheet)
    return sheet
