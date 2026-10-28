"""Read side of currencies: the company's currencies, rate history, the rate on a date."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from fractions import Fraction

from modern_gl.domain.currency import unit_rate
from modern_gl.domain.dates import iso_date, ru_date
from modern_gl.i18n import tr
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


def no_rate_text(code: str, day: date | str) -> str:
    """The same words wherever a rate is missing: «нет курса USD на 05.03.2026»."""
    return tr("нет курса {code} на {date}", code=code, date=ru_date(iso_date(day)))


def missing_rates_text(
    conn: Connection, company_id: int, currency_ids: Iterable[int], day: date | str
) -> str:
    """«На 05.03.2026 курс не загружен: нет курса RUB, курс USD от 01.03.2026» — the
    currencies (each once, by code) without a rate set for the day itself; "" if none."""
    day = iso_date(day)
    stale: dict[str, str] = {}
    for currency_id in set(currency_ids):
        rate = rate_on(conn, company_id, currency_id, day)
        if rate is None or rate.rate_date < day:
            code = conn.execute(
                "SELECT code FROM currencies WHERE company_id = ? AND id = ?",
                (company_id, currency_id),
            ).fetchone()["code"]
            stale[code] = (
                tr("курс {code} от {old}", code=code, old=ru_date(rate.rate_date))
                if rate
                else tr("нет курса {code}", code=code)
            )
    if not stale:
        return ""
    what = ", ".join(stale[code] for code in sorted(stale))
    return tr("На {date} курс не загружен: {what}", date=ru_date(day), what=what)


def days_without_rate(
    conn: Connection, company_id: int, needs: Iterable[tuple[str, str]]
) -> dict[str, list[str]]:
    """Of the (currency code, ISO day) pairs some lines need — a bank statement in a
    currency — the days a currency of the company has no rate set for: code -> the days,
    earliest first. A currency the company has not (the manat too) is left out."""
    wanted: dict[str, set[str]] = {}
    for code, day in needs:  # the manat is no currency of the company: left out below
        wanted.setdefault(code, set()).add(day)
    if not wanted:
        return {}
    marks = ", ".join("?" * len(wanted))
    have: dict[str, set[str]] = {
        r["code"]: set()
        for r in conn.execute(
            f"SELECT code FROM currencies WHERE company_id = ? AND code IN ({marks})",
            (company_id, *sorted(wanted)),
        )
    }
    first = min(min(days) for days in wanted.values())
    for r in conn.execute(
        "SELECT c.code, r.rate_date FROM currency_rates r "
        "JOIN currencies c ON c.company_id = r.company_id AND c.id = r.currency_id "
        f"WHERE r.company_id = ? AND r.rate_date >= ? AND c.code IN ({marks})",
        (company_id, first, *sorted(wanted)),
    ):
        have[r["code"]].add(r["rate_date"])
    missing = {code: sorted(wanted[code] - days) for code, days in have.items()}
    return {code: days for code, days in sorted(missing.items()) if days}


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
