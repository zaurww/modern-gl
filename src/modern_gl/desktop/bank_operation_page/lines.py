"""The lines of the payment: suggested (as last time, else by the kind), added, copied,
removed; a line paying several e-qaimə; Enter and Tab in the order things are typed."""

from __future__ import annotations

from dataclasses import replace
from itertools import pairwise

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QWidget,
)

from modern_gl.application.bank import (
    FEE,
    KIND_TYPES,
    OTHER,
    TRANSFER,
    BankLine,
    last_lines,
    transfer_targets,
)
from modern_gl.desktop.bank_operation_page.common import (
    TYPE_KINDS,
    select_data,
)
from modern_gl.desktop.bank_operation_page.form import BankOperationForm
from modern_gl.desktop.bank_operation_page.line_row import LineRow
from modern_gl.desktop.invoice_picker import InvoicePicker
from modern_gl.domain.accounts import BANK_FEE
from modern_gl.domain.money import to_minor
from modern_gl.i18n import trd


class LinesPart(BankOperationForm):
    def _suggest(self) -> None:
        """Lines as last time for this counterparty (D47), else the kind's account."""
        if self.counterparty is None:
            self._default_lines()
            return
        found = last_lines(self.s.conn, self.s.company_id, self.direction_value, self.counterparty)
        if not found:
            self._default_lines()
            return
        amount = self.line_rows[0].amount.text() if self.line_rows else ""
        for row in list(self.line_rows):
            self._remove_line(row, changed=False)
        for line in found:
            self.add_line().set_line(line, amount=False)
        self.line_rows[0].amount.setText(amount)
        account = self.s.catalog.accounts.get(found[0].account_id or 0)
        if self.kind.currentData() == OTHER and account is not None:
            select_data(self.kind, TYPE_KINDS.get(account.account_type or "", OTHER))

    def _default_lines(self) -> None:
        """The first line takes the account of the kind: 60, 62, 68…, the bank fee, or
        another bank account in the same currency for a transfer."""
        if not self.line_rows:
            return
        row = self.line_rows[0]
        line = self._kind_line()
        if line is None:
            return
        row.set_line(line, amount=False)

    def _kind_line(self) -> BankLine | None:
        kind = self.kind.currentData()
        catalog = self.s.catalog
        if kind == FEE:
            account_id = self.s.ledger.account_role(self.s.company_id, BANK_FEE)
            return BankLine(account_id, 0, self._fee_subconto(account_id))
        if kind == TRANSFER:
            own = (self.account.currentData(), self.bank_subconto()[0])
            others = transfer_targets(
                self.s.conn, self.s.company_id, own, self.currency.currentData()
            )
            return BankLine(others[0].account_id, 0, others[0].subconto) if others else None
        account_type = KIND_TYPES.get(kind)
        if account_type is None:
            return None
        found = next((a for a in catalog.leaf_accounts if a.account_type == account_type), None)
        return BankLine(found.id, 0) if found else None

    def _fee_subconto(self, account_id: int | None) -> tuple[int | None, ...]:
        """The item «Комиссия банка» of the fee account (made on first use, as a
        conversion makes it)."""
        if account_id is None:
            return ()
        values = self.s.ledger.bank.named_subconto(
            self.s.company_id, account_id, trd("Комиссия банка")
        )
        self.s.catalog.reload()
        return values

    def add_line(self, focus: bool = False, at: int | None = None) -> LineRow:
        row = LineRow(self.s)
        row.set_counterparty(self.counterparty)
        row.set_invoices(self.open_invoices)
        row.several.connect(lambda r: QTimer.singleShot(0, lambda: self._pay_several(r)))
        row.set_read_only(self.read_only)
        row.changed.connect(self._changed)
        row.edited.connect(self._line_edited)
        row.removed.connect(self._remove_line)
        row.unknown.connect(self._add_line_value)
        row.added.connect(lambda r, p, text: self._add_line_value(r, p, text, True))
        row.error.connect(self.show_error)
        at = len(self.line_rows) if at is None else at
        self.line_rows.insert(at, row)
        self.lines_box.insertWidget(at, row)
        self._chain()
        self._layout_lines()
        if focus:
            row.account.setFocus()
        return row

    def _insert_line(self) -> None:
        if not self.read_only:
            self._unfolded = True
            self.add_line(focus=True)

    def _current_line(self) -> LineRow | None:
        focused = QApplication.focusWidget()
        return next((r for r in self.line_rows if focused and r.isAncestorOf(focused)), None)

    def _duplicate_line(self) -> None:
        """F9: one more line like this one (another e-qaimə of the same supplier)."""
        row = self._current_line()
        if row is None or self.read_only or (line := row.value()) is None:
            return
        self._unfolded = True
        copy = self.add_line()
        copy.set_line(replace(line, invoice=""))
        (copy.amount if copy.invoice.isHidden() else copy.invoice).setFocus()
        self._changed()

    def _remove_current_line(self) -> None:
        """Ctrl+Del: the line the cursor is in; the cursor goes to the one above."""
        row = self._current_line()
        if row is None or self.read_only:
            return
        at = self.line_rows.index(row)
        self._remove_line(row)
        if self.line_rows:
            self.line_rows[max(at - 1, 0)].account.setFocus()

    def _remove_line(self, row: LineRow, changed: bool = True) -> None:
        self.line_rows.remove(row)
        self.lines_box.removeWidget(row)
        row.hide()  # out of the Enter / Tab order at once
        row.deleteLater()
        self._layout_lines()
        if changed:
            self._changed()

    def _line_edited(self) -> None:
        if not self._loading:
            self._lines_edited = True

    def _add_line_value(self, row: LineRow, position: int, text: str, listed=False) -> None:
        """A contract (or any element of the line's account) added right here."""
        account = row.account_info
        kind = account.sc_kinds[position] if account else None
        if kind is None or self.read_only:
            return
        value = self._new_value(listed, kind, text, owner_id=row.owner_of(position))
        if value is None:
            return
        row.set_subconto(position, value)
        self._focus_after(row.sc[position], listed)

    def _pay_several(self, row: LineRow) -> None:
        """One payment over several e-qaimə: a line for each, the same account; the
        amount typed in the line is spread oldest first, what is left — an advance."""
        typed = row.amount.text().strip()
        try:
            total = to_minor(typed) if typed else None
        except ValueError:
            total = None
        picker = InvoicePicker(self.open_invoices, total, self)
        if picker.exec() != QDialog.DialogCode.Accepted:
            (self.invoice if self.folded else row.invoice).setFocus()
            return
        line = row.value() or BankLine(row.account.currentData(), 0, row.subconto())
        at = self.line_rows.index(row)
        parts = [*picker.chosen, *([("", picker.left)] if picker.left else [])]
        for n, (invoice, amount) in enumerate(parts):
            target = row if n == 0 else self.add_line(at=at + n)
            target.set_line(replace(line, amount=amount, invoice=invoice))
        self._lines_edited = True
        self._unfolded |= len(parts) > 1
        self._changed()
        self._amount_of(self.line_rows[at + len(parts) - 1]).setFocus()

    def _chain(self) -> None:
        """Enter and Tab go in the order things are typed: who, the e-qaimə and amount (or
        the lines), «Провести»; the bank, day and kind before them (Shift+Tab), the
        statement reference and the purpose after (the lines are made later than the
        buttons below them, so Qt's own order would put them last)."""
        fields: list[QWidget] = [self.btn_out, self.btn_in, self.bank, self.currency, self.date]
        fields += [self.kind, self.counterparty_edit, self.invoice, self.amount, self.vat_amount]
        for row in self.line_rows:
            fields += [row.account, *row.sc, row.invoice, row.amount]
        fields += [self.btn_post, self.reference, self.deposit, self.deposit_date, self.memo]
        for first, second in pairwise(fields):
            QWidget.setTabOrder(first, second)

    def add_fee(self) -> None:
        """A bank fee taken with the payment: a line on the fee account."""
        account_id = self.s.ledger.account_role(self.s.company_id, BANK_FEE)
        self._unfolded = True
        row = self.add_line()
        row.set_line(BankLine(account_id, 0, self._fee_subconto(account_id)), amount=False)
        row.amount.setFocus()
        self._changed()

    def _fee_key(self) -> None:
        if not self.read_only:
            self.add_fee()
