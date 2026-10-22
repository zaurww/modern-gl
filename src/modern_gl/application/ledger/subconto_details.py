"""A directory element with its details saved at once — the element's window (D80: one
scenario, one transaction): name, counterparty of a contract, currency, VÖEN, tags."""

from __future__ import annotations

from dataclasses import dataclass

from modern_gl.application.ledger.subconto import SubcontoCommands
from modern_gl.infrastructure.db import transaction

Tax = tuple[str | None, bool, str | None]  # VÖEN or own tax number, non-resident, country
NO_TAX: Tax = (None, False, None)


@dataclass(frozen=True)
class ValueDetails:
    """What the element's window may set; None — the window does not show it."""

    owner_id: int | None = None
    currency_id: int | None = None
    tax: Tax | None = None
    tags: tuple[int, ...] | None = None


class SubcontoDetailCommands(SubcontoCommands):
    def add_detailed_value(
        self, company_id: int, kind_id: int, name: str, details: ValueDetails
    ) -> int:
        """A new element with what its window set, all or nothing."""
        with transaction(self.conn):
            value_id = self.add_subconto_value(company_id, kind_id, name, owner_id=details.owner_id)
            if details.currency_id is not None:
                self.set_subconto_value_currency(company_id, value_id, details.currency_id)
            if details.tax is not None and details.tax != NO_TAX:
                self.set_subconto_value_tax(company_id, value_id, *details.tax)
            if details.tags:
                self.set_subconto_value_tags(company_id, value_id, details.tags)
        return value_id

    def save_detailed_value(
        self,
        company_id: int,
        value_id: int,
        name: str,
        details: ValueDetails,
        owner_shown: bool,
        currency_shown: bool,
    ) -> None:
        """The element's window saved: what changed is written, all or nothing."""
        value = self._subconto_value(company_id, value_id)
        with transaction(self.conn):
            if name.strip() != value["name"]:
                self.update_subconto_value(company_id, value_id, name, value["code"])
            if owner_shown and details.owner_id != value["owner_id"]:
                self.set_subconto_value_owner(company_id, value_id, details.owner_id)
            if currency_shown and details.currency_id != value["currency_id"]:
                self.set_subconto_value_currency(company_id, value_id, details.currency_id)
            old_tax = (value["tax_id"], bool(value["nonresident"]), value["country"])
            if details.tax is not None and details.tax != old_tax:
                self.set_subconto_value_tax(company_id, value_id, *details.tax)
            if details.tags is not None:
                self.set_subconto_value_tags(company_id, value_id, details.tags)
