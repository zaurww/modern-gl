"""What the entry line offers (D78): the counterparties, the accounts with the company's
other bank accounts for a transfer, the account "as last time", the analytics the account
asks for, the unpaid e-qaimə of the counterparty."""

from __future__ import annotations

from modern_gl.application.bank import (
    IN,
    OUT,
    bank_places,
    last_lines,
    latest_direction,
)
from modern_gl.application.catalog import AccountInfo
from modern_gl.desktop.bank_operation_page.common import (
    counterparty_kind,
    offer_invoices,
    select_data,
)
from modern_gl.desktop.bank_page.entry.fields import ONE, EntryFields
from modern_gl.desktop.widgets import edited_date
from modern_gl.domain.money import format_minor
from modern_gl.reporting.invoices import open_invoices

BANK_TYPES = ("bank", "vat_deposit")


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
        lines = last_lines(conn, cid, direction, value)
        if not lines or lines[0].account_id is None:
            return
        line = lines[0]
        if self.account.findData((line.account_id, None)) < 0:
            return
        select_data(self.account, (line.account_id, None))
        self.auto_account = True
        self.account_chosen(remembered=list(line.subconto))

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
        self.invoice.setEnabled(self.invoices_apply())

    def invoice_chosen(self, *_) -> None:
        """The amount left to pay goes into the amount, unless one is typed."""
        chosen = next((i for i in self.invoices if i.invoice == self.invoice.text()), None)
        if self.mode == ONE:
            target = self.amount
        else:
            target = self.money_in if self.guessed_direction() == IN else self.money_out
        if chosen is not None and not target.text().strip():
            target.setText(format_minor(chosen.amount))

    def account_hook(self) -> None:  # the line: the sign of the amount, the purpose
        pass
