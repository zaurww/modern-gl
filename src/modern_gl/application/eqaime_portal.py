"""Reading the portal's e-qaimə lists for the reconciliation (D53): every status, no lines —
one request per status and page, fast enough for a month."""

from __future__ import annotations

import calendar
import sqlite3
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date

from modern_gl.domain.eqaime import ALL, PortalInvoice, portal_invoice
from modern_gl.i18n import tr
from modern_gl.infrastructure.etaxes import EtaxesClient

RECHECK_MONTHS = 12  # reconciled months older than this are not read again


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


@dataclass(frozen=True)
class Recheck:
    outgoing: bool
    date_from: date
    date_to: date


def rechecks(conn: sqlite3.Connection, company_id: int, today: date) -> list[Recheck]:
    """What to read again from the portal to see changes in reconciled months: per
    direction, from the first to the last reconciled month of the last year."""
    oldest = f"{today.year - 1:04d}-{today.month:02d}"
    return [
        Recheck(bool(row["outgoing"]), month_bounds(row["first"])[0], month_bounds(row["last"])[1])
        for row in conn.execute(
            "SELECT outgoing, MIN(month) AS first, MAX(month) AS last FROM eqaime_reconciled "
            "WHERE company_id = ? AND month > ? GROUP BY outgoing ORDER BY outgoing",
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
