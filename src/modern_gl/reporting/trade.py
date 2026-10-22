"""Purchases and sales (Alış və satış): the receipts and sales of the company as one list."""

from __future__ import annotations

from dataclasses import dataclass

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
               COALESCE(d.invoice, '') AS invoice,
               COALESCE((
                   SELECT string_agg(name, ', ') FROM (
                       SELECT DISTINCT v.name FROM inventory_lines x
                       JOIN subconto_values v
                         ON v.company_id = x.company_id
                        AND v.id IN (x.offset_sc1, x.offset_sc2, x.offset_sc3)
                       JOIN subconto_kinds k ON k.id = v.kind_id AND k.code = 'counterparty'
                       WHERE x.document_id = d.id
                   )
               ), '') AS counterparties,
               COALESCE((
                   SELECT string_agg(tax_id, ', ') FROM (
                       SELECT DISTINCT v.tax_id FROM inventory_lines x
                       JOIN subconto_values v
                         ON v.company_id = x.company_id
                        AND v.id IN (x.offset_sc1, x.offset_sc2, x.offset_sc3)
                       JOIN subconto_kinds k ON k.id = v.kind_id AND k.code = 'counterparty'
                       WHERE x.document_id = d.id AND v.tax_id IS NOT NULL
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
