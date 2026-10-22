"""The account's window saved as one scenario, in one transaction (debt 10): a new account
or the changes to one, its class, type and optional subconto."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from modern_gl.application.ledger.chart import ChartCommands
from modern_gl.application.ledger.subconto import SubcontoCommands
from modern_gl.infrastructure.db import transaction


@dataclass(frozen=True)
class AccountForm:
    code: str
    name: str
    parent_id: int | None = None  # a new account only: under which
    is_group: bool = False
    subconto: Sequence[int] = ()
    account_class: str | None = None
    account_type: str | None = None
    contra: bool = False
    two_sided: bool = False
    currency: int | None = None
    optional: frozenset[int] = field(default_factory=frozenset)  # subconto positions


class AccountFormCommands(ChartCommands, SubcontoCommands):
    def save_account_form(self, company_id: int, account_id: int | None, form: AccountForm) -> int:
        """Add the account (`account_id` None) or change it; returns its id. The first
        subaccount turns a plain parent into a group."""
        with transaction(self.conn):
            if account_id is None:
                account_id = self._add_from_form(company_id, form)
            else:
                self._update_from_form(company_id, account_id, form)
            self.set_optional_subconto(company_id, account_id, form.optional)
        return account_id

    def _add_from_form(self, company_id: int, form: AccountForm) -> int:
        if form.parent_id is not None and not self._account(company_id, form.parent_id)["is_group"]:
            self.update_account(company_id, form.parent_id, is_group=True)
        return self.add_account(
            company_id,
            form.code,
            form.name,
            two_sided=form.two_sided,
            parent=form.parent_id,
            is_group=form.is_group,
            subconto=form.subconto,
            account_class=form.account_class,
            account_type=form.account_type,
            contra=form.contra,
            currency=form.currency,
        )

    def _update_from_form(self, company_id: int, account_id: int, form: AccountForm) -> None:
        before = self._account(company_id, account_id)
        self.update_account(
            company_id,
            account_id,
            new_code=form.code,
            name=form.name,
            two_sided=form.two_sided,
            is_group=form.is_group,
            subconto=form.subconto,
            currency=form.currency,
        )
        if (form.account_class, form.contra) != (before["account_class"], bool(before["contra"])):
            self.set_account_class(company_id, account_id, form.account_class, form.contra)
        if form.account_type != before["account_type"]:
            self.set_account_type(company_id, account_id, form.account_type)
