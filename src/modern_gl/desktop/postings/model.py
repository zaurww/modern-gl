"""The lines of a GL document as a table model."""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal
from fractions import Fraction

from PySide6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    QPersistentModelIndex,
    Qt,
    Signal,
)
from PySide6.QtGui import QColor

from modern_gl.application.catalog import Catalog
from modern_gl.application.ledger import PostingInput
from modern_gl.desktop.postings.columns import (
    ALIGN_LEFT,
    ALIGN_RIGHT,
    AMOUNT,
    ARITHMETIC,
    CT,
    CURRENCY,
    CURRENCY_AMOUNT_TEXT,
    CURRENCY_COLUMNS,
    DT,
    HEADERS,
    INVOICE,
    NUMBER_COLUMNS,
    InCurrency,
    PasteResult,
    PostingRow,
    UnknownValue,
    column_role,
    header_columns,
    plain_number,
)
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
from modern_gl.i18n import tr


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
            return ALIGN_RIGHT if self.is_number(section) else ALIGN_LEFT
        return None

    def column_order(self) -> list[int]:
        """Columns in the order they are shown, typed and pasted."""
        return list(range(self.columnCount()))

    def is_number(self, col: int) -> bool:
        return col in NUMBER_COLUMNS

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
            return ALIGN_RIGHT if self.is_number(col) else ALIGN_LEFT
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
            # An inherited number belongs to the old account/dimensions.  Drop it only
            # when the user actually changes that key; merely painting the cell must
            # never mutate the row (and used to make inherited numbers disappear).
            self._clear_auto_invoice(r)
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

    @staticmethod
    def _clear_auto_invoice(row: PostingRow) -> None:
        if row.invoice_auto:
            row.invoice = ""
            row.invoice_auto = False

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
        self.dataChanged.emit(self.index(row, 0), self.index(row, self.columnCount() - 1))

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
        mapping = self.header_columns(cells[0])
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

    def header_columns(self, cells: list[str]) -> list[int | None] | None:
        return header_columns(cells)

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
        order = self.column_order()
        at = order.index(start_col)
        for cell in line:
            while at < len(order) and not (shown(order[at]) and self.applies(row, order[at])):
                at += 1
            if at >= len(order):
                if cell.strip():
                    result.errors.append(
                        tr("строка {n}: лишнее значение «{text}»", n=n, text=cell.strip())
                    )
                continue
            if cell.strip():
                self._paste_cell(row, order[at], cell, n, result)
            at += 1

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
        columns = [c for c in self.column_order() if shown(c)]

        def title(col: int) -> str:
            side, pos = column_role(col)
            if pos is not None:
                return f"{tr('Субконто')} {tr('Дт' if side == 'debit' else 'Кт')} {pos}"
            return str(self.headerData(col, Qt.Orientation.Horizontal))

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
