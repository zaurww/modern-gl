"""E-qaimə report: postings gathered by the number of the electronic invoice (or of
the customs declaration of imported goods — kept apart from e-qaimə numbers).

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

import json
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date

from modern_gl.domain.accounts import SETTLEMENT_TYPES, VAT_TYPES
from modern_gl.domain.eqaime import ON_APPROVAL, TURNOVER
from modern_gl.reporting.reports import _DOCS_CTE, COMMON, _params

# documents of a status: drafts too, for the e-qaimə a payment may name
_STATUS_DOCS_CTE = _DOCS_CTE.replace("d.status = 'posted'", "d.status = :status")


@dataclass
class InvoiceRow:
    invoice: str
    doc_date: str = ""  # of the first posting
    kind: str = ""  # domain.invoice: "" an e-qaimə, "customs" a customs declaration
    counterparties: list[int] = field(default_factory=list)  # more than one: a mistake?
    contract_id: int | None = None
    debit: int = 0  # turnovers of the settlement accounts
    credit: int = 0
    vat: int = 0
    deposit: int = 0  # paid from or to the ƏDV deposit account (D41)
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
    rows = _gathered(conn, company_id, params)
    if open_only:
        return [r for r in rows.values() if r.balance != 0]
    return [r for r in rows.values() if r.in_period]


def _gathered(
    conn: sqlite3.Connection, company_id: int, params: dict, status: str = "posted"
) -> dict[tuple[str, str], InvoiceRow]:
    """The invoices of the documents of a status up to `date_to`, by (kind, number)."""
    chart = _Chart(conn, company_id)
    rows: dict[tuple[str, str], InvoiceRow] = {}
    for p in conn.execute(
        f"""
        WITH {_STATUS_DOCS_CTE}
        SELECT p.*, docs.doc_date, docs.number
        FROM postings p JOIN docs ON docs.id = p.document_id
        WHERE p.company_id = :company_id AND p.invoice IS NOT NULL
        ORDER BY docs.doc_date, docs.number, p.line_no
        """,
        {**params, "status": status},
    ):
        kind = p["invoice_kind"] or ""
        row = rows.setdefault((kind, p["invoice"]), InvoiceRow(p["invoice"], p["doc_date"], kind))
        row.in_period |= p["doc_date"] >= params["date_from"]
        if (p["document_id"], p["number"]) not in row.documents:
            row.documents.append((p["document_id"], p["number"]))
        chart.add(row, p)
    return rows


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
        vat = deposit = False
        for side, prefix in (("debit", "dt"), ("credit", "ct")):
            account = self.accounts[p[f"{side}_account_id"]]
            vat |= account["account_type"] in VAT_TYPES
            deposit |= account["account_type"] == "vat_deposit"
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
        if deposit:
            row.deposit += p["amount"]


DRAFT, PORTAL = "draft", "portal"  # where an open e-qaimə is known from, but the books


@dataclass
class OpenInvoice:
    invoice: str
    doc_date: str
    amount: int  # still to pay (> 0)
    source: str = ""  # "": posted; DRAFT: only a draft has it; PORTAL: only the portal
    vat: int = 0  # of it, the ƏDV still to pay from (or to) the deposit account


def open_invoices(
    conn: sqlite3.Connection,
    company_id: int,
    counterparty_id: int,
    payable: bool,
    on_date: date | str,
    layers: Sequence[str] = COMMON,
) -> list[OpenInvoice]:
    """E-qaimə of the counterparty not yet settled on the day, oldest first: what is owed
    to it (`payable`, a purchase: Kt balance) or what it owes (a sale: Dt balance).

    What is owed comes from the posted documents; an e-qaimə none of them names yet comes
    from a draft (journal, purchase or sale — an imported one not posted yet), else from
    what the portal showed (an e-qaimə not entered at all). The posted payments on its
    number are taken off. The counterparty is known by its VÖEN as well: a second element
    of the directory with the same VÖEN is the same firm."""
    params = _params(conn, company_id, on_date, on_date, layers)
    parties, tin = _same_firm(conn, company_id, counterparty_id)

    def accrued(row: InvoiceRow) -> int:  # what the e-qaimə itself made owed
        return row.credit if payable else row.debit

    def settled(row: InvoiceRow) -> int:  # what was paid on it
        return row.debit if payable else row.credit

    posted = {n: r for (k, n), r in _gathered(conn, company_id, params).items() if k == ""}
    paid = {n: settled(r) for n, r in posted.items()}
    deposit = {n: r.deposit for n, r in posted.items()}
    known = {n for n, r in posted.items() if accrued(r)}

    def still(number: str, doc_date: str, owed: int, vat: int, source: str) -> OpenInvoice:
        left = owed - paid.get(number, 0)
        vat_left = min(max(vat - deposit.get(number, 0), 0), max(left, 0))
        return OpenInvoice(number, doc_date, left, source, vat_left)

    found = [
        still(n, r.doc_date, accrued(r), r.vat, "")
        for n, r in posted.items()
        if n in known and parties & set(r.counterparties)
    ]
    others: list[tuple[str, str, int, int, bool, str]] = [  # number, date, owed, ƏDV, whose
        (n, r.doc_date, accrued(r), r.vat, bool(parties & set(r.counterparties)), DRAFT)
        for (k, n), r in _gathered(conn, company_id, params, "draft").items()
        if k == "" and accrued(r)
    ]
    others += _trade_drafts(conn, company_id, params["date_to"], payable, parties)
    others += _portal(conn, company_id, params["date_to"], payable, tin)
    for number, doc_date, owed, vat, whose, source in others:
        if number in known:  # the books, or a source before this one, know it already
            continue
        known.add(number)
        if whose:
            found.append(still(number, doc_date, owed, vat, source))
    other_way = _other_way(conn, company_id, payable)  # a payment on a purchase is no sale
    found.sort(key=lambda i: (i.doc_date, i.invoice))
    return [i for i in found if i.amount > 0 and i.invoice not in other_way]


def _other_way(conn: sqlite3.Connection, company_id: int, payable: bool) -> set[str]:
    """E-qaimə known to go the other way: sales when paying, purchases when money comes
    in (a purchase or sale document, or the portal's list) — an advance paid on a purchase
    not posted yet is not offered as owed to the company."""
    rows = conn.execute(
        "SELECT invoice FROM inventory_documents WHERE company_id = ? AND doc_type = ? "
        "AND invoice IS NOT NULL AND COALESCE(invoice_kind, '') = '' "
        "UNION SELECT number FROM eqaime_portal WHERE company_id = ? AND outgoing = ?",
        (company_id, "sale" if payable else "receipt", company_id, int(payable)),
    )
    return {r[0] for r in rows}


def _same_firm(
    conn: sqlite3.Connection, company_id: int, counterparty_id: int
) -> tuple[set[int], str]:
    """The counterparty and the elements of its directory with its VÖEN; the VÖEN."""
    row = conn.execute(
        "SELECT kind_id, COALESCE(tax_id, '') AS tin FROM subconto_values "
        "WHERE company_id = ? AND id = ?",
        (company_id, counterparty_id),
    ).fetchone()
    if row is None or not row["tin"]:
        return {counterparty_id}, ""
    same = conn.execute(
        "SELECT id FROM subconto_values WHERE company_id = ? AND kind_id = ? AND tax_id = ?",
        (company_id, row["kind_id"], row["tin"]),
    )
    return {counterparty_id, *(r["id"] for r in same)}, row["tin"]


def _trade_drafts(
    conn: sqlite3.Connection, company_id: int, on_date: str, payable: bool, parties: set[int]
) -> list[tuple[str, str, int, int, bool, str]]:
    """Purchase (sale) drafts with an e-qaimə number: their total with ƏDV, and the ƏDV."""
    rows = conn.execute(
        """
        SELECT d.invoice, d.doc_date, SUM(l.amount + l.vat_amount) AS total,
               SUM(l.vat_amount) AS vat,
               json_group_array(l.offset_sc1) AS sc1, json_group_array(l.offset_sc2) AS sc2,
               json_group_array(l.offset_sc3) AS sc3
        FROM inventory_documents d
        JOIN inventory_lines l ON l.company_id = d.company_id AND l.document_id = d.id
        WHERE d.company_id = ? AND d.status = 'draft' AND d.doc_type = ?
          AND d.invoice IS NOT NULL AND COALESCE(d.invoice_kind, '') = ''
          AND d.doc_date <= ?
        GROUP BY d.id
        ORDER BY d.doc_date, d.number
        """,
        (company_id, "receipt" if payable else "sale", on_date),
    )
    found = []
    for r in rows:
        values = {v for column in ("sc1", "sc2", "sc3") for v in json.loads(r[column])}
        whose = bool(parties & values)
        found.append((r["invoice"], r["doc_date"], r["total"], r["vat"], whose, DRAFT))
    return found


def _portal(
    conn: sqlite3.Connection, company_id: int, on_date: str, payable: bool, tin: str
) -> list[tuple[str, str, int, int, bool, str]]:
    """E-qaimə the portal showed for the VÖEN (in turnover or awaiting approval)."""
    if not tin:
        return []
    statuses = (*TURNOVER, ON_APPROVAL)
    rows = conn.execute(
        f"""
        SELECT number, doc_date, total, vat FROM eqaime_portal
        WHERE company_id = ? AND outgoing = ? AND party_tin = ? AND doc_date <= ?
          AND status IN ({", ".join("?" * len(statuses))})
        ORDER BY doc_date, number
        """,
        (company_id, int(not payable), tin, on_date, *statuses),
    )
    return [(r["number"], r["doc_date"], r["total"], r["vat"], True, PORTAL) for r in rows]
