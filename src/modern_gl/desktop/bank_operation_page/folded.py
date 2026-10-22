"""One line, folded: its e-qaimə and amount typed above the lines, and the ƏDV deposit
part typed beside the amount (D69)."""

from __future__ import annotations

from PySide6.QtCore import QTimer

from modern_gl.application.bank import (
    IN,
    BankOperationInput,
    BankPlace,
    split_by_deposit,
    vat_deposit_part,
)
from modern_gl.desktop.bank_operation_page.common import (
    SEVERAL,
)
from modern_gl.desktop.bank_operation_page.form import BankOperationForm
from modern_gl.desktop.conversion_page.common import amount_text
from modern_gl.desktop.widgets import (
    edited_date,
)
from modern_gl.domain.money import format_minor, to_minor
from modern_gl.i18n import tr
from modern_gl.reporting.invoices import OpenInvoice


class FoldedPart(BankOperationForm):
    def unfold(self) -> None:
        self._unfolded = True
        self._layout_lines()
        if self.line_rows:
            self.line_rows[0].account.setFocus()

    def _layout_lines(self) -> None:
        folded = self.folded
        for row in self.line_rows:
            row.setVisible(not folded)
        self.lines_header.setVisible(not folded and bool(self.line_rows))
        self.total_row.setVisible(not folded)
        self.summary.setVisible(folded)
        self.btn_unfold.setVisible(folded and not self.read_only)
        for w in (self.amount_caption, self.amount, self.amount_currency):
            w.setVisible(folded)
        deposit = self.deposit_shown
        for w in (self.vat_caption, self.vat_amount, self.vat_currency):
            w.setVisible(deposit)
        for w in (self.deposit_caption, self.deposit, self.deposit_date):
            w.setVisible(deposit)
        into = self.direction_value == IN
        if deposit:
            self.amount_caption.setText(tr("В банк") if into else tr("Из банка"))
            self.vat_caption.setText(tr("На депозит ƏDV") if into else tr("С депозита ƏDV"))
        else:
            self.amount_caption.setText(tr("Сумма"))
        self._show_check()
        row = self.line_rows[0] if folded else None
        takes = row is not None and not row.invoice.isHidden()  # its account takes e-qaimə
        self.invoice_caption.setVisible(takes)
        self.invoice.setVisible(takes)
        if row is None:
            return
        # the fields above show the line (set only when different: the cursor stays put)
        if self.invoice.text() != row.invoice.text():
            self.invoice.setText(row.invoice.text())
        if self.amount.text() != row.amount.text():
            self.amount.setText(row.amount.text())
        parts = [row.account.text() or tr("Счёт не выбран")]
        parts += [box.text() or box.placeholderText() for box in row.sc if not box.isHidden()]
        self.summary_text.setText("  ·  ".join(parts))

    def _invoice_chosen(self, index: int) -> None:
        """An e-qaimə from the list above: the line's, with what is left to pay on it."""
        if not self.line_rows:
            return
        row = self.line_rows[0]
        chosen = self.invoice.itemData(index) if index >= 0 else None
        if chosen == SEVERAL:
            QTimer.singleShot(0, lambda: self._pay_several(row))
            return
        i = row.invoice.findData(chosen) if chosen is not None else -1
        if i < 0:
            self._invoice_typed(self.invoice.text())
            return
        empty = not row.amount.text().strip() and not self.vat_amount.text().strip()
        if isinstance(chosen, OpenInvoice) and empty:
            on_deposit = not self.deposit_shown and self._on_deposit()
            bank, vat = split_by_deposit(chosen.amount, chosen.vat, self.deposit_shown, on_deposit)
            if self.deposit_shown or on_deposit:
                row.amount.setText(amount_text(bank))
            if self.deposit_shown:
                self.vat_amount.setText(amount_text(vat) if vat else "")
        row.invoice.setCurrentIndex(i)
        row.invoice.activated.emit(i)

    def _invoice_typed(self, text: str) -> None:
        if self.line_rows:
            self.line_rows[0].invoice.setText(text)
            self.line_rows[0].changed.emit()

    def _amount_typed(self, text: str) -> None:
        if self.line_rows:
            self.line_rows[0].amount.setText(text)
            self.line_rows[0].changed.emit()

    def _follow_date(self, *_) -> None:
        if self._deposit_day_kept:
            self.deposit_date.blockSignals(True)
            self.deposit_date.setDate(self.date.date())
            self.deposit_date.blockSignals(False)

    def _deposit_day_changed(self, *_) -> None:
        self._deposit_day_kept = self.deposit_date.date() == self.date.date()
        self._changed()

    def _show_check(self) -> None:
        """How the amounts typed close the e-qaimə chosen: in full, partly, or over."""
        row = self.line_rows[0] if self.folded else None
        number = row.invoice.text().strip().upper() if row is not None else ""
        chosen = next((i for i in self.open_invoices if i.invoice == number), None)
        if chosen is None or self.doc is not None:
            self.check.hide()
            return
        try:
            bank = to_minor(row.amount.text()) if row and row.amount.text().strip() else 0
            vat = to_minor(self.vat_amount.text()) if self.vat_amount.text().strip() else 0
        except ValueError:
            self.check.hide()
            return
        vat = vat if self.deposit_shown else 0
        paid = bank + vat
        parts = (
            tr(
                "банк {bank} + депозит {vat} = {total}",
                bank=format_minor(bank),
                vat=format_minor(vat),
                total=format_minor(paid),
            )
            if vat
            else ""
        )
        if paid == chosen.amount:
            text, tone = tr("✓ e-qaimə оплачивается полностью"), "success"
        elif paid < chosen.amount:
            left = format_minor(chosen.amount - paid)
            text, tone = tr("по e-qaimə останется {left}", left=left), "tertiary"
        else:
            over = format_minor(paid - chosen.amount)
            text, tone = tr("больше остатка по e-qaimə на {over}", over=over), "caution"
        self.check.setText(f"{parts}   ·   {text}" if parts else text)
        self.check.setObjectName(tone)
        self.check.style().unpolish(self.check)  # the new name's color
        self.check.style().polish(self.check)
        self.check.show()

    def _deposit_part(self, data: BankOperationInput) -> BankOperationInput | None:
        """The operation on the ƏDV deposit account, if its amount is typed: the same
        counterparty, line and e-qaimə, its own day."""
        text = self.vat_amount.text().strip()
        if not self.deposit_shown or not text or not data.lines:
            return None
        place = self.deposit.currentData()
        if not isinstance(place, BankPlace):
            return None
        day = edited_date(self.deposit_date).isoformat()
        subconto = self._place_subconto(place)
        return vat_deposit_part(data, place.account_id, subconto, to_minor(text), day)
