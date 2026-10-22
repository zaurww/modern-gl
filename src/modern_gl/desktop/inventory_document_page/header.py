"""The header of a warehouse document: VAT rate, currency and rate, the basis (e-qaimə or
customs declaration) with its portal status, the month of the expense (D65)."""

from __future__ import annotations

from fractions import Fraction

from modern_gl.application.currencies import rate_on
from modern_gl.desktop.inventory_document_page.columns import (
    VAT_DOCUMENTS,
)
from modern_gl.desktop.inventory_document_page.form import InventoryDocumentForm
from modern_gl.desktop.postings import plain_number
from modern_gl.desktop.widgets import (
    edited_date,
)
from modern_gl.domain.currency import format_unit_rate, parse_rate, unit_rate
from modern_gl.domain.dates import earlier_months, month_name
from modern_gl.domain.eqaime import status_group, status_label
from modern_gl.domain.invoice import EQAIME
from modern_gl.i18n import tr
from modern_gl.reporting.eqaime_reconciliation import portal_status


class HeaderPart(InventoryDocumentForm):
    def _vat_rate_changed(self, *_args) -> None:
        self.model.set_vat_rate(self._chosen_vat_rate())
        self.table.configure_columns()

    def _typed_rate(self) -> Fraction | None:
        try:
            return unit_rate(parse_rate(plain_number(self.rate.text())))
        except (TypeError, ValueError):
            return None

    def _rate_of_the_day(self) -> None:
        """The rate in force on the document's date (unless the rate was typed)."""
        currency_id = self._chosen_currency()
        if currency_id is None or self.rate_typed:
            return
        found = rate_on(self.s.conn, self.s.company_id, currency_id, edited_date(self.date))
        self.rate.setText(format_unit_rate(found.per_unit) if found else "")

    def _apply_currency(self) -> None:
        in_currency = self._chosen_currency() is not None
        for widget in (self.rate_caption, self.rate):
            widget.setVisible(in_currency)
        if in_currency:  # an import has no Azerbaijani VAT: it comes with customs
            self._show_vat_rate(None)
            self.model.set_vat_rate(None)
        self.vat_rate.setEnabled(not in_currency and not self.model.read_only)
        self.model.set_currency(self.currency.currentText(), self._typed_rate(), in_currency)
        self.table.configure_columns()

    def _currency_changed(self, *_args) -> None:
        self.rate_typed = False
        self._rate_of_the_day()
        self._apply_currency()

    def _rate_edited(self, *_args) -> None:
        self.rate_typed = True
        self._apply_currency()

    def _date_changed(self, *_args) -> None:
        if self._chosen_currency() is not None and not self.rate_typed:
            self._rate_of_the_day()
            self._apply_currency()

    def _show_currency(self, currency_id: int | None, rate: int | None) -> None:
        receipt = self.doc_type == "receipt"
        self.currency.setCurrentIndex(max(self.currency.findData(currency_id), 0))
        self.rate.setText("" if rate is None else format_unit_rate(unit_rate(rate)))
        self.rate_typed = rate is not None  # a saved rate stays as it was
        for widget in (self.currency_caption, self.currency):
            widget.setVisible(receipt)
        self._apply_currency()

    def _rate_text(self) -> str | None:
        if self._chosen_currency() is None:
            return None
        return plain_number(self.rate.text()) or None

    def _show_reason(self, reason: str | None) -> None:
        """A mədaxil's reason (D91); other documents have none."""
        self.reason.setCurrentIndex(max(self.reason.findData(reason), 0))
        for widget in (self.reason_caption, self.reason):
            widget.setVisible(self.doc_type == "incoming")

    def _reason_changed(self, *_args) -> None:
        self.model.set_incoming_account(self._incoming_account())
        self.table.configure_columns()

    def _show_basis(self, kind: str, number: str) -> None:
        """The e-qaimə / declaration of a receipt, the e-qaimə of a sale; other documents
        have none."""
        self.basis.setCurrentIndex(max(self.basis.findData(kind), 0))
        self.invoice.setText(number)
        self.basis.setVisible(self.doc_type == "receipt")
        self.invoice_caption.setVisible(self.doc_type == "sale")
        self.invoice.setVisible(self.doc_type in VAT_DOCUMENTS)
        self._show_portal_status(kind, number)

    def _show_portal_status(self, kind: str, number: str) -> None:
        """Only what is worth a look: an approved e-qaimə shows nothing."""
        status = None
        if kind == EQAIME and self.doc_type in ("receipt", "sale"):
            status = portal_status(self.s.conn, self.s.company_id, self.doc_type == "sale", number)
        group = status_group(status or "")
        if status is None or group == "turnover":
            self.portal_status.hide()
            return
        self.portal_status.set(status_label(status), "red" if group == "void" else "neutral")
        self.portal_status.setToolTip(tr("Статус на портале при последней загрузке"))
        self.portal_status.show()

    def _invoice(self) -> dict[str, str]:
        """The basis for saving: number and kind (an empty number: none)."""
        number = self.invoice.text().strip()
        if self.doc_type == "sale":
            return {"invoice": number}
        return {"invoice": number, "invoice_kind": self.basis.currentData() if number else ""}

    def _fill_expense_months(self, chosen: str | None) -> None:
        """The months a receipt's services may belong to: the document's own (nothing is
        accrued) or one of the twelve before it, each as its last day."""
        self.expense_month.clear()
        self.expense_month.addItem(tr("месяц документа"), None)
        for last in earlier_months(edited_date(self.date)):
            self.expense_month.addItem(month_name(last[:7]), last)
        if chosen is not None and self.expense_month.findData(chosen) < 0:
            self.expense_month.addItem(month_name(chosen[:7]), chosen)  # saved earlier
        self.expense_month.setCurrentIndex(max(self.expense_month.findData(chosen), 0))
        self._show_expense_month()

    def _expense_months_changed(self, *_args) -> None:
        self._fill_expense_months(self._expense_date())

    def _show_expense_month(self) -> None:
        """Only a receipt with services (or with a month already chosen) asks for it."""
        shown = self.doc_type == "receipt" and (
            self.model.has_expenses() or self._expense_date() is not None
        )
        self.expense_caption.setVisible(shown)
        self.expense_month.setVisible(shown)
