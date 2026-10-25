"""The bank field: the GL account and the bank account directory in one list, the
currency it leaves to choose, the balance on the day; a new bank added right here."""

from __future__ import annotations

from collections.abc import Sequence

from modern_gl.application.bank import (
    BankPlace,
    bank_places,
    place_balance,
)
from modern_gl.desktop.bank_operation_page.common import (
    FROM_BANK,
    bank_accounts,
    fits,
    place_label,
    select_data,
)
from modern_gl.desktop.bank_operation_page.form import BankOperationForm
from modern_gl.desktop.conversion_page.common import fit_currency
from modern_gl.desktop.widgets import (
    edited_date,
)
from modern_gl.domain.money import format_minor
from modern_gl.i18n import tr


class BankAccountPart(BankOperationForm):
    def _bank_account_changed(self, *_, chosen: Sequence[int | None] = ()) -> None:
        account = self.bank_info
        kinds = account.sc_kinds if account else (None, None, None)
        chosen = [*chosen, None, None, None][:3]
        for label, box, kind, value in zip(self.sc_captions, self.sc, kinds, chosen, strict=True):
            box.clear()
            shown = kind is not None
            label.setVisible(shown)
            box.setVisible(shown)
            if kind is None:
                continue
            label.setText(self.s.catalog.kinds[kind])
            values = [v for v in self.s.catalog.values(kind) if fits(account, v)]
            for v in values:
                box.addItem(v.name, v.id)
            if value is not None:
                select_data(box, value, self.s.catalog.value(value).name)
            elif len(values) == 1:  # the only one: chosen already
                box.setCurrentIndex(0)
        self._fit_currency()
        self._show_bank()
        self._kind_visibility()
        self._changed()

    def _bank_subconto_changed(self, *_) -> None:
        self._fit_currency()
        self._show_bank()
        self._changed()

    def _fit_currency(self) -> None:
        fit_currency(self.currency, self.s, self.bank_info, self.bank_subconto())
        self.currency.setVisible(self.currency.isEnabled())  # a currency left to choose

    def _fill_banks(self) -> None:
        """Every bank account of the company in one list, «Kapital Bank · 51 · AZN»: the
        ones in use, then a bank on a GL account it was never used with (a new ƏDV
        deposit on 55 with the bank of 51); the ƏDV deposit ones for the deposit part."""
        self.places = bank_places(self.s.conn, self.s.company_id)
        self.places += self._unused_places({p.key for p in self.places})
        self.bank.clear()
        for place in self.places:
            self.bank.addItem(place_label(place), place)
        chosen = self.deposit.currentData()
        self.deposits = [p for p in self.places if p.account_type == "vat_deposit"]
        self.deposit.clear()
        for place in self.deposits:
            self.deposit.addItem(place_label(place), place)
        # or the ƏDV straight from this account to the supplier's deposit (D145)
        self.deposit.addItem(tr("С этого счёта — на депозит поставщика"), FROM_BANK)
        items = [*self.deposits, FROM_BANK]
        self.deposit.setCurrentIndex(next((i for i, p in enumerate(items) if p == chosen), 0))
        self._show_bank()

    def _unused_places(self, listed: set[tuple[int, int | None]]) -> list[BankPlace]:
        catalog = self.s.catalog
        result = []
        for account in bank_accounts(self.s):
            kind = next(
                (k for k in account.sc_kinds if catalog.kind_codes.get(k or 0) == "bank_account"),
                None,
            )
            if kind is None:
                continue
            for v in catalog.values(kind):
                if (account.id, v.id) in listed or not fits(account, v):
                    continue
                currency = catalog.currencies[v.currency_id].code if v.currency_id else ""
                code = account.code or account.name
                result.append(
                    BankPlace(
                        account.id,
                        v.id,
                        v.name,
                        code,
                        v.currency_id,
                        currency,
                        account.account_type,
                    )
                )
        return result

    def _add_bank(self, text: str, listed: bool = False) -> None:
        """A bank not yet in the directory: added under the chosen GL account (or the first
        one with the bank account directory), as an element of that directory."""
        catalog = self.s.catalog
        for account in [self.bank_info, *bank_accounts(self.s)]:
            if account is None:
                continue
            position = next(
                (
                    i
                    for i, kind in enumerate(account.sc_kinds)
                    if catalog.kind_codes.get(kind or 0) == "bank_account"
                ),
                None,
            )
            if position is None:
                continue
            select_data(self.account, account.id, account.label)
            self._bank_account_changed(chosen=self.bank_subconto())
            self._add_bank_value(position, text, listed)
            self._fill_banks()
            if not listed:
                self.bank.setFocus()
                self.focusNextChild()
            return
        self._not_listed(text)

    def _bank_chosen(self, *_) -> None:
        """The one bank field: its GL account and the element of the bank directory."""
        place = self.bank.currentData()
        if not isinstance(place, BankPlace):
            return
        label = self.s.catalog.accounts[place.account_id].label
        select_data(self.account, place.account_id, label)
        self._bank_account_changed(chosen=self._place_subconto(place))

    def _show_bank(self) -> None:
        """The bank field shows the account and bank chosen, and its balance on the day."""
        account_id = self.account.currentData()
        values = {v for v in self.bank_subconto() if v is not None}
        found = next(
            (
                i
                for i, place in enumerate(self.places)
                if place.account_id == account_id
                and (place.value_id is None or place.value_id in values)
            ),
            -1,
        )
        if found < 0 and account_id is not None:  # not among the bank accounts any more
            self.bank.addItem(self.s.catalog.accounts[account_id].label, None)
            found = self.bank.count() - 1
        self.bank.setCurrentIndex(found)
        self._show_balance()

    def _show_balance(self, *_) -> None:
        place = self.bank.currentData()
        if not isinstance(place, BankPlace):
            self.balance.setText("")
            return
        day = edited_date(self.date).isoformat()
        amount = place_balance(self.s.conn, self.s.company_id, place, day)
        self.balance.setText(tr("остаток {amount}", amount=format_minor(amount)))

    def _add_bank_value(self, position: int, text: str, listed: bool = False) -> None:
        """A bank account not yet in the directory (a new bank): added right here."""
        account = self.bank_info
        kind = account.sc_kinds[position] if account else None
        if kind is None or self.read_only:
            return
        currency = self.currency.currentData() if account and account.currency else None
        value = self._new_value(listed, kind, text, currency_id=currency)
        if value is None:
            return
        chosen = list(self.bank_subconto())
        chosen[position] = value
        self._bank_account_changed(chosen=chosen)
        self._focus_after(self.sc[position], listed)
