"""The kind of operation and its counterparty: who, the VÖEN, the unpaid e-qaimə."""

from __future__ import annotations

from modern_gl.application.bank import (
    CUSTOMER,
    OTHER,
    OUT,
    SUPPLIER,
    VAT_DEPOSIT_KINDS,
    default_memo,
)
from modern_gl.desktop.bank_operation_page.common import (
    WITH_COUNTERPARTY,
    counterparty_kind,
    offer_invoices,
    select_data,
)
from modern_gl.desktop.bank_operation_page.form import BankOperationForm
from modern_gl.desktop.widgets import (
    edited_date,
)
from modern_gl.reporting.invoices import open_invoices


class CounterpartyPart(BankOperationForm):
    def _kind_visibility(self) -> None:
        """A counterparty for payments to and from partners; the ƏDV deposit account
        offers only what it may pay (D41)."""
        kind = self.kind.currentData()
        shown = kind in WITH_COUNTERPARTY
        for w in (self.counterparty_caption, self.counterparty_edit, self.tax_id):
            w.setVisible(shown)
        deposit = self.bank_info is not None and self.bank_info.account_type == "vat_deposit"
        for i in range(self.kind.count()):
            allowed = not deposit or self.kind.itemData(i) in VAT_DEPOSIT_KINDS
            self.kind.setItemHidden(i, not allowed)
        self.memo.setPlaceholderText(self._default_memo())

    def _kind_changed(self, *_) -> None:
        kind = self.kind.currentData()
        if kind not in WITH_COUNTERPARTY:
            self._set_counterparty(None)
        self._kind_visibility()
        if not self._lines_edited:
            self._default_lines()
        self._changed()

    def _direction_changed(self, *_) -> None:
        if not self._lines_edited:
            if self.kind.currentData() in (SUPPLIER, CUSTOMER):  # who usually pays which way
                select_data(self.kind, SUPPLIER if self.direction_value == OUT else CUSTOMER)
            self._suggest()
        self._refresh_invoices()
        self._kind_visibility()
        self._changed()
        self.title_changed.emit()

    def _fill_counterparties(self) -> None:
        """Found by name or VÖEN; the field shows the name, the VÖEN is under it."""
        box = self.counterparty_edit
        box.clear()
        kind = counterparty_kind(self.s)
        for v in self.s.catalog.values(kind) if kind is not None else []:
            box.addItem(v.label, v.id, v.name)

    def _add_counterparty(self, text: str, listed: bool = False) -> None:
        """A counterparty not yet in the directory: added right here (D49)."""
        kind = counterparty_kind(self.s)
        if kind is None or self.read_only:
            return
        value = self._new_value(listed, kind, text)
        if value is None:
            return
        self._fill_counterparties()
        self._choose_counterparty(value)
        self._focus_after(self.counterparty_edit, listed)

    def _choose_counterparty(self, value: int | None) -> None:
        if value == self.counterparty:
            self._show_counterparty()
            return
        self._set_counterparty(value)
        if value is not None and not self._lines_edited:
            self._suggest()
        self._kind_visibility()
        self._changed()

    def _set_counterparty(self, value: int | None) -> None:
        self.counterparty = value
        for row in self.line_rows:
            row.set_counterparty(value)
        self._show_counterparty()
        self._refresh_invoices()

    def _refresh_invoices(self, *_) -> None:
        """The unpaid e-qaimə of the counterparty on the day: owed to it when paying out,
        owed by it when money comes in."""
        if self.counterparty is None:
            self.open_invoices = []
        else:
            self.open_invoices = open_invoices(
                self.s.conn,
                self.s.company_id,
                self.counterparty,
                payable=self.direction_value == OUT,
                on_date=edited_date(self.date),
            )
        offer_invoices(self.invoice, self.open_invoices)
        for row in self.line_rows:
            row.set_invoices(self.open_invoices)

    def _show_counterparty(self) -> None:
        value = self.counterparty
        info = self.s.catalog.value(value) if value is not None else None
        select_data(self.counterparty_edit, value, info.name if info else "")
        self.tax_id.setText(f"VÖEN {info.tax_id}" if info and info.tax_id else "")

    def _default_memo(self) -> str:
        name = self.s.catalog.value(self.counterparty).name if self.counterparty else ""
        kind = self.kind.currentData() or OTHER
        return default_memo(self.direction_value, kind, name)
