"""Currencies and exchange rates."""

from __future__ import annotations

from datetime import date

from modern_gl.application.common import insert
from modern_gl.application.ledger.base import LedgerBase
from modern_gl.domain.currency import check_code, currency_name
from modern_gl.domain.dates import iso_date
from modern_gl.domain.errors import NotFoundError, ValidationError
from modern_gl.i18n import tr
from modern_gl.infrastructure.db import IntegrityError, transaction


class CurrencyCommands(LedgerBase):
    """Use cases of currencies and their rates (millionths of a manat per nominal)."""

    def add_currency(self, company_id: int, code: str, name: str | None = None) -> int:
        """Add a currency (USD, EUR…). The base currency (manat) is not one of them."""
        try:
            code = check_code(code)
        except ValueError as e:
            raise ValidationError(str(e)) from e
        if code == self._company(company_id)["base_currency"]:
            raise ValidationError(tr("{code} — основная валюта учёта", code=code))
        name = (name or "").strip() or currency_name(code)
        with transaction(self.conn):
            try:
                currency_id = insert(
                    self.conn,
                    "INSERT INTO currencies (company_id, code, name) VALUES (?, ?, ?)",
                    (company_id, code, name),
                )
            except IntegrityError as e:
                raise ValidationError(tr("валюта {code} уже есть", code=code)) from e
            self._audit(company_id, "currency", currency_id, "create", {"code": code})
        return currency_id

    def currency_id(self, company_id: int, code: str) -> int:
        """The id of a currency by its code (USD, EUR…); NotFoundError if it is not added."""
        return self._currency(company_id, code)["id"]

    def set_currency_active(self, company_id: int, currency: int | str, active: bool) -> None:
        """Show or hide a currency in lists; its rates and postings stay. Audited."""
        with transaction(self.conn):
            cur = self._currency(company_id, currency)
            self.conn.execute(
                "UPDATE currencies SET active = ? WHERE id = ?", (int(active), cur["id"])
            )
            self._audit(company_id, "currency", cur["id"], "show" if active else "hide", {})

    def set_rate(
        self,
        company_id: int,
        currency: int | str,
        day: date | str,
        rate: int,
        nominal: int = 1,
        source: str = "manual",
    ) -> None:
        """Set (or replace) the rate of a currency on a day: `rate` millionths of a manat
        for `nominal` units (see domain.currency.parse_rate). Audited."""
        if rate <= 0 or nominal <= 0:
            raise ValidationError(tr("курс должен быть больше нуля: {value}", value=rate))
        with transaction(self.conn):
            cur = self._currency(company_id, currency)
            day = iso_date(day)
            old = self.conn.execute(
                "SELECT rate, nominal FROM currency_rates WHERE currency_id = ? AND rate_date = ?",
                (cur["id"], day),
            ).fetchone()
            self.conn.execute(
                "INSERT INTO currency_rates (company_id, currency_id, rate_date, rate, nominal, "
                "source) VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT (currency_id, rate_date) "
                "DO UPDATE SET rate = excluded.rate, nominal = excluded.nominal, "
                "source = excluded.source",
                (company_id, cur["id"], day, rate, nominal, source),
            )
            self._audit(
                company_id,
                "currency",
                cur["id"],
                "set_rate",
                {
                    "date": day,
                    "rate": rate,
                    "nominal": nominal,
                    "source": source,
                    "before": dict(old) if old else None,
                },
            )

    def delete_rate(self, company_id: int, currency: int | str, day: date | str) -> None:
        """Remove the currency's rate of one day (the previous rate then applies). Audited."""
        with transaction(self.conn):
            cur = self._currency(company_id, currency)
            day = iso_date(day)
            old = self.conn.execute(
                "DELETE FROM currency_rates WHERE currency_id = ? AND rate_date = ? "
                "RETURNING rate, nominal",
                (cur["id"], day),
            ).fetchone()
            if old is None:
                raise NotFoundError(tr("курса {code} на {date} нет", code=cur["code"], date=day))
            self._audit(
                company_id, "currency", cur["id"], "delete_rate", {"date": day, **dict(old)}
            )

    def import_rates(
        self,
        company_id: int,
        day: date | str,
        rates: dict[str, tuple[int, int]],
        source: str = "cbar",
    ) -> int:
        """Rates {code: (rate, nominal)} of a day for the company's active currencies
        (others are ignored). Returns how many were set."""
        with transaction(self.conn):
            currencies = self.conn.execute(
                "SELECT code FROM currencies WHERE company_id = ? AND active = 1", (company_id,)
            ).fetchall()
            count = 0
            for (code,) in currencies:
                if code in rates:
                    rate, nominal = rates[code]
                    self.set_rate(company_id, code, day, rate, nominal, source)
                    count += 1
            return count
