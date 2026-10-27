"""The e-qaimə of the books by number: their accruals and ƏDV (`invoice_rules`, D120) — what
the reconciliation with the portal (D53) and the ƏDV register (D139) count as an e-qaimə.

A purchase is the credit of a settlement account (Dt 41 / Kt 60, Dt 19 / Kt 60), a sale the
debit of one (Dt 62 / Kt 46). The total is with ƏDV. Payments and offsets carry the number
too, but are not the e-qaimə's amount. Only posted documents of the common book count.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from modern_gl.application.books import COMMON, book_params, docs_cte
from modern_gl.application.invoice_rules import invoice_accounts, is_accrual, is_vat_accrual
from modern_gl.domain.invoice import EQAIME
from modern_gl.infrastructure.db import Connection

_DOCS = docs_cte("d.id, d.doc_date, d.number, d.memo")


@dataclass
class BookInvoice:
    number: str
    doc_date: str  # of the first accrual
    total: int = 0  # with ƏDV
    vat: int = 0
    parties: list[int] = field(default_factory=list)
    tax_ids: list[str] = field(default_factory=list)
    documents: list[tuple[int, int]] = field(default_factory=list)  # (id, number)

    @property
    def amount(self) -> int:
        return self.total - self.vat


def book_invoices(
    conn: Connection,
    company_id: int,
    outgoing: bool,
    layers: Sequence[str] = COMMON,
    kind: str = EQAIME,
    period: tuple[str, str] | None = None,
) -> dict[str, BookInvoice]:
    """The e-qaimə of the books by number, purchases or sales, every date: their accruals.
    One reversed to nothing (red storno) is not there. `kind` CUSTOMS: the customs
    declarations instead (the ƏDV register, `reporting/vat_register`). `period` (ISO):
    only the numbers with a posting in it — each still with all its postings; the ones
    dated in the period are among them."""
    pairs = _pairs(conn, company_id, outgoing)
    if not pairs:
        return {}
    params = book_params(conn, company_id, "0001-01-01", "9999-12-31", layers) | {"kind": kind}
    chosen = ""
    if period is not None:
        params |= {"first": period[0], "last": period[1]}
        chosen = """
          AND p.invoice IN (
            SELECT q.invoice FROM postings q CROSS JOIN docs e
            WHERE e.id = q.document_id AND q.company_id = :company_id
              AND q.invoice IS NOT NULL AND e.doc_date BETWEEN :first AND :last)"""
    who = "CASE r.partner " + " ".join(
        f"WHEN {i} THEN p.{'dt' if outgoing else 'ct'}_sc{i}" for i in (1, 2, 3)
    )
    result: dict[str, BookInvoice] = {}
    # summed in SQL by number, document and counterparty; the postings come before the
    # documents (CROSS JOIN), as in `invoices.py`
    for p in conn.execute(
        f"""
        WITH {_DOCS},
        pairs (debit_id, credit_id, accrual, vat, partner) AS (VALUES {pairs})
        SELECT p.invoice, p.document_id, docs.doc_date, docs.number, {who} END AS who,
               SUM(r.accrual * p.amount) AS total, SUM(r.vat * p.amount) AS vat
        FROM postings p CROSS JOIN docs
        JOIN pairs r ON r.debit_id = p.debit_account_id AND r.credit_id = p.credit_account_id
        WHERE docs.id = p.document_id AND p.company_id = :company_id AND p.invoice IS NOT NULL
          AND COALESCE(p.invoice_kind, '') = :kind{chosen}
        GROUP BY p.invoice, p.document_id, docs.doc_date, docs.number, {who} END
        ORDER BY docs.doc_date, docs.number, MIN(p.line_no)
        """,
        params,
    ):
        row = result.setdefault(p["invoice"], BookInvoice(p["invoice"], p["doc_date"]))
        row.total += p["total"]
        row.vat += p["vat"]
        if p["who"] is not None and p["who"] not in row.parties:
            row.parties.append(p["who"])
        if (p["document_id"], p["number"]) not in row.documents:
            row.documents.append((p["document_id"], p["number"]))
    tax_ids = {
        r["id"]: r["tax_id"]
        for r in conn.execute(
            "SELECT id, tax_id FROM subconto_values WHERE company_id = ? AND tax_id IS NOT NULL",
            (company_id,),
        )
    }
    for row in result.values():
        row.tax_ids = [tax_ids[party] for party in row.parties if party in tax_ids]
    return {n: r for n, r in result.items() if r.total or r.vat}


def _pairs(conn: Connection, company_id: int, outgoing: bool) -> str:
    """`VALUES` of the (debit, credit) pairs posted with a number that accrue the e-qaimə
    or its ƏDV: whether they are the accrual, the ƏDV, and the position of the
    counterparty on the settlement side of an accrual (0: none)."""
    accounts = invoice_accounts(conn, company_id)
    found: list[str] = []
    for p in conn.execute(
        "SELECT DISTINCT debit_account_id, credit_account_id FROM postings "
        "WHERE company_id = ? AND invoice IS NOT NULL",
        (company_id,),
    ):
        debit, credit = accounts[p[0]], accounts[p[1]]
        # the settlement side, and what it is against; the ƏDV the other way round
        side, other = (debit, credit) if outgoing else (credit, debit)
        accrual, vat = is_accrual(side, other), is_vat_accrual(other, side)
        if accrual or vat:
            partner = (side.partner_at or 0) if accrual else 0
            found.append(f"({int(p[0])}, {int(p[1])}, {int(accrual)}, {int(vat)}, {partner})")
    return ", ".join(found)


def book_digest(
    conn: Connection, company_id: int, outgoing: bool, date_from: str, date_to: str
) -> str:
    """What the books say of the e-qaimə of a period, as one fingerprint (`digest`)."""
    return digest(book_invoices(conn, company_id, outgoing).values(), date_from, date_to)


def digest(books: Iterable[BookInvoice], date_from: str, date_to: str) -> str:
    """Each number dated in the period with its total, ƏDV and counterparties, as one
    fingerprint. A period marked reconciled keeps it; a later correction to one of its
    e-qaimə (D140) changes it."""
    lines = sorted(
        f"{b.number}|{b.total}|{b.vat}|{','.join(map(str, sorted(b.parties)))}"
        for b in books
        if date_from <= b.doc_date <= date_to
    )
    return hashlib.sha256("\n".join(lines).encode()).hexdigest()
