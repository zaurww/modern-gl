"""The kind of operation and its counterparty: who, the VÖEN, the unpaid e-qaimə; a
line of a bank's file whose sender the directory lacks — whom the bank names."""

from __future__ import annotations

from modern_gl.application.bank import (
    CUSTOMER,
    OTHER,
    OUT,
    SUPPLIER,
    VAT_DEPOSIT_KINDS,
    default_memo,
)
from modern_gl.application.bank.parties import statement_party
from modern_gl.application.counterparties import short_name
from modern_gl.application.invoices import open_invoices
from modern_gl.desktop.bank_operation_page.common import (
    WITH_COUNTERPARTY,
    counterparty_kind,
    offer_invoices,
    select_data,
)
from modern_gl.desktop.bank_operation_page.form import BankOperationForm
from modern_gl.desktop.directories_page import new_value
from modern_gl.desktop.widgets import (
    edited_date,
)
from modern_gl.domain.errors import LedgerError
from modern_gl.i18n import tr


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
        self._show_party_note()

    def _show_party_note(self) -> None:
        """A draft from a bank's file without a counterparty: whom the bank names — and
        whether the directory has it by now."""
        d = self.doc
        waits = (
            d is not None
            and d.status == "draft"
            and self.counterparty is None
            and bool(d.party_tin or d.party_name)
            and not self.counterparty_edit.isHidden()
        )
        self.party_note.setVisible(waits)
        if d is None or not waits:
            return
        who = (
            tr("{name}, VÖEN {tin}", name=d.party_name, tin=d.party_tin)
            if d.party_tin
            else d.party_name
        )
        found = statement_party(self.s.conn, self.s.company_id, d.party_tin, d.party_name)
        info = self.s.catalog.value(found) if found is not None else None
        self._party_found = found if info is not None else None
        if info is None:
            self.party_text.setText(tr("В выписке: {who} — в справочнике нет", who=who))
            self.btn_party.setText(tr("Добавить в справочник…"))
        else:
            self.party_text.setText(
                tr("В выписке: {who} — в справочнике это «{name}»", who=who, name=info.name)
            )
            self.btn_party.setText(tr("Подставить"))
        self.btn_party.setVisible(not self.read_only)

    def _take_party(self) -> None:
        """The sender the bank names becomes the counterparty: the one found, else a new
        one — in the directory's window, the bank's name and VÖEN to check. Its other
        waiting lines get it too, spread over its unpaid e-qaimə as the import does."""
        d = self.doc
        if d is None or self.read_only:
            return
        value = self._party_found
        if value is None:
            kind = counterparty_kind(self.s)
            if kind is None:
                return
            value = new_value(self.s, self, kind, short_name(d.party_name), tax_id=d.party_tin)
            if value is None:
                return
        self._fill_counterparties()
        if not self.dirty:  # nothing typed yet: as the import would have made it
            try:
                self.s.ledger.bank.adopt_parties(self.s.company_id)
            except LedgerError as e:
                self.show_error(str(e))
                return
            self.load(d.id)
        if self.counterparty is None:  # typed over, or named another way: this line alone
            self._choose_counterparty(value)

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
