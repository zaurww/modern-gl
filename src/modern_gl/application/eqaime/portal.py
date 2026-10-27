"""Reading the portal's e-qaimə lists for the reconciliation (D53): every status, no lines —
one request per status and page, fast enough for a month."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta

from modern_gl.application.common import local_day
from modern_gl.domain.eqaime import ALL, IMPORTED, PortalInvoice, portal_invoice
from modern_gl.domain.periods import MONTH, span_of
from modern_gl.i18n import tr
from modern_gl.infrastructure.db import Connection
from modern_gl.infrastructure.etaxes import EtaxesClient, PortalError


def fetch_list(
    client: EtaxesClient,
    outgoing: bool,
    date_from: date,
    date_to: date,
    progress: Callable[[str], None] = lambda _text: None,
    statuses: Sequence[str] = ALL,
    skipped: list[str] | None = None,
) -> list[PortalInvoice]:
    """The e-qaimə of a period in every status, received (purchases) or sent (sales).
    A status the portal refuses to filter by (400) is left out and named in `skipped`:
    one unknown status must not stop the whole list; the imported ones must not fail."""
    result = []
    for n, status in enumerate(statuses, 1):
        progress(tr("Портал: статус {n} из {total}", n=n, total=len(statuses)))
        try:
            rows = list(client.invoices(outgoing, date_from, date_to, (status,)))
        except PortalError as exc:
            if exc.code != 400 or status in IMPORTED:
                raise
            if skipped is not None:
                skipped.append(status)
            continue
        for row in rows:
            invoice = portal_invoice({"status": status, **row}, outgoing)
            if invoice is not None:
                result.append(invoice)
    return result


def usual_span(conn: Connection, company_id: int, outgoing: bool) -> str:
    """How this company is usually reconciled: like its last mark, judged on the day it
    was made (this month if none, or if that period was chosen by hand)."""
    row = conn.execute(
        "SELECT date_from, date_to, reconciled_at FROM eqaime_reconciled "
        "WHERE company_id = ? AND outgoing = ? ORDER BY reconciled_at DESC LIMIT 1",
        (company_id, int(outgoing)),
    ).fetchone()
    if row is None:
        return MONTH
    marked = local_day(row["reconciled_at"])
    span = span_of(date.fromisoformat(row["date_from"]), date.fromisoformat(row["date_to"]), marked)
    return span or MONTH


@dataclass(frozen=True)
class Recheck:
    outgoing: bool
    date_from: date
    date_to: date


def rechecks(conn: Connection, company_id: int, today: date) -> list[Recheck]:
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
