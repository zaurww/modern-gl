"""Purchases and sales (Alış və satış): the receipts and sales of the company as one list."""

from __future__ import annotations

from dataclasses import dataclass

from modern_gl.application import attention
from modern_gl.application.attention import Attention, attention_source
from modern_gl.domain.dates import ru_date
from modern_gl.i18n import tr
from modern_gl.infrastructure.db import Connection

PURCHASE, SALE = "receipt", "sale"
# a section lists its returns too: the goods back to the supplier among the purchases
RETURNS_OF = {PURCHASE: "purchase_return", SALE: "sale_return"}


@dataclass(frozen=True)
class TradeDocument:
    id: int
    doc_type: str  # PURCHASE or SALE
    number: int
    doc_date: str
    status: str
    memo: str
    invoice: str
    counterparties: str  # the names on its lines, «, »-separated
    tax_ids: str  # their VÖEN
    amount: int  # without VAT; a return's is negative
    vat: int
    awaits_invoice: int = 0  # 1: a purchase whose e-qaimə comes later (D119)
    basis_note: str = ""  # the basis «Digər»: an act, a receipt… (D-new-basis-other)

    @property
    def is_return(self) -> bool:
        return self.doc_type in RETURNS_OF.values()

    @property
    def total(self) -> int:
        return self.amount + self.vat


def trade_documents(
    conn: Connection,
    company_id: int,
    doc_type: str | None = None,
    limit: int = 500,
    period: tuple[str, str] | None = None,
) -> list[TradeDocument]:
    """Receipts and sales (one kind, or both) with their returns — the latest `limit`
    (of the `period`, ISO days, when given: all of them), listed oldest first (checked
    one by one from the top), with the counterparties of their settlement lines and
    their totals (a return's negative)."""
    kinds = (doc_type,) if doc_type else (PURCHASE, SALE)
    types = (*kinds, *(RETURNS_OF[k] for k in kinds))
    marks = ", ".join("?" * len(types))
    days = "AND d.doc_date BETWEEN ? AND ?" if period else ""
    latest = "" if period else "LIMIT ?"  # a period: all of it
    rows = conn.execute(
        f"""
        SELECT d.id, d.doc_type, d.number, d.doc_date, d.status, d.memo,
               COALESCE(d.invoice, '') AS invoice, d.awaits_invoice,
               COALESCE(d.basis_note, '') AS basis_note,
               COALESCE((
                   SELECT string_agg(name, ', ') FROM (
                       SELECT DISTINCT c.name FROM inventory_line_counterparties c
                       WHERE c.company_id = d.company_id AND c.document_id = d.id
                   )
               ), '') AS counterparties,
               COALESCE((
                   SELECT string_agg(tax_id, ', ') FROM (
                       SELECT DISTINCT c.tax_id FROM inventory_line_counterparties c
                       WHERE c.company_id = d.company_id AND c.document_id = d.id
                         AND c.tax_id IS NOT NULL
                   )
               ), '') AS tax_ids,
               CASE WHEN d.doc_type LIKE '%return' THEN -1 ELSE 1 END
                   * COALESCE(SUM(l.amount), 0) AS amount,
               CASE WHEN d.doc_type LIKE '%return' THEN -1 ELSE 1 END
                   * COALESCE(SUM(l.vat_amount), 0) AS vat
        FROM inventory_documents d
        LEFT JOIN inventory_lines l ON l.company_id = d.company_id AND l.document_id = d.id
        WHERE d.company_id = ? AND d.doc_type IN ({marks}) {days}
        GROUP BY d.id
        ORDER BY d.doc_date DESC, d.id DESC
        {latest}
        """,
        (company_id, *types, *(period or ()), *(() if period else (limit,))),
    )
    return [TradeDocument(**dict(r)) for r in reversed(rows.fetchall())]


@attention_source(attention.AWAITING_INVOICES)
def awaiting_invoices(conn: Connection, company_id: int, day: str) -> list[Attention]:
    """«Bu gün» (D86): purchases whose goods came before their e-qaimə (D119) — a
    forgotten one is ƏDV not taken; the oldest one's day tells how long they wait."""
    row = conn.execute(
        "SELECT COUNT(*) AS n, MIN(doc_date) AS oldest FROM inventory_documents "
        "WHERE company_id = ? AND awaits_invoice = 1 AND doc_date <= ?",
        (company_id, day),
    ).fetchone()
    if not row["n"]:
        return []
    text = tr("Покупки ждут e-qaimə, с {date}", date=ru_date(row["oldest"]))
    return [Attention(text, row["n"], ("purchases",))]
