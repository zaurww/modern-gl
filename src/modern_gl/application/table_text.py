"""Text of a table pasted from Excel or read from a file: numbers as Excel writes them and
column headings in Russian or Azerbaijani — one reading for the journal import and for
every grid that takes a paste."""

from __future__ import annotations

from modern_gl.i18n import fold
from modern_gl.i18n_az import AZ


def plain_number(text: str) -> str:
    """Excel numbers as they come: '1 234,50', '1,234.50', '1.234,50' -> '1234.50'."""
    text = text.strip().replace(" ", "").replace(" ", "").replace("'", "")
    if "," in text and "." in text:  # the first one separates thousands
        thousands = "," if text.index(",") < text.index(".") else "."
        text = text.replace(thousands, "")
    return text.replace(",", ".")


def header_names(*sources: str) -> set[str]:
    """A heading in Russian and in Azerbaijani, folded for matching."""
    return {fold(name) for src in sources for name in (src, AZ.get(src, src))}
