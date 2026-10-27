"""Rows of cells from a spreadsheet file (.xlsx) or a text table (.csv / .txt / .tsv).

Every cell comes back as text the way a person reads it: dates as DD.MM.YYYY, whole
numbers without ".0", so the import treats a file and pasted Excel cells the same way.
"""

from __future__ import annotations

import csv
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from modern_gl.domain.errors import LedgerError
from modern_gl.i18n import tr

TEXT_SUFFIXES = {".csv", ".txt", ".tsv"}


class TableFileError(LedgerError):
    """A table file that cannot be read; the message is for the user."""


def from_clipboard(text: str) -> list[list[str]]:
    """Cells copied from Excel: tab-separated, one row per line."""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    while lines and not lines[-1].strip():
        lines.pop()
    return [line.split("\t") for line in lines]


def read_rows(path: str | Path) -> list[list[str]]:
    """The cells of an Excel (.xlsx) or CSV/text file as text, row by row;
    TableFileError for another kind of file."""
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix in (".xlsx", ".xlsm"):
        return _xlsx(path)
    if suffix in TEXT_SUFFIXES:
        return _text(path)
    raise TableFileError(tr("файл {file}: нужен Excel (.xlsx) или CSV", file=path.name))


def cell_text(value: object) -> str:
    """A cell of an Excel or CSV file as text: dates as DD.MM.YYYY, numbers without float noise."""
    if value is None:
        return ""
    if isinstance(value, datetime):
        return f"{value:%d.%m.%Y}"
    if isinstance(value, date):
        return f"{value:%d.%m.%Y}"
    if isinstance(value, float):  # Excel keeps numbers as floats: show them plainly
        text = format(Decimal(repr(value)), "f")
        return text[:-2] if text.endswith(".0") else text
    return str(value).strip()


def _xlsx(path: Path) -> list[list[str]]:
    from openpyxl import load_workbook  # only needed for Excel files

    try:
        book = load_workbook(path, read_only=True, data_only=True)
    except Exception as e:  # openpyxl raises many kinds for a broken or foreign file
        raise TableFileError(
            tr("не удалось прочитать {file}: {error}", file=path.name, error=e)
        ) from e
    try:
        sheet = book.worksheets[0]
        rows = [[cell_text(v) for v in row] for row in sheet.iter_rows(values_only=True)]
    finally:
        book.close()
    while rows and not any(rows[-1]):
        rows.pop()
    return rows


def _text(path: Path) -> list[list[str]]:
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "cp1251"):  # Excel "CSV UTF-8", or old Windows Cyrillic
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise TableFileError(
            tr("не удалось прочитать {file}: неизвестная кодировка", file=path.name)
        )
    sample = text[:4096]
    delimiter = max(("\t", ";", ","), key=sample.count)
    rows = [row for row in csv.reader(text.splitlines(), delimiter=delimiter)]
    while rows and not any(c.strip() for c in rows[-1]):
        rows.pop()
    return rows
