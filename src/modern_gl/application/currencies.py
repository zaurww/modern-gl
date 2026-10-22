"""Read side of currencies: the company's currencies, rate history, the rate on a date."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from fractions import Fraction

from modern_gl.domain.currency import unit_rate
from modern_gl.domain.dates import iso_date
from modern_gl.infrastructure.db import Connection, Row


@dataclass(frozen=True)
class CurrencyInfo:
    id: int
    code: str
    name: str
    active: bool = True

    @property
    def label(self) -> str:
        return f"{self.code}  {self.name}"


@dataclass(frozen=True)
class Rate:
    currency_id: int
    rate_date: str
    rate: int  # millionths of a manat for `nominal` units
    nominal: int
    source: str

    @property
    def per_unit(self) -> Fraction:
        return unit_rate(self.rate, self.nominal)


def list_currencies(conn: Connection, company_id: int) -> list[CurrencyInfo]:
    return [
        CurrencyInfo(r["id"], r["code"], r["name"], bool(r["active"]))
        for r in conn.execute(
            "SELECT * FROM currencies WHERE company_id = ? ORDER BY code", (company_id,)
        )
    ]


def list_rates(conn: Connection, company_id: int, currency_id: int) -> list[Rate]:
    """Rate history of a currency, newest first."""
    return [
        _rate(r)
        for r in conn.execute(
            "SELECT * FROM currency_rates WHERE company_id = ? AND currency_id = ? "
            "ORDER BY rate_date DESC",
            (company_id, currency_id),
        )
    ]


def rate_on(conn: Connection, company_id: int, currency_id: int, day: date | str) -> Rate | None:
    """The rate in force on a day: the latest one set on or before it."""
    row = conn.execute(
        "SELECT * FROM currency_rates WHERE company_id = ? AND currency_id = ? "
        "AND rate_date <= ? ORDER BY rate_date DESC LIMIT 1",
        (company_id, currency_id, iso_date(day)),
    ).fetchone()
    return _rate(row) if row else None


def latest_rates(conn: Connection, company_id: int) -> dict[int, Rate]:
    """The most recent rate of every currency that has one."""
    return {
        r["currency_id"]: _rate(r)
        for r in conn.execute(
            """
            SELECT r.* FROM currency_rates r
            WHERE r.company_id = ? AND r.rate_date = (
                SELECT MAX(rate_date) FROM currency_rates x WHERE x.currency_id = r.currency_id)
            """,
            (company_id,),
        )
    }


def _rate(r: Row) -> Rate:
    return Rate(r["currency_id"], r["rate_date"], r["rate"], r["nominal"], r["source"])
