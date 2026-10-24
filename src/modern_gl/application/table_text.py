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


# the columns of a posting, by the names a table may give them (the document form's paste
# and the journal import alike); «Субконто» columns are read by subconto_header
POSTING_HEADERS = {
    "debit": header_names("Дебет", "Дт", "Счёт Дт"),
    "credit": header_names("Кредит", "Кт", "Счёт Кт"),
    "amount": header_names("Сумма", "Сумма AZN"),
    "currency": header_names("Валюта"),
    "currency_amount": header_names("В валюте", "Сумма в валюте"),
    "rate": header_names("Курс"),
    "memo": header_names("Содержание", "Комментарий"),
    "invoice": header_names(
        "E-qaimə", "E-qaime", "Е-гаимя", "Qaimə", "Номер e-qaimə", "Счёт-фактура"
    ),
}
SUBCONTO_HEADERS = header_names("Субконто")
SIDE_WORDS = {"дт": "dt", "dt": "dt", "кт": "ct", "kt": "ct"}


def subconto_header(name: str, pos: int) -> tuple[str | None, int] | None:
    """A folded heading «Субконто», «Субконто Кт 2», «Subkonto Dt»: (its side — "dt",
    "ct", or None for the account column before it; its position — the digit, else the
    one after `pos`, from 1 again after a side). None — not a subconto heading."""
    words = name.split()
    if not words or words[0] not in SUBCONTO_HEADERS:
        return None
    side = next((SIDE_WORDS[w] for w in words[1:] if w in SIDE_WORDS), None)
    digits = [int(w) for w in words if w.isdigit()]
    if side is not None:
        pos = 0
    return side, digits[0] if digits else pos + 1
