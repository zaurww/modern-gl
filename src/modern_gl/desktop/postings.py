"""Postings grid: model, inline editors with completion, keyboard flow.

Keyboard flow (1C-like): type into a cell to edit, Enter/Tab moves to the next cell
that applies — subconto cells the chosen account doesn't have are skipped, and so
are the currency cells of a line without a currency account. On a currency line the
amount in manat follows the amount in currency at the rate (the rate of the document
date is offered; both the rate and the manat amount can be typed over).
Enter on the last cell of the last row starts a new row.

Paste (Ctrl+V) takes lines copied from Excel, one posting per line. With a header line
(Дебет, Кредит, Сумма… in Russian or Azerbaijani, any order) cells go by the headers;
without one they go in the order of keyboard entry: Dt, its subconto, Kt, its subconto,
(currency, amount in currency, rate,) amount, memo — an empty cell skips a field.
Copy (Ctrl+C) gives the document in the header form, so it can go to Excel and back.

Speed-ups: a subconto list starts with the elements recently used on that account; the
memo cell offers the memo of the last posting with the same Dt/Kt pair (selected, so
typing replaces it); "#" in the Dt cell picks an entry template; an amount may be typed
as arithmetic (1180*18/118).

The e-qaimə column (the number of the portal's electronic invoice) appears once a line
is on a settlement or ƏDV account; it stays after the memo, so pasting in the order of
keyboard entry is not shifted.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal
from fractions import Fraction
from typing import cast

from PySide6.QtCore import (
    QAbstractTableModel,
    QEvent,
    QModelIndex,
    QObject,
    QPersistentModelIndex,
    QStringListModel,
    Qt,
    QTimer,
    Signal,
    SignalInstance,
)
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemDelegate,
    QAbstractItemView,
    QCompleter,
    QHeaderView,
    QLineEdit,
    QStyledItemDelegate,
    QTableView,
)

from modern_gl.application.catalog import Catalog, search
from modern_gl.application.ledger import PostingInput
from modern_gl.application.queries import PostingData
from modern_gl.desktop.theme import P, fonts
from modern_gl.domain import formula
from modern_gl.domain.accounts import SETTLEMENT_TYPES
from modern_gl.domain.currency import (
    CURRENCY_ONLY,
    format_unit_rate,
    parse_rate,
    to_base,
    unit_rate,
)
from modern_gl.domain.errors import ValidationError
from modern_gl.domain.invoice import normalize_invoice
from modern_gl.domain.money import SCALE, format_minor, to_minor
from modern_gl.i18n import fold, tr
from modern_gl.i18n_az import AZ

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


TEMPLATE_MARK = "#"
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


def plain_number(text: str) -> str:
    """Excel numbers as they come: '1 234,50', '1,234.50', '1.234,50' -> '1234.50'."""
    text = text.strip().replace("\u00a0", "").replace(" ", "").replace("'", "")
    if "," in text and "." in text:  # the first one separates thousands
        thousands = "," if text.index(",") < text.index(".") else "."
        text = text.replace(thousands, "")
    return text.replace(",", ".")


def _names(*sources: str) -> set[str]:
    """A header in Russian and in Azerbaijani, folded for matching."""
    return {fold(name) for src in sources for name in (src, AZ.get(src, src))}


HEADER_FIELDS = [  # header names -> column (subconto headers are handled separately)
    (_names("Дебет", "Дт", "Счёт Дт"), DT),
    (_names("Кредит", "Кт", "Счёт Кт"), CT),
    (_names("Валюта"), CURRENCY),
    (_names("В валюте", "Сумма в валюте"), CURRENCY_AMOUNT),
    (_names("Курс"), RATE),
    (_names("Сумма"), AMOUNT),
    (_names("Содержание", "Комментарий"), MEMO),
    (_names("E-qaimə", "E-qaime", "Е-гаимя", "Счёт-фактура", "Qaimə"), INVOICE),
]
SUBCONTO_NAMES = _names("Субконто")


def header_columns(cells: list[str]) -> list[int | None] | None:
    """Columns of a header line, or None if the line is not a header. A bare
    "Субконто" belongs to the account column before it (1st, 2nd… in a row);
    "Субконто Дт 2" / "Subkonto Kt 1" say it explicitly."""
    result: list[int | None] = []
    base, pos, known = None, 0, 0
    for cell in cells:
        name = fold(cell.strip())
        column = next((col for names, col in HEADER_FIELDS if name in names), None)
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


class PostingsModel(QAbstractTableModel):
    changed = Signal()

    def __init__(
        self,
        catalog: Catalog,
        rows: list[PostingRow] | None = None,
        read_only: bool = False,
        formulas: bool = False,
        inherit_invoices: bool = True,
    ) -> None:
        super().__init__()
        self.catalog = catalog
        self.rows = rows or [PostingRow()]
        self.read_only = read_only
        self.formulas = formulas  # template editing: the amount column holds formulas
        self.inherit_invoices = inherit_invoices
        # currency id -> manat per unit on the document date (set by the document page)
        self.rate_for: Callable[[int], Fraction | None] = lambda _currency_id: None

    # ---- Qt model API ----------------------------------------------------------------

    def rowCount(self, parent: QModelIndex | QPersistentModelIndex | None = None) -> int:
        return 0 if parent is not None and parent.isValid() else len(self.rows)

    def columnCount(self, parent: QModelIndex | QPersistentModelIndex | None = None) -> int:
        return 0 if parent is not None and parent.isValid() else len(HEADERS)

    def headerData(self, section, orientation, role: int = Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole:
            if orientation == Qt.Orientation.Horizontal:
                return tr(HEADERS[section]) if HEADERS[section] else ""
            return str(section + 1)
        if role == Qt.ItemDataRole.TextAlignmentRole and orientation == Qt.Orientation.Horizontal:
            return ALIGN_RIGHT if section in NUMBER_COLUMNS else ALIGN_LEFT
        return None

    def _currency_modes(self, row: int) -> list[int]:
        r = self.rows[row]
        if self.formulas:
            return []
        modes = [self.catalog.accounts[a].currency for a in (r.debit, r.credit) if a is not None]
        return [m for m in modes if m]

    def is_currency(self, row: int) -> bool:
        """The line hits a currency account, so it may have a currency and an amount in it."""
        return bool(self._currency_modes(row))

    def currency_required(self, row: int) -> bool:
        """The line hits an account kept only in currency (52): manat alone won't do."""
        return CURRENCY_ONLY in self._currency_modes(row)

    def in_currency(self, row: int) -> bool:
        """The line is (or has to be) in a currency: its currency cells are in use.
        A line on 60 / 62 with a local partner stays in manat and shows none of them."""
        return self.currency_required(row) or (
            self.is_currency(row) and self.rows[row].currency_id is not None
        )

    def takes_invoice(self, row: int) -> bool:
        """The line is on a settlement or ƏDV account: it may name its e-qaimə."""
        r = self.rows[row]
        return not self.formulas and (
            self.catalog.takes_invoice(r.debit) or self.catalog.takes_invoice(r.credit)
        )

    def kind_at(self, row: int, col: int) -> int | None:
        """Subconto kind required at this cell, or None if the cell doesn't apply."""
        side, pos = column_role(col)
        if pos is None:
            return None
        account_id = getattr(self.rows[row], side)
        if account_id is None:
            return None
        return self.catalog.accounts[account_id].sc_kinds[pos - 1]

    def applies(self, row: int, col: int) -> bool:
        if col == CURRENCY:
            return self.is_currency(row)
        if col in CURRENCY_COLUMNS:
            return self.in_currency(row)
        if col == INVOICE:
            return self.takes_invoice(row)
        _, pos = column_role(col)
        return pos is None or self.kind_at(row, col) is not None

    def flags(self, index):
        if not self.applies(index.row(), index.column()):
            return Qt.ItemFlag.NoItemFlags
        flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        if not self.read_only:
            flags |= Qt.ItemFlag.ItemIsEditable
        return flags

    def data(self, index, role: int = Qt.ItemDataRole.DisplayRole):
        row, col = index.row(), index.column()
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            return self._text(row, col, display=role == Qt.ItemDataRole.DisplayRole)
        if role == Qt.ItemDataRole.ForegroundRole:
            return self._foreground(row, col)
        if role == Qt.ItemDataRole.FontRole and self._is_placeholder(row, col):
            return fonts().cell_italic
        if role == Qt.ItemDataRole.TextAlignmentRole:
            return ALIGN_RIGHT if col in NUMBER_COLUMNS else ALIGN_LEFT
        if role == Qt.ItemDataRole.ToolTipRole:
            side, pos = column_role(col)
            if side in ("debit", "credit") and pos is None:
                account_id = getattr(self.rows[row], side)
                return self.catalog.accounts[account_id].label if account_id else None
        return None

    def _is_placeholder(self, row: int, col: int) -> bool:
        """An empty subconto cell, which shows the name of its kind instead."""
        side, pos = column_role(col)
        return pos is not None and getattr(self.rows[row], f"{side}_sc")[pos - 1] is None

    def _text(self, row: int, col: int, display: bool) -> str:
        r = self.rows[row]
        side, pos = column_role(col)
        if side in ("debit", "credit"):
            if r.invoice_auto:
                r.invoice = ""
                r.invoice_auto = False
            if pos is None:
                account_id = getattr(r, side)
                return self.catalog.accounts[account_id].short if account_id else ""
            return self._subconto_text(row, col, getattr(r, f"{side}_sc")[pos - 1], display)
        if side == "amount" and self.formulas:
            return r.formula
        if side in ("currency", "currency_amount", "rate") and not self.in_currency(row):
            return ""
        if side == "invoice":
            return r.invoice if self.takes_invoice(row) else ""
        if side == "currency":
            currency = self.catalog.currencies.get(r.currency_id or 0)
            return currency.code if currency else ""
        if side == "rate":
            return "" if r.rate is None else format_unit_rate(r.rate)
        if side in ("amount", "currency_amount"):
            value = getattr(r, side)
            if value is None:
                return ""
            text = format_minor(value)
            return text if display else text.replace(" ", "")
        return r.memo

    def _subconto_text(self, row: int, col: int, value_id: int | None, display: bool) -> str:
        if value_id is not None:
            return self.catalog.value(value_id).name
        kind = self.kind_at(row, col)
        if kind is None or not display or self.read_only:
            return ""
        return self.catalog.kinds[kind]

    def _foreground(self, row: int, col: int) -> QColor | None:
        side, _ = column_role(col)
        if self._is_placeholder(row, col):
            return QColor(P.tertiary)  # placeholder with the subconto kind name
        if side in ("amount", "currency_amount"):
            value = getattr(self.rows[row], side)
            return QColor(P.red) if value is not None and value < 0 else None
        if side == "rate":
            return QColor(P.secondary)
        return None

    def setData(self, index, value, role: int = Qt.ItemDataRole.EditRole) -> bool:
        if self.read_only or role != Qt.ItemDataRole.EditRole:
            return False
        row, col = index.row(), index.column()
        r = self.rows[row]
        side, pos = column_role(col)
        if side in ("debit", "credit"):
            if pos is None:
                self._set_account(r, side, value)
            else:
                getattr(r, f"{side}_sc")[pos - 1] = value
                self._fit_owned(r, side)
            self._fit_currency(row)
            if self.inherit_invoices:
                self._sync_invoice(row)
        elif side in ("currency", "currency_amount", "rate"):
            self._set_currency_field(r, side, value)
        elif side == "invoice":
            r.invoice = value or ""
            r.invoice_auto = False
            if r.invoice and self.inherit_invoices:
                self._spread_invoice(row)
        elif side == "amount":
            if self.formulas:
                r.formula = value
            elif isinstance(value, InCurrency):  # "500 EUR" typed in the amount cell
                self._set_currency_field(r, "currency", value.currency_id)
                self._set_currency_field(r, "currency_amount", value.amount)
                side = "currency"  # the whole row changed
            else:
                r.amount = value
                r.formula = ""  # typed by hand: no longer follows the operation amount
        else:
            r.memo = value
        if side in ("amount", "memo", "invoice"):
            self.dataChanged.emit(index, index)
        else:
            self._row_changed(row)
        self.changed.emit()
        return True

    def _invoice_keys(self, row: int) -> set[tuple[int, tuple[int | None, ...]]]:
        """Settlement account + its dimensions identify lines of the same invoice.

        Thus Dt 26 / Ct 60 and Dt 19 / Ct 60 meet on the same supplier/contract,
        while two suppliers in one document do not borrow each other's number.
        """
        r = self.rows[row]
        result: set[tuple[int, tuple[int | None, ...]]] = set()
        for side in ("debit", "credit"):
            account_id = getattr(r, side)
            if account_id is None:
                continue
            account = self.catalog.accounts[account_id]
            fallback = any(
                self.catalog.kind_codes.get(kind or 0) == "counterparty"
                for kind in account.sc_kinds
            )
            if account.account_type not in SETTLEMENT_TYPES and not fallback:
                continue
            values = tuple(getattr(r, f"{side}_sc"))
            incomplete = any(
                kind is not None and values[i] is None for i, kind in enumerate(account.sc_kinds)
            )
            if incomplete:
                continue
            result.add((account_id, values))
        return result

    def _sync_invoice(self, row: int) -> None:
        if self.rows[row].invoice:
            self._spread_invoice(row)
        else:
            self._inherit_invoice(row)

    def _spread_invoice(self, source: int) -> None:
        """Fill blank related lines; an explicitly different number is never touched."""
        keys = self._invoice_keys(source)
        if not keys:
            return
        invoice = self.rows[source].invoice
        for row, item in enumerate(self.rows):
            if (
                row == source
                or (item.invoice and not item.invoice_auto)
                or not keys.intersection(self._invoice_keys(row))
            ):
                continue
            item.invoice = invoice
            item.invoice_auto = True
            self.dataChanged.emit(self.index(row, INVOICE), self.index(row, INVOICE))

    def _inherit_invoice(self, row: int) -> None:
        """A line completed after its companion takes that companion's e-qaimə."""
        item = self.rows[row]
        keys = self._invoice_keys(row)
        if item.invoice or not keys:
            return
        numbers = {
            other.invoice
            for i, other in enumerate(self.rows)
            if i != row and other.invoice and keys.intersection(self._invoice_keys(i))
        }
        if len(numbers) == 1:
            item.invoice = numbers.pop()
            item.invoice_auto = True
            self.dataChanged.emit(self.index(row, INVOICE), self.index(row, INVOICE))

    def _set_account(self, r: PostingRow, side: str, account_id: int | None) -> None:
        """Set an account and drop subconto values its positions no longer accept."""
        setattr(r, side, account_id)
        kinds = self.catalog.accounts[account_id].sc_kinds if account_id else (None, None, None)
        sc = getattr(r, f"{side}_sc")
        for i, kind in enumerate(kinds):
            if sc[i] is not None and (kind is None or self.catalog.value(sc[i]).kind_id != kind):
                sc[i] = None

    def _fit_owned(self, r: PostingRow, side: str) -> None:
        """A contract of another counterparty than the one chosen leaves the line."""
        account_id = getattr(r, side)
        if account_id is None:
            return
        account = self.catalog.accounts[account_id]
        sc = getattr(r, f"{side}_sc")
        for pos, value_id in enumerate(sc):
            owner = self.catalog.owner_in(account, sc, pos)
            if value_id is not None and self.catalog.owned_elsewhere(value_id, owner):
                sc[pos] = None

    def _set_currency_field(self, r: PostingRow, side: str, value) -> None:
        if side == "currency":
            r.currency_id = value
            r.rate_auto = True
            r.rate = self.rate_for(value) if value is not None else None
            if value is None:  # back to manat (60 / 62): the manat amount stays
                r.currency_amount = None
        elif side == "currency_amount":
            r.currency_amount = value
        else:
            r.rate = value
            r.rate_auto = value is None
            if value is None and r.currency_id is not None:
                r.rate = self.rate_for(r.currency_id)
        self._follow_rate(r)

    # ---- currency ----------------------------------------------------------------------

    def _row_changed(self, row: int) -> None:
        self.dataChanged.emit(self.index(row, 0), self.index(row, len(HEADERS) - 1))

    def _fit_currency(self, row: int) -> None:
        """After an account or subconto changes: a line without currency accounts drops
        its currency; a currency line takes the currency of a chosen element (a USD bank
        account, a contract in EUR) when it has one."""
        r = self.rows[row]
        if not self.is_currency(row):
            r.currency_id = r.currency_amount = r.rate = None
            r.rate_auto = True
            return
        for side in ("debit", "credit"):
            account_id = getattr(r, side)
            if account_id is None or not self.catalog.accounts[account_id].currency:
                continue
            for value_id in getattr(r, f"{side}_sc"):
                currency_id = self.catalog.value(value_id).currency_id if value_id else None
                if currency_id is not None and currency_id != r.currency_id:
                    r.currency_id, r.rate_auto = currency_id, True
                    r.rate = self.rate_for(currency_id)
                    self._follow_rate(r)
                    return

    @staticmethod
    def _follow_rate(r: PostingRow) -> None:
        """The manat amount = amount in currency × rate."""
        if r.currency_amount is not None and r.rate is not None:
            r.amount = to_base(r.currency_amount, r.rate) or None
            r.formula = ""

    def refresh_rates(self) -> None:
        """The document date changed: lines on the offered rate take the new day's rate."""
        for row, r in enumerate(self.rows):
            if r.currency_id is not None and r.rate_auto:
                r.rate = self.rate_for(r.currency_id)
                self._follow_rate(r)
                self._row_changed(row)
        self.changed.emit()

    # ---- typed text -> values ----------------------------------------------------------

    def parse(self, row: int, col: int, text: str):
        """The value for a cell from what was typed or pasted; None for an empty text.
        Raises LookupError / ValueError (UnknownValue for a name not in a directory)."""
        text = text.strip()
        side, pos = column_role(col)
        if side == "invoice":
            return normalize_invoice(text) or ""
        if not text:  # text fields (memo, a template's formula) stay strings
            return "" if side == "memo" or (side == "amount" and self.formulas) else None
        if side in ("debit", "credit") and pos is None:
            return self.catalog.resolve_account(text).id
        if side in ("debit", "credit"):
            return self._parse_subconto(row, col, text)
        if side == "currency":
            return self.catalog.resolve_currency(text).id
        if side == "rate":
            return unit_rate(parse_rate(plain_number(text)))
        if side == "amount" and self.formulas:
            formula.parse(text)  # check now, not when the template is saved
            return text
        if side == "amount" and self.is_currency(row) and (found := self._in_currency(text)):
            return found
        if side in ("amount", "currency_amount"):
            if ARITHMETIC.search(text):  # a small calculator: 1180*18/118
                value = formula.evaluate(text)
            else:
                value = to_minor(plain_number(text))
            if value <= 0:
                raise ValueError(tr("сумма должна быть больше нуля"))
            return value
        return text

    def _parse_subconto(self, row: int, col: int, text: str) -> int:
        kind = self.kind_at(row, col)
        if kind is None:
            raise ValueError(tr("у счёта нет этого субконто: {text}", text=text))
        value = self.catalog.resolve_value(kind, text, self.owner_at(row, col))
        if value is None:
            raise UnknownValue(kind, text)
        return value

    def owner_at(self, row: int, col: int) -> int | None:
        """The counterparty chosen on the line for a contract cell (None: any contract)."""
        side, pos = column_role(col)
        account_id = getattr(self.rows[row], side) if pos is not None else None
        if account_id is None or pos is None:
            return None
        account = self.catalog.accounts[account_id]
        return self.catalog.owner_in(account, getattr(self.rows[row], f"{side}_sc"), pos - 1)

    def _in_currency(self, text: str) -> InCurrency | None:
        """ "500 EUR" / "EUR 500" in the amount cell of a line on 60 / 62 / 52."""
        m = CURRENCY_AMOUNT_TEXT.match(text)
        if not m:
            return None
        code = (m["code"] or m["code2"]).upper()
        currency = next((c for c in self.catalog.active_currencies if c.code == code), None)
        if currency is None:
            raise LookupError(tr("валюта «{text}» не найдена", text=code))
        amount = to_minor(plain_number(m["number"] or m["number2"]))
        if amount <= 0:
            raise ValueError(tr("сумма должна быть больше нуля"))
        return InCurrency(currency.id, amount)

    def paste(self, text: str, start_row: int, start_col: int, shown) -> PasteResult:
        """Put lines copied from Excel into the grid (see the module docstring).
        `shown(col)` tells whether a column is visible. A single line goes into the
        current row; more lines fill the current row if it is empty, then new rows."""
        lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        while lines and not lines[-1].strip():
            lines.pop()
        cells = [line.split("\t") for line in lines]
        result = PasteResult()
        if not cells:
            return result
        mapping = header_columns(cells[0])
        if mapping is not None:
            cells = cells[1:]
        target = start_row
        for n, line in enumerate(cells, start=1):
            if not any(c.strip() for c in line):
                continue
            needs_row = target >= len(self.rows) or not self.rows[target].is_empty()
            if (len(cells) > 1 or target >= len(self.rows)) and needs_row:
                self.insert_row(target)
            if mapping is not None:
                self._paste_by_header(target, line, mapping, n, result)
            else:
                self._paste_in_order(target, line, start_col, shown, n, result)
            result.rows += 1
            target += 1
        self.changed.emit()
        return result

    def _paste_by_header(self, row, line, mapping, n, result) -> None:
        # accounts first: their subconto columns apply only once the account is known
        order = sorted(
            (i for i, col in enumerate(mapping) if col is not None and i < len(line)),
            key=lambda i: (mapping[i] not in (DT, CT), mapping[i]),
        )
        for i in order:
            if line[i].strip():
                self._paste_cell(row, mapping[i], line[i], n, result)

    def _paste_in_order(self, row, line, start_col, shown, n, result) -> None:
        col = start_col
        for cell in line:
            while col < len(HEADERS) and not (shown(col) and self.applies(row, col)):
                col += 1
            if col >= len(HEADERS):
                if cell.strip():
                    result.errors.append(
                        tr("строка {n}: лишнее значение «{text}»", n=n, text=cell.strip())
                    )
                continue
            if cell.strip():
                self._paste_cell(row, col, cell, n, result)
            col += 1

    def _paste_cell(self, row, col, text, n, result) -> None:
        try:
            value = self.parse(row, col, text)
        except UnknownValue as e:
            result.unknown.append((row, col, e.kind_id, e.text))
            return
        except (LookupError, ValueError, TypeError, ValidationError) as e:
            result.errors.append(tr("строка {n}: {error}", n=n, error=str(e).strip("'\"")))
            return
        self.setData(self.index(row, col), value)

    def copy_text(self, shown) -> str:
        """The document as tab-separated lines with a header, for Excel."""
        columns = [c for c in range(len(HEADERS)) if shown(c)]

        def title(col: int) -> str:
            side, pos = column_role(col)
            if pos is not None:
                return f"{tr('Субконто')} {tr('Дт' if side == 'debit' else 'Кт')} {pos}"
            return tr(HEADERS[col])

        lines = ["\t".join(title(c) for c in columns)]
        for r, row in enumerate(self.rows):
            if row.is_empty():
                continue
            values = []
            for c in columns:
                if not self.applies(r, c):
                    values.append("")
                    continue
                value = self.data(self.index(r, c), Qt.ItemDataRole.EditRole)
                values.append("" if value is None else str(value))
            lines.append("\t".join(values))
        return "\n".join(lines) + "\n"

    # ---- row operations --------------------------------------------------------------

    def insert_row(self, at: int | None = None, row: PostingRow | None = None) -> int:
        at = len(self.rows) if at is None else at
        self.beginInsertRows(QModelIndex(), at, at)
        self.rows.insert(at, row or PostingRow())
        self.endInsertRows()
        self.changed.emit()
        return at

    def duplicate_row(self, i: int) -> int:
        src = self.rows[i]
        return self.insert_row(
            i + 1,
            PostingRow(
                src.debit,
                list(src.debit_sc),
                src.credit,
                list(src.credit_sc),
                src.amount,
                src.memo,
                src.formula,
                src.currency_id,
                src.currency_amount,
                src.rate,
                src.rate_auto,
                src.invoice,
                src.invoice_kind,
            ),
        )

    def recalculate(self, total: int | None) -> str | None:
        """Set the amounts of rows that have a formula for the operation amount S.
        Rows typed by hand take part with their amount. Returns an error text, if any."""
        if not any(r.formula for r in self.rows):
            return None
        sources = [
            r.formula or (format_minor(r.amount).replace(" ", "") if r.amount else "")
            for r in self.rows
        ]
        try:
            amounts = formula.compute(sources, total) if total else [None] * len(sources)
        except ValidationError as e:
            return str(e)
        for r, amount in zip(self.rows, amounts, strict=True):
            if r.formula:
                r.amount = amount if amount and amount > 0 else None
        self.dataChanged.emit(self.index(0, AMOUNT), self.index(len(self.rows) - 1, AMOUNT))
        self.changed.emit()
        return None

    def remove_row(self, i: int) -> None:
        self.beginRemoveRows(QModelIndex(), i, i)
        del self.rows[i]
        self.endRemoveRows()
        if not self.rows:
            self.insert_row()
        self.changed.emit()

    def total(self) -> int:
        return sum(abs(r.amount or 0) for r in self.rows)

    def to_inputs(self) -> list[PostingInput]:
        result = []
        for n, r in enumerate(self.rows, start=1):
            if r.is_empty():
                continue
            if r.debit is None:
                raise ValidationError(tr("строка {line}: не указан счёт дебета", line=n))
            if r.credit is None:
                raise ValidationError(tr("строка {line}: не указан счёт кредита", line=n))
            if r.amount is None:
                raise ValidationError(tr("строка {line}: не указана сумма", line=n))
            currency = self.is_currency(n - 1) and r.currency_id is not None
            result.append(
                PostingInput(
                    r.debit,
                    r.credit,
                    Decimal(r.amount).scaleb(-SCALE),
                    tuple(r.debit_sc),
                    tuple(r.credit_sc),
                    r.memo.strip(),
                    r.currency_id if currency else None,
                    Decimal(r.currency_amount or 0).scaleb(-SCALE) if currency else None,
                    r.invoice if self.takes_invoice(n - 1) else "",
                    r.invoice_kind if self.takes_invoice(n - 1) and r.invoice else "",
                )
            )
        if not result:
            raise ValidationError(tr("в документе нет проводок"))
        return result


class PickWithKeys(QObject):
    """On the open list, Enter or Tab takes the highlighted item."""

    KEYS = (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Tab)

    def __init__(self, popup, choose) -> None:
        super().__init__(popup)
        self.choose = choose
        popup.installEventFilter(self)  # installed after QCompleter's, so it runs first

    def eventFilter(self, popup, event) -> bool:
        if event.type() == QEvent.Type.KeyPress and event.key() in self.KEYS:
            index = popup.currentIndex()
            if popup.isVisible() and index.isValid():
                popup.hide()
                self.choose(index.data())
                return True
        return False


def fit_popup(popup: QAbstractItemView, rows: int, most: int = 12) -> None:
    """Height for exactly the rows shown: Qt does not count the popup's padding, so a
    short list would get a scroll bar."""
    shown = min(rows, most)
    margins = popup.contentsMargins()
    padding = 8 + margins.top() + margins.bottom()  # theme: QListView#completer padding 4px
    popup.setFixedHeight(popup.sizeHintForRow(0) * shown + padding)


def attach_list(
    editor: QLineEdit,
    items: list[str],
    show_all: bool,
    chosen,
    subaccounts: Callable[[str], list[str] | None] | None = None,
) -> Callable[[], None]:
    """Completion list under a cell editor; `chosen(editor, text)` gets the picked item.
    `subaccounts(text)` lists the accounts of a group typed in full ("68"): they are
    offered with none taken, so Enter does not pick 68.1 behind the user's back.
    Returns `pick_first()`: the list again with its first item highlighted."""
    model = QStringListModel(editor)
    completer = QCompleter(model, editor)
    completer.setCompletionMode(QCompleter.CompletionMode.UnfilteredPopupCompletion)
    completer.setMaxVisibleItems(12)
    completer.setWidget(editor)  # filtering is ours (search), not Qt's prefix matching
    popup = cast(QAbstractItemView, completer.popup())
    popup.setObjectName("completer")

    def refresh(text: str, pick_first: bool = False) -> None:
        try:
            # asked anew each time: PySide may drop a kept wrapper of the parentless popup
            popup = cast(QAbstractItemView, completer.popup())
            typed = bool(text.strip())
            group = subaccounts(text) if subaccounts and typed else None
            if group is not None:
                matches = group
            else:
                matches = search(items, text) if (typed or show_all) else []
            if not text.strip().startswith(TEMPLATE_MARK):  # templates only after "#"
                matches = [m for m in matches if not m.startswith(TEMPLATE_MARK)]
            model.setStringList(matches)
            if not matches:
                popup.hide()
                return
            rect = editor.rect()
            rect.setWidth(max(rect.width(), 380))
            completer.complete(rect)
            fit_popup(popup, len(matches))
            if (typed and group is None) or pick_first:  # Enter takes the best match
                popup.setCurrentIndex(model.index(0))
            else:  # the completer puts its cursor on the first row on showing the list
                popup.selectionModel().clear()
        except RuntimeError:  # editor already closed
            pass

    editor.textEdited.connect(refresh)
    # mouse click; the str overload of the signal is not in the PySide6 stubs
    completer.activated[str].connect(  # pyright: ignore[reportIndexIssue]
        lambda text: chosen(editor, text)
    )
    # Enter / Tab on a highlighted item: Qt would hand the key to the editor *before*
    # reporting the choice, so the editor would commit what was typed (often nothing).
    PickWithKeys(popup, lambda text: chosen(editor, text))
    QTimer.singleShot(0, lambda: refresh(editor.text()))
    return lambda: refresh(editor.text(), pick_first=True)


class CellEditor(QLineEdit):
    """A cell editor; an account cell keeps how to reopen its list on a group."""

    pick_first: Callable[[], None] | None = None
    catalog: Catalog | None = None


def attach_account_list(editor: CellEditor, items: list[str], catalog: Catalog, chosen) -> None:
    """The list of an account cell: suggestions from the first typed character, and a
    group typed in full ("68") lists its accounts (see `holds_on_group`)."""

    def subaccounts(text: str) -> list[str] | None:
        group = catalog.group_named(text)
        return [a.label for a in catalog.subaccounts(group)] if group else None

    editor.catalog = catalog
    editor.pick_first = attach_list(editor, items, False, chosen, subaccounts)


def holds_on_group(editor: QLineEdit, error: SignalInstance) -> bool:
    """Enter on a group in an account cell: a group is not posted to, so the editor
    stays open, says so, and highlights the group's first account. True if held."""
    if not isinstance(editor, CellEditor) or editor.catalog is None or not editor.pick_first:
        return False
    group = editor.catalog.group_named(editor.text())
    if group is None:
        return False
    error.emit(tr("{code} — группа: выберите субсчёт из списка", code=group.short))
    QTimer.singleShot(0, editor.pick_first)  # after the completer hides its popup
    return True


class PostingsDelegate(QStyledItemDelegate):
    """Line editors with completion for accounts and subconto; Enter = next cell."""

    error = Signal(str)
    unknown_value = Signal(QPersistentModelIndex, int, str)  # index, kind_id, typed text
    template_chosen = Signal(int, int)  # row, entry template id

    def __init__(self, catalog: Catalog, parent=None, hints: EntryHints | None = None) -> None:
        super().__init__(parent)
        self.catalog = catalog
        self.hints = hints or EntryHints()

    def _template_items(self) -> list[str]:
        return [f"{TEMPLATE_MARK}{name}" for _, name in self.hints.templates()]

    def _subconto_items(self, model, row: int, col: int) -> list[str]:
        """The directory with the elements recently used on this account first."""
        kind = model.kind_at(row, col)
        if kind is None:
            return []
        side, pos = column_role(col)
        values = self.catalog.values(kind, model.owner_at(row, col))
        account = getattr(model.rows[row], side)
        active = {v.id for v in values}
        recent = (
            [v for v in self.hints.recent(account, pos) if v in active]
            if account and pos is not None
            else []
        )
        rest = [v for v in values if v.id not in set(recent)]
        return [self.catalog.value(v).label for v in recent] + [v.label for v in rest]

    def createEditor(self, parent, option, index):
        editor = CellEditor(parent)
        editor.setFrame(False)
        editor.setProperty("gl_row", index.row())
        side, pos = column_role(index.column())
        model = index.model()
        if side in ("debit", "credit") and pos is None:
            items = [a.label for a in self.catalog.leaf_accounts]
            if side == "debit" and not model.formulas:
                items += self._template_items()
            # an account cell shows suggestions from the first typed character
            attach_account_list(editor, items, self.catalog, self._chosen)
        elif side in ("debit", "credit"):
            # a subconto cell opens with its whole list, like a 1C directory
            items = self._subconto_items(model, index.row(), index.column())
            attach_list(editor, items, True, self._chosen)
        elif side == "currency":
            attach_list(
                editor, [c.label for c in self.catalog.active_currencies], True, self._chosen
            )
        elif index.column() in NUMBER_COLUMNS:
            editor.setAlignment(ALIGN_RIGHT)
        # Enter forwarded by an open popup reaches the editor as returnPressed.
        editor.returnPressed.connect(lambda e=editor: self._commit_and_next(e))
        return editor

    def _chosen(self, editor: QLineEdit, text: str) -> None:
        editor.setText(text)
        self._commit_and_next(editor)

    def setEditorData(self, editor, index):
        if editor.text():  # keep the key that started editing
            return
        editor.setText(index.data(Qt.ItemDataRole.EditRole) or "")
        model = index.model()
        r = model.rows[index.row()]
        if (
            column_role(index.column())[0] == "memo"
            and not r.memo
            and r.debit is not None
            and r.credit is not None
            and not model.read_only
        ):
            hint = self.hints.memo(r.debit, r.credit)
            if hint:  # offered selected: Enter takes it, typing replaces it
                editor.setText(hint)
                editor.selectAll()

    def _template(self, text: str) -> int | None:
        needle = fold(text.strip()[len(TEMPLATE_MARK) :])
        templates = self.hints.templates()
        found = [t for t in templates if fold(t[1]) == needle] or [
            t for t in templates if fold(t[1]).startswith(needle)
        ]
        if len(found) != 1:
            return None
        return found[0][0]

    def setModelData(self, editor, model, index):
        text = editor.text().strip()
        if (
            text.startswith(TEMPLATE_MARK)
            and index.column() == DT
            and not model.formulas
            and self.hints.templates()
        ):
            template_id = self._template(text)
            if template_id is None:
                self.error.emit(tr("шаблон «{name}» не найден или не один", name=text[1:]))
            else:
                self.template_chosen.emit(index.row(), template_id)
            return
        try:
            value = model.parse(index.row(), index.column(), editor.text())
        except UnknownValue as e:
            self.unknown_value.emit(QPersistentModelIndex(index), e.kind_id, e.text)
            return
        except (LookupError, ValueError, TypeError, ValidationError) as e:
            self.error.emit(str(e).strip("'\""))
            return
        model.setData(index, value)

    def eventFilter(self, editor, event):
        if event.type() == QEvent.Type.KeyPress and event.key() in (
            Qt.Key.Key_Return,
            Qt.Key.Key_Enter,
        ):
            self._commit_and_next(editor)
            return True
        return super().eventFilter(editor, event)

    def _commit_and_next(self, editor) -> None:
        if editor.property("gl_done"):
            return
        if holds_on_group(editor, self.error):
            return
        editor.setProperty("gl_done", True)
        self.commitData.emit(editor)
        self.closeEditor.emit(editor, QAbstractItemDelegate.EndEditHint.EditNextItem)


class PostingsTable(QTableView):
    def __init__(self, model: PostingsModel, delegate: PostingsDelegate) -> None:
        super().__init__()
        self.setModel(model)
        self.setItemDelegate(delegate)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectItems)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setEditTriggers(
            QAbstractItemView.EditTrigger.AnyKeyPressed
            | QAbstractItemView.EditTrigger.EditKeyPressed
            | QAbstractItemView.EditTrigger.DoubleClicked
        )
        self.setShowGrid(False)
        self.setWordWrap(False)
        self.setTabKeyNavigation(True)
        vh = self.verticalHeader()
        vh.setDefaultSectionSize(34)
        vh.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        vh.setDefaultAlignment(Qt.AlignmentFlag.AlignCenter)
        hh = self.horizontalHeader()
        hh.setHighlightSections(False)
        self.setColumnWidth(DT, 78)
        self.setColumnWidth(CT, 78)
        for col, w in (
            (CURRENCY, 64),
            (CURRENCY_AMOUNT, 110),
            (RATE, 72),
            (AMOUNT, 120),
            (INVOICE, 150),
        ):
            self.setColumnWidth(col, w)
        hh.setSectionResizeMode(MEMO, QHeaderView.ResizeMode.Stretch)
        used = model.catalog.used_positions()
        for pos in (1, 2, 3):
            if pos not in used:
                self.setColumnHidden(DT + pos, True)
                self.setColumnHidden(CT + pos, True)
        self._shown: tuple[bool, bool] | None = None
        self._fit_columns()
        model.changed.connect(self._fit_columns)
        model.modelReset.connect(self._fit_columns)

    def _fit_columns(self) -> None:
        """Currency columns appear only while a line is in a currency, the e-qaimə column
        while a line is on a settlement or ƏDV account."""
        m = self.model()
        rows = range(m.rowCount())
        shown = (any(m.in_currency(r) for r in rows), any(m.takes_invoice(r) for r in rows))
        if shown == self._shown:
            return
        self._shown = shown
        for col in CURRENCY_COLUMNS:
            self.setColumnHidden(col, not shown[0])
        self.setColumnHidden(INVOICE, not shown[1])
        self._fit_subconto_widths()

    MEMO_MIN = 200  # the memo keeps room to be read
    SUBCONTO_WIDTH = (100, 180)  # each subconto column, narrowest and widest

    def _fit_subconto_widths(self) -> None:
        """Subconto columns share what the window leaves after the fixed columns and the
        memo: a wide window shows whole names, a narrow one keeps the memo in view."""
        subconto = [
            base + pos
            for base in (DT, CT)
            for pos in (1, 2, 3)
            if not self.isColumnHidden(base + pos)
        ]
        if not subconto:
            return
        fixed = sum(
            self.columnWidth(c)
            for c in range(len(HEADERS))
            if c not in subconto and c != MEMO and not self.isColumnHidden(c)
        )
        free = self.viewport().width() - self.verticalHeader().width() - fixed - self.MEMO_MIN
        low, high = self.SUBCONTO_WIDTH
        width = max(low, min(high, free // len(subconto)))
        for col in subconto:
            self.setColumnWidth(col, width)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._fit_subconto_widths()

    def model(self) -> PostingsModel:  # typed accessor
        return cast(PostingsModel, super().model())

    def _last_enabled_column(self, row: int) -> int:
        cols = [
            c
            for c in range(len(HEADERS))
            if not self.isColumnHidden(c) and self.model().applies(row, c)
        ]
        return cols[-1]

    def closeEditor(self, editor, hint):
        idx = self.currentIndex()
        m = self.model()
        if (
            hint == QAbstractItemDelegate.EndEditHint.EditNextItem
            and idx.isValid()
            and idx.row() == m.rowCount() - 1
            and idx.column() == self._last_enabled_column(idx.row())
        ):
            super().closeEditor(editor, QAbstractItemDelegate.EndEditHint.NoHint)
            row = m.insert_row()
            new = m.index(row, self._first_enabled_column(row))
            self.setCurrentIndex(new)
            self.edit(new)
            return
        super().closeEditor(editor, hint)

    def _first_enabled_column(self, row: int) -> int:
        return next(
            c
            for c in range(len(HEADERS))
            if not self.isColumnHidden(c) and self.model().applies(row, c)
        )

    def keyPressEvent(self, event):
        if (
            event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
            and not event.modifiers() & Qt.KeyboardModifier.ControlModifier
            and self.state() != QAbstractItemView.State.EditingState
        ):
            idx = self.currentIndex()
            if idx.isValid() and idx.flags() & Qt.ItemFlag.ItemIsEditable:
                self.edit(idx)
                return
        super().keyPressEvent(event)
