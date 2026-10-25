"""The e-qaimə of the books by number: their accruals and ƏDV (`invoice_rules`, D120) — what
the reconciliation with the portal (D53) and the ƏDV register (D139) count as an e-qaimə.

A purchase is the credit of a settlement account (Dt 41 / Kt 60, Dt 19 / Kt 60), a sale the
debit of one (Dt 62 / Kt 46). The total is with ƏDV. Payments and offsets carry the number
too, but are not the e-qaimə's amount. Only posted documents of the common book count.
"""

from __future__ import annotations

from collections.abc import Sequence
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
) -> dict[str, BookInvoice]:
    """The e-qaimə of the books by number, purchases or sales, every date: their accruals.
    One reversed to nothing (red storno) is not there. `kind` CUSTOMS: the customs
    declarations instead (the ƏDV register, `reporting/vat_register`)."""
    accounts = invoice_accounts(conn, company_id)
    params = book_params(conn, company_id, "0001-01-01", "9999-12-31", layers) | {"kind": kind}
    result: dict[str, BookInvoice] = {}
    for p in conn.execute(
        f"""
        WITH {_DOCS}
        SELECT p.*, docs.doc_date, docs.number
        FROM postings p CROSS JOIN docs
        WHERE docs.id = p.document_id AND p.company_id = :company_id AND p.invoice IS NOT NULL
          AND COALESCE(p.invoice_kind, '') = :kind
        ORDER BY docs.doc_date, docs.number, p.line_no
        """,
        params,
    ):
        debit, credit = accounts[p["debit_account_id"]], accounts[p["credit_account_id"]]
        # the settlement side, and what it is against; the ƏDV the other way round
        side, prefix, other = (debit, "dt", credit) if outgoing else (credit, "ct", debit)
        accrual = is_accrual(side, other)
        vat = is_vat_accrual(other, side)
        if not (accrual or vat):
            continue
        row = result.setdefault(p["invoice"], BookInvoice(p["invoice"], p["doc_date"]))
        if accrual:
            row.total += p["amount"]
            slot = side.partner_at
            who = p[f"{prefix}_sc{slot}"] if slot else None
            if who is not None and who not in row.parties:
                row.parties.append(who)
        if vat:
            row.vat += p["amount"]
        if (p["document_id"], p["number"]) not in row.documents:
            row.documents.append((p["document_id"], p["number"]))
    for row in result.values():
        row.tax_ids = [
            r["tax_id"]
            for party in row.parties
            for r in conn.execute(
                "SELECT tax_id FROM subconto_values WHERE company_id = ? AND id = ? "
                "AND tax_id IS NOT NULL",
                (company_id, party),
            )
        ]
    return {n: r for n, r in result.items() if r.total or r.vat}
