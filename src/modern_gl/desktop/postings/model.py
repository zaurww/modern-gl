"""The lines of a GL document as a table model: what each cell shows and takes; which
cells a line has and the clipboard are in their own modules."""

from __future__ import annotations

from PySide6.QtCore import (
    QModelIndex,
    Qt,
)
from PySide6.QtGui import QColor

from modern_gl.application.ledger import PostingInput
from modern_gl.application.ledger.inputs import typed_posting
from modern_gl.desktop.postings.clipboard import PostingsClipboard
from modern_gl.desktop.postings.columns import (
    ALIGN_LEFT,
    ALIGN_RIGHT,
    AMOUNT,
    INVOICE,
    InCurrency,
    PostingRow,
    column_role,
)
from modern_gl.desktop.theme import P
from modern_gl.domain import formula
from modern_gl.domain.accounts import SETTLEMENT_TYPES
from modern_gl.domain.currency import (
    format_unit_rate,
    to_base,
)
from modern_gl.domain.errors import ValidationError
from modern_gl.domain.money import format_minor
from modern_gl.i18n import tr


class PostingsModel(PostingsClipboard):
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
            invoice = self.takes_invoice(n - 1)
            result.append(
                typed_posting(
                    n,
                    r,
                    currency=self.is_currency(n - 1),
                    invoice=invoice,
                    invoice_kind=r.invoice_kind if invoice else "",
                    pays_vat=r.pays_vat,
                )
            )
        if not result:
            raise ValidationError(tr("в документе нет проводок"))
        return result
