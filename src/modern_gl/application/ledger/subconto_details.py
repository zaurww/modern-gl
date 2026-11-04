"""A directory element with its details saved at once — the element's window (D80: one
scenario, one transaction): name, counterparty of a contract, currency, VÖEN, tags; and
elements named by the lines of a document, all at once (D172)."""

from __future__ import annotations

from dataclasses import dataclass

from modern_gl.application.ledger.subconto import SubcontoCommands
from modern_gl.application.ledger.tags import TagCommands
from modern_gl.i18n import fold
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


class SubcontoDetailCommands(SubcontoCommands, TagCommands):
    """Use cases of the element's window: the element and its details in one transaction."""

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

    def add_named_values(self, company_id: int, kind_id: int, names: list[str]) -> list[int]:
        """An element for each name, in order, all or nothing: a name the directory has
        (or that comes twice) is the same element, not a new one — the fixed assets of a
        purchase named by its lines."""
        known = {
            fold(r["name"]): r["id"]
            for r in self.conn.execute(
                "SELECT id, name FROM subconto_values "
                "WHERE company_id = ? AND kind_id = ? AND is_group = 0 ORDER BY id",
                (company_id, kind_id),
            )
        }
        result: list[int] = []
        with transaction(self.conn):
            for name in names:
                key = fold(name.strip())
                if key not in known:
                    known[key] = self.add_subconto_value(company_id, kind_id, name.strip())
                result.append(known[key])
        return result
