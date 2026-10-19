"""Companies and their closed period."""

from __future__ import annotations

from datetime import date

from modern_gl.application.common import now
from modern_gl.application.ledger.base import LedgerBase
from modern_gl.application.ledger.inputs import DEFAULT_LAYERS
from modern_gl.domain.currency import DEFAULT_CURRENCIES, currency_name
from modern_gl.domain.dates import iso_date
from modern_gl.i18n import tr
from modern_gl.infrastructure.db import transaction


class CompanyCommands(LedgerBase):
    def create_company(self, name: str, base_currency: str = "AZN") -> int:
        with transaction(self.conn):
            company_id = self.conn.execute(
                "INSERT INTO companies (name, base_currency, created_at) VALUES (?, ?, ?)",
                (name, base_currency, now()),
            ).lastrowid
            self.conn.executemany(
                "INSERT INTO layers (company_id, code, name) VALUES (?, ?, ?)",
                [(company_id, code, tr(title)) for code, title in DEFAULT_LAYERS],
            )
            self.conn.executemany(
                "INSERT INTO currencies (company_id, code, name) VALUES (?, ?, ?)",
                [(company_id, code, currency_name(code)) for code in DEFAULT_CURRENCIES],
            )
            self._audit(
                company_id,
                "company",
                company_id,
                "create",
                {"name": name, "base_currency": base_currency},
            )
        return company_id

    def set_closed_through(self, company_id: int, through: date | str | None) -> None:
        """Close the period up to `through` inclusive; None reopens everything. Audited."""
        value = None if through is None else iso_date(through)
        with transaction(self.conn):
            old = self._company(company_id)["closed_through"]
            self.conn.execute(
                "UPDATE companies SET closed_through = ? WHERE id = ?", (value, company_id)
            )
            self._audit(
                company_id, "company", company_id, "set_closed_through", {"from": old, "to": value}
            )
