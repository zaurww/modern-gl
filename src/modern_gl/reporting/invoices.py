"""E-qaimə report: postings gathered by the number of the electronic invoice (or of
the customs declaration of imported goods — kept apart from e-qaimə numbers).

A purchase (Dt 41 / Kt 60), its ƏDV (Dt 19 / Kt 60) and the payment (Dt 60 / Kt 51)
carry the same number. Per invoice the report sums the turnovers of the settlement
accounts, the ƏDV (lines on ƏDV / tax accounts) and what is left unpaid — the rule is
`invoice_rules` (D120); it names the
counterparty and contract of the settlement lines and the documents.

An invoice is shown when it has a posting in the period; the amounts are everything
posted on it up to the end of the period (a January invoice paid in March shows paid).
With `open_only` every invoice with a balance at the end of the period is shown.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

from modern_gl.application.attention import Attention, attention_source
from modern_gl.application.books import COMMON, book_params
from modern_gl.application.invoices import IN_PERIOD, UNPAID, InvoiceRow, gathered_invoices
from modern_gl.i18n import tr
from modern_gl.infrastructure.db import Connection


def invoice_report(
    conn: Connection,
    company_id: int,
    date_from: date | str,
    date_to: date | str,
    layers: Sequence[str] = COMMON,
    open_only: bool = False,
) -> list[InvoiceRow]:
    params = book_params(conn, company_id, date_from, date_to, layers)
    only = UNPAID if open_only else IN_PERIOD
    return list(gathered_invoices(conn, company_id, params, only=only).values())


@attention_source
def unpaid_invoices(conn: Connection, company_id: int, day: str) -> list[Attention]:
    """«Bu gün» (D86): e-qaimə not settled on the day — to suppliers, and from buyers."""
    rows = invoice_report(conn, company_id, day, day, open_only=True)
    owed = [r.balance for r in rows if r.balance < 0]
    due = [r.balance for r in rows if r.balance > 0]
    return [
        Attention(tr("Неоплаченные e-qaimə поставщиков"), len(owed), ("invoices",), -sum(owed)),
        Attention(tr("Неоплаченные e-qaimə покупателей"), len(due), ("invoices",), sum(due)),
    ]
