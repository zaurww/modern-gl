"""The columns of a posting line, its row and reading pasted Excel headers."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from fractions import Fraction

from PySide6.QtCore import (
    Qt,
)

from modern_gl.application.queries import PostingData
from modern_gl.application.table_text import header_names
from modern_gl.i18n import fold

DT, CT, CURRENCY, CURRENCY_AMOUNT, RATE, AMOUNT, MEMO, INVOICE = 0, 4, 8, 9, 10, 11, 12, 13
CURRENCY_COLUMNS = (CURRENCY, CURRENCY_AMOUNT, RATE)
HEADERS = [
    "Дебет",
    "Субконто",
    "",
    "",
    "Кредит",
    "Субконто",
    "",
    "",
    "Валюта",
    "В валюте",
    "Курс",
    "Сумма",
    "Содержание",
    "E-qaimə",
]
NUMBER_COLUMNS = (CURRENCY_AMOUNT, RATE, AMOUNT)
# translated at display time: tr(HEADERS[i])
ALIGN_RIGHT = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
ALIGN_LEFT = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter


def column_role(col: int) -> tuple[str, int | None]:
    """('debit'|'credit', None) for an account, (side, 1..3) for subconto, else field name."""
    if DT <= col < CT:
        return "debit", (col - DT) or None
    if CT <= col < CURRENCY:
        return "credit", (col - CT) or None
    names = {
        CURRENCY: "currency",
        CURRENCY_AMOUNT: "currency_amount",
        RATE: "rate",
        AMOUNT: "amount",
        INVOICE: "invoice",
    }
    return names.get(col, "memo"), None


class UnknownValue(LookupError):
    """A subconto name that is not in its directory (yet)."""

    def __init__(self, kind_id: int, text: str) -> None:
        super().__init__(text)
        self.kind_id, self.text = kind_id, text


@dataclass
class EntryHints:
    """What the grid may suggest; the document page fills it from the company's history."""

    recent: Callable[[int, int], list[int]] = lambda _account, _position: []
    memo: Callable[[int, int], str] = lambda _debit, _credit: ""
    templates: Callable[[], list[tuple[int, str]]] = list  # (id, name)


ARITHMETIC = re.compile(r"[-+*/()=]")
CURRENCY_AMOUNT_TEXT = re.compile(
    r"^\s*(?:(?P<number>[\d\s.,']+?)\s*(?P<code>[A-Za-z]{3})"
    r"|(?P<code2>[A-Za-z]{3})\s*(?P<number2>[\d\s.,']+))\s*$"
)


@dataclass(frozen=True)
class InCurrency:
    """An amount typed with its currency: 500 EUR."""

    currency_id: int
    amount: int


@dataclass
class PasteResult:
    rows: int = 0
    errors: list[str] = field(default_factory=list)
    unknown: list[tuple[int, int, int, str]] = field(default_factory=list)  # row, col, kind


HEADER_FIELDS = [  # header names -> column (subconto headers are handled separately)
    (header_names("Дебет", "Дт", "Счёт Дт"), DT),
    (header_names("Кредит", "Кт", "Счёт Кт"), CT),
    (header_names("Валюта"), CURRENCY),
    (header_names("В валюте", "Сумма в валюте"), CURRENCY_AMOUNT),
    (header_names("Курс"), RATE),
    (header_names("Сумма"), AMOUNT),
    (header_names("Содержание", "Комментарий"), MEMO),
    (header_names("E-qaimə", "E-qaime", "Е-гаимя", "Счёт-фактура", "Qaimə"), INVOICE),
]
SUBCONTO_NAMES = header_names("Субконто")


def header_columns(
    cells: list[str], fields: list[tuple[set[str], int]] = HEADER_FIELDS
) -> list[int | None] | None:
    """Columns of a header line, or None if the line is not a header. A bare
    "Субконто" belongs to the account column before it (1st, 2nd… in a row);
    "Субконто Дт 2" / "Subkonto Kt 1" say it explicitly."""
    result: list[int | None] = []
    base, pos, known = None, 0, 0
    for cell in cells:
        name = fold(cell.strip())
        column = next((col for names, col in fields if name in names), None)
        words = name.split()
        if column is None and words and words[0] in SUBCONTO_NAMES:
            side = next((w for w in words[1:] if w in ("дт", "dt", "кт", "kt")), None)
            digits = [int(w) for w in words if w.isdigit()]
            if side is not None:
                base, pos = (DT if side in ("дт", "dt") else CT), 0
            pos = digits[0] if digits else pos + 1
            if base is not None and 1 <= pos <= 3:
                column = base + pos
        elif column in (DT, CT):
            base, pos = column, 0
        known += column is not None
        result.append(column)
    return result if known >= 2 else None


@dataclass
class PostingRow:
    debit: int | None = None
    debit_sc: list[int | None] = field(default_factory=lambda: [None, None, None])
    credit: int | None = None
    credit_sc: list[int | None] = field(default_factory=lambda: [None, None, None])
    amount: int | None = None
    memo: str = ""
    formula: str = ""  # entry templates: amount formula (S, S*18/118…), see domain.formula
    currency_id: int | None = None
    currency_amount: int | None = None
    rate: Fraction | None = None  # manat per unit; the manat amount follows it
    rate_auto: bool = True  # taken from the rates of the document date (not typed)
    invoice: str = ""  # e-qaimə number
    invoice_kind: str = ""  # "customs": a customs declaration (from a warehouse receipt)
    invoice_auto: bool = False  # inherited from a related line, safe to refresh

    def is_empty(self) -> bool:
        return (
            self.debit is None
            and self.credit is None
            and self.amount is None
            and not self.formula
            and not self.memo.strip()
        )

    @classmethod
    def from_data(cls, p: PostingData, keep_sign: bool = True) -> PostingRow:
        cur = p.currency_amount
        return cls(
            p.debit_account_id,
            list(p.debit_subconto),
            p.credit_account_id,
            list(p.credit_subconto),
            p.amount if keep_sign or p.amount is None else abs(p.amount),
            p.memo,
            currency_id=p.currency_id,
            currency_amount=cur if keep_sign or cur is None else abs(cur),
            rate=Fraction(p.amount, cur) if cur and p.amount else None,  # as it was posted
            rate_auto=False,
            invoice=p.invoice,
            invoice_kind=p.invoice_kind,
        )
