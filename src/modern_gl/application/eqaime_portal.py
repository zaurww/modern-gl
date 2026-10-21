"""Reading the portal's e-qaimə lists for the reconciliation (D53): every status, no lines —
one request per status and page, fast enough for a month."""

from __future__ import annotations

import calendar
import sqlite3
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta

from modern_gl.domain.eqaime import ALL, PortalInvoice, portal_invoice
from modern_gl.i18n import tr
from modern_gl.infrastructure.etaxes import EtaxesClient


def fetch_list(
    client: EtaxesClient,
    outgoing: bool,
    date_from: date,
    date_to: date,
    progress: Callable[[str], None] = lambda _text: None,
    statuses: Sequence[str] = ALL,
) -> list[PortalInvoice]:
    """The e-qaimə of a period in every status, received (purchases) or sent (sales)."""
    result = []
    for n, status in enumerate(statuses, 1):
        progress(tr("Портал: статус {n} из {total}", n=n, total=len(statuses)))
        for row in client.invoices(outgoing, date_from, date_to, (status,)):
            invoice = portal_invoice({"status": status, **row}, outgoing)
            if invoice is not None:
                result.append(invoice)
    return result


def month_bounds(month: str) -> tuple[date, date]:
    """'2026-09' -> 1 and 30 September 2026."""
    year, number = int(month[:4]), int(month[5:7])
    return date(year, number, 1), date(year, number, calendar.monthrange(year, number)[1])


def full_month(date_from: date, date_to: date) -> str | None:
    """'YYYY-MM' when the period is exactly one calendar month, else None."""
    month = f"{date_from:%Y-%m}"
    return month if (date_from, date_to) == month_bounds(month) else None


DAY, WEEK, MONTH = "day", "week", "month"


def quick_period(span: str, today: date) -> tuple[date, date]:
    """What a morning check looks at. «Вчера»: yesterday, on a Monday Friday to Sunday;
    «Неделя»: from Monday of yesterday's week to yesterday (on a Monday: the last week);
    «Месяц»: yesterday's month, whole (on the 1st: the month just ended)."""
    yesterday = today - timedelta(days=1)
    if span == DAY:
        return (today - timedelta(days=3) if today.weekday() == 0 else yesterday), yesterday
    if span == WEEK:
        return yesterday - timedelta(days=yesterday.weekday()), yesterday
    return month_bounds(f"{yesterday:%Y-%m}")


def usual_span(conn: sqlite3.Connection, company_id: int, outgoing: bool) -> str:
    """How this company is usually reconciled: like its last mark (a month if none)."""
    row = conn.execute(
        "SELECT date_from, date_to FROM eqaime_reconciled WHERE company_id = ? AND outgoing = ? "
        "ORDER BY reconciled_at DESC LIMIT 1",
        (company_id, int(outgoing)),
    ).fetchone()
    if row is None:
        return MONTH
    days = (date.fromisoformat(row["date_to"]) - date.fromisoformat(row["date_from"])).days + 1
    if full_month(date.fromisoformat(row["date_from"]), date.fromisoformat(row["date_to"])):
        return MONTH
    return DAY if days <= 3 else WEEK if days <= 7 else MONTH


@dataclass(frozen=True)
class Recheck:
    outgoing: bool
    date_from: date
    date_to: date


def rechecks(conn: sqlite3.Connection, company_id: int, today: date) -> list[Recheck]:
    """What to read again from the portal to see changes in reconciled periods: per
    direction, from the first to the last reconciled day of the last year."""
    oldest = (today - timedelta(days=365)).isoformat()
    return [
        Recheck(
            bool(row["outgoing"]),
            date.fromisoformat(max(row["first"], oldest)),
            date.fromisoformat(row["last"]),
        )
        for row in conn.execute(
            "SELECT outgoing, MIN(date_from) AS first, MAX(date_to) AS last "
            "FROM eqaime_reconciled WHERE company_id = ? AND date_to >= ? "
            "GROUP BY outgoing ORDER BY outgoing",
            (company_id, oldest),
        )
    ]


def read_again(
    client: EtaxesClient,
    checks: Sequence[Recheck],
    progress: Callable[[str], None] = lambda _text: None,
) -> list[PortalInvoice]:
    """The lists of the reconciled months, to be remembered: a change shows up."""
    result = []
    for check in checks:
        result += fetch_list(client, check.outgoing, check.date_from, check.date_to, progress)
    return result
