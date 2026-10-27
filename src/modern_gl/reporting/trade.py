"""Purchases and sales (Alış və satış): the receipts and sales of the company as one list."""

from __future__ import annotations

from dataclasses import dataclass

from modern_gl.application import attention
from modern_gl.application.attention import Attention, attention_source
from modern_gl.domain.dates import ru_date
from modern_gl.i18n import tr
from modern_gl.infrastructure.db import Connection

PURCHASE, SALE = "receipt", "sale"


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
    amount: int  # without VAT
    vat: int
    awaits_invoice: int = 0  # 1: a purchase whose e-qaimə comes later (D119)

    @property
    def total(self) -> int:
        return self.amount + self.vat


def trade_documents(
    conn: Connection, company_id: int, doc_type: str | None = None, limit: int = 500
) -> list[TradeDocument]:
    """Receipts and sales (one kind, or both), newest first, with the counterparties of
    their settlement lines and their totals."""
    types = (doc_type,) if doc_type else (PURCHASE, SALE)
    marks = ", ".join("?" * len(types))
    rows = conn.execute(
        f"""
        SELECT d.id, d.doc_type, d.number, d.doc_date, d.status, d.memo,
               COALESCE(d.invoice, '') AS invoice, d.awaits_invoice,
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
               COALESCE(SUM(l.amount), 0) AS amount,
               COALESCE(SUM(l.vat_amount), 0) AS vat
        FROM inventory_documents d
        LEFT JOIN inventory_lines l ON l.company_id = d.company_id AND l.document_id = d.id
        WHERE d.company_id = ? AND d.doc_type IN ({marks})
        GROUP BY d.id
        ORDER BY d.doc_date DESC, d.id DESC
        LIMIT ?
        """,
        (company_id, *types, limit),
    )
    return [TradeDocument(**dict(r)) for r in rows]


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
