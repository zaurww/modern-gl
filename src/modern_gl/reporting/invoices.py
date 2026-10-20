"""E-qaimə report: postings gathered by the number of the electronic invoice.

A purchase (Dt 41 / Kt 60), its ƏDV (Dt 19 / Kt 60) and the payment (Dt 60 / Kt 51)
carry the same number. Per invoice the report sums the turnovers of the settlement
accounts (of a settlement type, or without a type but with the counterparty directory),
the ƏDV (lines on ƏDV / tax accounts), and what is left unpaid; it names the
counterparty and contract of the settlement lines and the documents.

An invoice is shown when it has a posting in the period; the amounts are everything
posted on it up to the end of the period (a January invoice paid in March shows paid).
With `open_only` every invoice with a balance at the end of the period is shown.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date

from modern_gl.domain.accounts import SETTLEMENT_TYPES, VAT_TYPES
from modern_gl.reporting.reports import _DOCS_CTE, COMMON, _params


@dataclass
class InvoiceRow:
    invoice: str
    doc_date: str = ""  # of the first posting
    counterparties: list[int] = field(default_factory=list)  # more than one: a mistake?
    contract_id: int | None = None
    debit: int = 0  # turnovers of the settlement accounts
    credit: int = 0
    vat: int = 0
    documents: list[tuple[int, int]] = field(default_factory=list)  # (id, number)
    in_period: bool = False

    @property
    def balance(self) -> int:
        """Dt - Kt of the settlement accounts: unpaid (a sale > 0, a purchase < 0)."""
        return self.debit - self.credit

    @property
    def counterparty_id(self) -> int | None:
        return self.counterparties[0] if self.counterparties else None


def invoice_report(
    conn: sqlite3.Connection,
    company_id: int,
    date_from: date | str,
    date_to: date | str,
    layers: Sequence[str] = COMMON,
    open_only: bool = False,
) -> list[InvoiceRow]:
    params = _params(conn, company_id, date_from, date_to, layers)
    chart = _Chart(conn, company_id)
    rows: dict[str, InvoiceRow] = {}
    for p in conn.execute(
        f"""
        WITH {_DOCS_CTE}
        SELECT p.*, docs.doc_date, docs.number
        FROM postings p JOIN docs ON docs.id = p.document_id
        WHERE p.company_id = :company_id AND p.invoice IS NOT NULL
        ORDER BY docs.doc_date, docs.number, p.line_no
        """,
        params,
    ):
        row = rows.setdefault(p["invoice"], InvoiceRow(p["invoice"], p["doc_date"]))
        row.in_period |= p["doc_date"] >= params["date_from"]
        if (p["document_id"], p["number"]) not in row.documents:
            row.documents.append((p["document_id"], p["number"]))
        chart.add(row, p)
    if open_only:
        return [r for r in rows.values() if r.balance != 0]
    return [r for r in rows.values() if r.in_period]


class _Chart:
    """What each account of the company is to an invoice: a settlement with a partner
    (where its counterparty and contract are) or ƏDV."""

    def __init__(self, conn: sqlite3.Connection, company_id: int) -> None:
        self.accounts = {
            r["id"]: r
            for r in conn.execute(
                "SELECT id, account_type, sc1_kind_id, sc2_kind_id, sc3_kind_id "
                "FROM accounts WHERE company_id = ?",
                (company_id,),
            )
        }
        kinds = {
            r["code"]: r["id"]
            for r in conn.execute(
                "SELECT id, code FROM subconto_kinds WHERE company_id = ? "
                "AND code IN ('counterparty', 'contract')",
                (company_id,),
            )
        }
        self.partner, self.contract = kinds.get("counterparty"), kinds.get("contract")

    def slot(self, account: sqlite3.Row, kind: int | None) -> int | None:
        if kind is None:
            return None
        return next((i for i in (1, 2, 3) if account[f"sc{i}_kind_id"] == kind), None)

    def add(self, row: InvoiceRow, p: sqlite3.Row) -> None:
        """One posting of the invoice: settlement turnovers, partner, contract, ƏDV."""
        vat = False
        for side, prefix in (("debit", "dt"), ("credit", "ct")):
            account = self.accounts[p[f"{side}_account_id"]]
            vat |= account["account_type"] in VAT_TYPES
            partner_at = self.slot(account, self.partner)
            kind = account["account_type"]
            if not (kind in SETTLEMENT_TYPES or (kind is None and partner_at is not None)):
                continue
            if side == "debit":
                row.debit += p["amount"]
            else:
                row.credit += p["amount"]
            who = p[f"{prefix}_sc{partner_at}"] if partner_at else None
            if who is not None and who not in row.counterparties:
                row.counterparties.append(who)
            contract_at = self.slot(account, self.contract)
            if contract_at and row.contract_id is None:
                row.contract_id = p[f"{prefix}_sc{contract_at}"]
        if vat:
            row.vat += p["amount"]
