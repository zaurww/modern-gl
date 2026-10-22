"""What the entry line offers (D78): the counterparties, the accounts with the company's
other bank accounts for a transfer, the account "as last time", the analytics the account
asks for, the unpaid e-qaimə of the counterparty."""

from __future__ import annotations

from PySide6.QtWidgets import QDialog

from modern_gl.application.bank import (
    IN,
    OUT,
    bank_places,
    last_lines,
    latest_direction,
)
from modern_gl.application.catalog import AccountInfo
from modern_gl.desktop.bank_operation_page.common import (
    SEVERAL,
    counterparty_kind,
    offer_invoices,
    select_data,
)
from modern_gl.desktop.bank_page.entry.fields import ONE, EntryFields
from modern_gl.desktop.invoice_picker import InvoicePicker
from modern_gl.desktop.widgets import edited_date
from modern_gl.domain.money import format_minor, to_minor
from modern_gl.i18n import tr
from modern_gl.reporting.invoices import open_invoices

BANK_TYPES = ("bank", "vat_deposit")
ADVANCE_OF = {"advance_paid": "payable", "advance_received": "receivable"}


class EntryChoices(EntryFields):
    def fill_lists(self) -> None:
        """The counterparties and the accounts; called as the statement opens (the
        directories may have grown meanwhile)."""
        box = self.counterparty_box
        box.clear()
        kind = counterparty_kind(self.s)
        for v in self.s.catalog.values(kind) if kind is not None else []:
            box.addItem(v.label, v.id, v.name)
        self.account.clear()
        for a in self.s.catalog.leaf_accounts:
            if not self._is_bank(a):
                self.account.addItem(a.label, (a.id, None))
        place = self.place
        for other in bank_places(self.s.conn, self.s.company_id):
            if place is None or other.key == place.key or other.currency_id != place.currency_id:
                continue
            label = f"{other.account_code}  {other.name}"
            self.account.addItem(label, other.key)

    def _is_bank(self, account: AccountInfo) -> bool:
        """A bank account is chosen with its bank (PAŞA Bank), never alone."""
        codes = self.s.catalog.kind_codes
        return account.account_type in BANK_TYPES or any(
            k is not None and codes.get(k) == "bank_account" for k in account.sc_kinds
        )

    @property
    def account_info(self) -> AccountInfo | None:
        data = self.account.currentData()
        return self.s.catalog.accounts.get(data[0]) if data else None

    def guessed_direction(self) -> str:
        """Money in for a customer's account, out for the rest."""
        info = self.account_info
        return IN if info is not None and info.account_type == "receivable" else OUT

    # ---- after a choice ------------------------------------------------------------------

    def counterparty_chosen(self, *_) -> None:
        value = self.counterparty_box.currentData()
        if value == self.counterparty:
            return
        self.counterparty = value
        if value is not None and (self.auto_account or self.account.currentData() is None):
            self._as_last_time(value)
        self.account_chosen()

    def _as_last_time(self, value: int) -> None:
        """The account (and analytics) the money of this counterparty went to last time."""
        conn, cid = self.s.conn, self.s.company_id
        direction = latest_direction(conn, cid, value) or OUT
        lines = [x for x in last_lines(conn, cid, direction, value) if x.account_id is not None]
        if not lines:
            return
        # the payment itself, not the advance it left (60.2 → its 60.1)
        settled = [x for x in lines if self._settlement_of(x.account_id) == x.account_id]
        line = (settled or lines)[0]
        account_id = self._settlement_of(line.account_id)
        if self.account.findData((account_id, None)) < 0:
            return
        select_data(self.account, (account_id, None))
        self.auto_account = True
        self.account_chosen(remembered=list(line.subconto))

    def _settlement_of(self, account_id: int | None) -> int | None:
        """An advance account's settlement account (60.2 → 60.1, of the same group if
        there is one); any other account is itself."""
        accounts = self.s.catalog.accounts
        info = accounts.get(account_id) if account_id is not None else None
        settles = ADVANCE_OF.get(info.account_type or "") if info is not None else None
        if info is None or settles is None:
            return account_id
        same = [a for a in self.s.catalog.leaf_accounts if a.account_type == settles]
        sibling = next((a for a in same if a.parent_id == info.parent_id), None)
        return (sibling or (same[0] if same else info)).id

    def account_chosen(self, *_, remembered: list[int | None] | None = None) -> None:
        """The analytics the account asks for, its contract, the e-qaimə it can close."""
        info = self.account_info
        self.analytics_position = self.contract_position = None
        self.analytics.clear()
        if info is not None and self.account.currentData()[1] is None:
            self._find_positions(info)
        if self.analytics_position is not None and info is not None:
            kind = info.sc_kinds[self.analytics_position]
            assert kind is not None
            for v in self.s.catalog.values(kind):
                self.analytics.addItem(v.label, v.id, v.name)
            self.analytics.setPlaceholderText(self.s.catalog.kinds[kind])
            if remembered and remembered[self.analytics_position] is not None:
                select_data(self.analytics, remembered[self.analytics_position])
        self.analytics.setVisible(self.analytics_position is not None)
        self.refresh_invoices()
        self.account_hook()

    def _find_positions(self, info: AccountInfo) -> None:
        """The first position the counterparty does not fill: a cost item, a tax; and a
        contract of the counterparty, taken when it has only one."""
        cat = self.s.catalog
        for i, kind in enumerate(info.sc_kinds):
            if kind is None:
                continue
            code = cat.kind_codes.get(kind)
            if kind in cat.owner_kinds:
                self.contract_position = i
            elif code not in ("counterparty", "bank_account") and self.analytics_position is None:
                self.analytics_position = i

    def contract(self) -> int | None:
        if self.contract_position is None or self.counterparty is None:
            return None
        info = self.account_info
        assert info is not None
        kind = info.sc_kinds[self.contract_position]
        contracts = self.s.catalog.values(kind, owner=self.counterparty) if kind else []
        return contracts[0].id if len(contracts) == 1 else None

    def invoices_apply(self) -> bool:
        info = self.account_info
        return (
            bool(self.counterparty) and info is not None and self.s.catalog.takes_invoice(info.id)
        )

    def refresh_invoices(self) -> None:
        """The unpaid e-qaimə of the counterparty on the day: owed to it, or by it."""
        if self.invoices_apply():
            assert self.counterparty is not None
            self.invoices = open_invoices(
                self.s.conn,
                self.s.company_id,
                self.counterparty,
                payable=self.guessed_direction() == OUT,
                on_date=edited_date(self.date),
            )
        else:
            self.invoices = []
        offer_invoices(self.invoice, self.invoices)
        self.chosen_invoices = []
        self.invoice.setEnabled(self.invoices_apply())

    def invoice_chosen(self, *_) -> None:
        """One e-qaimə: what it still owes goes into the amount, unless one is typed;
        «several»: ticked in a list, the amount spread over them oldest first."""
        target = self.amount_target()
        if self.invoice.currentData() == SEVERAL:
            self._pick_several(target)
            return
        chosen = next((i for i in self.invoices if i.invoice == self.invoice.text()), None)
        self.chosen_invoices = [chosen] if chosen is not None else []
        if chosen is not None and not target.text().strip():
            target.setText(format_minor(chosen.amount))

    def _pick_several(self, target) -> None:
        typed = target.text().strip()
        try:
            total = to_minor(typed.lstrip("+-−")) if typed else None
        except ValueError:
            total = None
        picker = InvoicePicker(self.invoices, total, self)
        if picker.exec() != QDialog.DialogCode.Accepted:
            self.invoice.setText("")
            return
        numbers = {number for number, _ in picker.chosen}
        self.chosen_invoices = [i for i in self.invoices if i.invoice in numbers]
        self.invoice.setText(tr("{n} e-qaimə", n=len(self.chosen_invoices)))
        if total is None:
            target.setText(format_minor(sum(amount for _, amount in picker.chosen)))

    def amount_target(self):
        if self.mode == ONE:
            return self.amount
        return self.money_in if self.guessed_direction() == IN else self.money_out

    def invoices_of_line(self) -> list[tuple[str, int | None]]:
        """(number, what it still owes) of the e-qaimə the line pays; a number typed that
        the list does not know: None, it takes the whole amount."""
        if self.chosen_invoices:
            return [(i.invoice, i.amount) for i in self.chosen_invoices]
        typed = self.invoice.text().strip()
        known = next((i for i in self.invoices if i.invoice == typed), None)
        return [(typed, known.amount if known else None)] if typed else []

    def account_hook(self) -> None:  # the line: the sign of the amount, the purpose
        pass
