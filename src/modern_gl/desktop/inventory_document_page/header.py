"""The header of a warehouse document: VAT rate, currency and rate, the basis (e-qaimə or
customs declaration) with its portal status."""

from __future__ import annotations

from fractions import Fraction

from modern_gl.application.currencies import rate_on
from modern_gl.application.table_text import plain_number
from modern_gl.desktop.inventory_document_page.columns import (
    VAT_DOCUMENTS,
)
from modern_gl.desktop.inventory_document_page.form import (
    AWAITING,
    OTHER,
    InventoryDocumentForm,
)
from modern_gl.desktop.widgets import (
    edited_date,
)
from modern_gl.domain.currency import format_unit_rate, parse_rate, unit_rate
from modern_gl.domain.eqaime import status_group, status_label
from modern_gl.domain.invoice import EQAIME
from modern_gl.i18n import tr
from modern_gl.reporting.eqaime_reconciliation import portal_status

# the documents with an e-qaimə, and whether the company sends it
OUTGOING = {"receipt": False, "sale": True, "purchase_return": True, "sale_return": False}
CHOSEN_BASIS = {"receipt", "sale"}  # the documents whose basis is chosen in a box


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
        self.model.set_doc_date(edited_date(self.date))  # the months an expense may be of
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

    def _show_basis(self, kind: str, number: str, awaits: bool = False, note: str = "") -> None:
        """The basis of a purchase (e-qaimə, declaration, «Ждёт e-qaimə», «Digər») or a sale
        (e-qaimə, «Digər»); a return's is its e-qaimə; other documents have none."""
        self._basis_items()
        chosen = OTHER if note else AWAITING if awaits else kind
        self.basis.setCurrentIndex(max(self.basis.findData(chosen), 0))
        self.invoice.setText(note or number)
        self.basis.setVisible(self.doc_type in CHOSEN_BASIS)
        self.invoice_caption.setVisible(self.doc_type in VAT_DOCUMENTS - CHOSEN_BASIS)
        self.invoice.setVisible(self.doc_type in VAT_DOCUMENTS)
        self._show_basis_field()
        self._show_portal_status(OTHER if note else kind, number)

    def _awaits(self) -> bool:
        return self.doc_type == "receipt" and self.basis.currentData() == AWAITING

    def _other_basis(self) -> bool:
        return self.doc_type in CHOSEN_BASIS and self.basis.currentData() == OTHER

    def _show_basis_field(self) -> None:
        """Waiting for the e-qaimə: no number to type (Tab passes the field by); «Digər»:
        the document in words."""
        awaits = self._awaits()
        if awaits:
            self.invoice.clear()
        self.invoice.setEnabled(not awaits)
        hint = tr("акт №5") if self._other_basis() else tr("номер")
        self.invoice.setPlaceholderText(tr("придёт позже") if awaits else hint)

    def _basis_changed(self, *_args) -> None:
        if self._other_basis() and self.doc_type == "receipt":  # no ƏDV without an e-qaimə
            self._show_vat_rate(None)
            self._vat_rate_changed()
        self._show_basis_field()
        self._changed()

    def _show_portal_status(self, kind: str, number: str) -> None:
        """Only what is worth a look: an approved e-qaimə shows nothing."""
        status = None
        if kind == EQAIME and self.doc_type in OUTGOING:
            sent = OUTGOING[self.doc_type]  # a return to the supplier is sent by the company
            status = portal_status(self.s.conn, self.s.company_id, sent, number)
        group = status_group(status or "")
        if status is None or group == "turnover":
            self.portal_status.hide()
            return
        self.portal_status.set(status_label(status), "red" if group == "void" else "neutral")
        self.portal_status.setToolTip(tr("Статус на портале при последней загрузке"))
        self.portal_status.show()

    def _invoice(self) -> dict[str, str]:
        """The basis for saving: number and kind (an empty number: none), or «Digər»."""
        number = self.invoice.text().strip()
        if self.doc_type not in CHOSEN_BASIS:  # a return's: always an e-qaimə
            return {"invoice": number}
        if self._other_basis():
            return {"invoice": "", "basis_note": number}
        if self.doc_type == "sale":
            return {"invoice": number, "basis_note": ""}
        if self._awaits():
            return {"invoice": "", "invoice_kind": "", "basis_note": ""}
        kind = self.basis.currentData() if number else ""
        return {"invoice": number, "invoice_kind": kind, "basis_note": ""}
