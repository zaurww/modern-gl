"""Postings gathered by the number of the e-qaimə (or of the customs declaration of
imported goods — kept apart from e-qaimə numbers): per number the turnovers of the
settlement accounts, the ƏDV, the counterparty, the documents (`gathered_invoices`,
the rule — `invoice_rules`, D120); and what a counterparty still owes or is owed on a day
(`open_invoices`, D51) — the bank splits payments and advance offsets by it. The report
over the numbers is `reporting/invoices.py`."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date

from modern_gl.application.books import COMMON, book_params, docs_cte
from modern_gl.application.invoice_rules import invoice_accounts, turnover_sides
from modern_gl.domain.eqaime import ON_APPROVAL, TURNOVER
from modern_gl.infrastructure.db import Connection

# documents of a status: drafts too, for the e-qaimə a payment may name
_STATUS_DOCS_CTE = docs_cte("d.id, d.doc_date, d.number, d.memo", status=":status")


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
    free: int = 0  # of the balance, paid without a number (`free_money.mark_free_money`)

    @property
    def balance(self) -> int:
        """Dt - Kt of the settlement accounts: unpaid (a sale > 0, a purchase < 0)."""
        return self.debit - self.credit

    @property
    def unpaid(self) -> int:
        """What is really left: the balance by number less the money without one."""
        return max(abs(self.balance) - self.free, 0)

    @property
    def counterparty_id(self) -> int | None:
        return self.counterparties[0] if self.counterparties else None


def gathered_invoices(
    conn: Connection,
    company_id: int,
    params: dict,
    status: str = "posted",
    only: str = "",
) -> dict[tuple[str, str], InvoiceRow]:
    """The invoices of the documents of a status up to `date_to`, by (kind, number), in
    the order of their first posting; `only` — IN_PERIOD (a posting from `date_from`) or
    UNPAID (a balance), chosen in SQL. What each posting counts as is worked out in SQL
    too, by its pair of accounts (`_pairs`); here the postings are only added up."""
    pairs = _pairs(conn, company_id)
    if not pairs:
        return {}
    sql = _gathered_sql(pairs, only)
    rows: dict[tuple[str, str], InvoiceRow] = {}
    for p in conn.execute(sql, {**params, "status": status}):
        row = rows.get((p["kind"], p["invoice"]))
        if row is None:
            row = rows[(p["kind"], p["invoice"])] = InvoiceRow(
                p["invoice"], p["doc_date"], p["kind"]
            )
        row.in_period |= p["doc_date"] >= params["date_from"]
        if (p["document_id"], p["number"]) not in row.documents:
            row.documents.append((p["document_id"], p["number"]))
        row.debit += p["debit"]
        row.credit += p["credit"]
        row.vat += p["vat"]
        row.deposit += p["deposit"]
        for who in (p["dt_who"], p["ct_who"]):
            if who is not None and who not in row.counterparties:
                row.counterparties.append(who)
        if row.contract_id is None:
            row.contract_id = p["dt_contract"] if p["dt_contract"] is not None else p["ct_contract"]
    return rows


def _pairs(conn: Connection, company_id: int) -> str:
    """`VALUES` of every (debit, credit) pair of accounts posted with an invoice: whether
    each side is a settlement turnover, the position of its counterparty and contract (0:
    none, or no turnover), whether the posting is ƏDV, a deposit payment (D41, D120)."""
    accounts = invoice_accounts(conn, company_id)
    found = []
    for p in conn.execute(
        "SELECT DISTINCT debit_account_id, credit_account_id FROM postings "
        "WHERE company_id = ? AND invoice IS NOT NULL",
        (company_id,),
    ):
        debit, credit = accounts[p[0]], accounts[p[1]]
        turns = turnover_sides(debit, credit)
        sides = [
            (int(turn), (a.partner_at or 0) * turn, (a.contract_at or 0) * turn)
            for a, turn in zip((debit, credit), turns, strict=True)
        ]
        vat = int(debit.vat or credit.vat)
        deposit = int("vat_deposit" in (debit.account_type, credit.account_type))
        values = (int(p[0]), int(p[1]), *sides[0], *sides[1], vat, deposit)
        found.append(f"({', '.join(str(v) for v in values)})")
    return ",\n        ".join(found)


def _side(column: str, prefix: str) -> str:
    """The subconto of a side of a posting at its position in `pairs.<column>` (0: none)."""
    cases = " ".join(f"WHEN {i} THEN p.{prefix}_sc{i}" for i in (1, 2, 3))
    return f"CASE r.{column} {cases} END"


IN_PERIOD, UNPAID = "in_period", "unpaid"  # which invoices `gathered_invoices` returns

# what each posting with an invoice counts as, by its pair of accounts. The postings come
# before the documents (CROSS JOIN keeps SQLite to that order): with the documents first
# it read every invoice posting again for each document
_LINES = f"""
    SELECT COALESCE(p.invoice_kind, '') AS kind, p.invoice, p.document_id, p.line_no,
           docs.doc_date, docs.number,
           r.dt_turn * p.amount AS debit, r.ct_turn * p.amount AS credit,
           r.vat * p.amount AS vat, r.deposit * p.amount AS deposit,
           {_side("dt_partner", "dt")} AS dt_who, {_side("ct_partner", "ct")} AS ct_who,
           {_side("dt_contract", "dt")} AS dt_contract,
           {_side("ct_contract", "ct")} AS ct_contract
    FROM {{source}} CROSS JOIN docs
    JOIN pairs r ON r.debit_id = p.debit_account_id AND r.credit_id = p.credit_account_id
    WHERE docs.id = p.document_id AND p.company_id = :company_id
      AND p.invoice IS NOT NULL{{chosen}}"""

# the invoices asked for, then their postings by the index on the number
_CHOSEN = {
    IN_PERIOD: """
    SELECT DISTINCT COALESCE(p.invoice_kind, '') AS kind, p.invoice
    FROM postings p CROSS JOIN docs
    WHERE docs.id = p.document_id AND p.company_id = :company_id
      AND p.invoice IS NOT NULL AND docs.doc_date >= :date_from""",
    UNPAID: f"""
    SELECT kind, invoice FROM ({_LINES.format(source="postings p", chosen="")}) a
    GROUP BY kind, invoice HAVING SUM(debit) <> SUM(credit)""",
}


def _gathered_sql(pairs: str, only: str) -> str:
    """The postings of the invoices asked for, in order (`gathered_invoices`)."""
    head = f"""
WITH {_STATUS_DOCS_CTE},
pairs (debit_id, credit_id, dt_turn, dt_partner, dt_contract,
       ct_turn, ct_partner, ct_contract, vat, deposit) AS (
    VALUES {pairs}
)"""
    if only:
        head += f",\nchosen AS ({_CHOSEN[only]}\n)"
        lines = _LINES.format(
            source="chosen c CROSS JOIN postings p",
            chosen="\n      AND p.invoice = c.invoice AND COALESCE(p.invoice_kind, '') = c.kind",
        )
    else:
        lines = _LINES.format(source="postings p", chosen="")
    return f"{head}\n{lines}\nORDER BY docs.doc_date, docs.number, p.line_no"


DRAFT, PORTAL = "draft", "portal"  # where an open e-qaimə is known from, but the books


@dataclass
class OpenInvoice:
    invoice: str
    doc_date: str
    amount: int  # still to pay (> 0)
    source: str = ""  # "": posted; DRAFT: only a draft has it; PORTAL: only the portal
    vat: int = 0  # of it, the ƏDV still to pay from (or to) the deposit account


def open_invoices(
    conn: Connection,
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
    params = book_params(conn, company_id, on_date, on_date, layers)
    parties, tin = same_firm(conn, company_id, counterparty_id)

    def accrued(row: InvoiceRow) -> int:  # what the e-qaimə itself made owed
        return row.credit if payable else row.debit

    def settled(row: InvoiceRow) -> int:  # what was paid on it
        return row.debit if payable else row.credit

    posted = {n: r for (k, n), r in gathered_invoices(conn, company_id, params).items() if k == ""}
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
        for (k, n), r in gathered_invoices(conn, company_id, params, "draft").items()
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


def eqaime_known(conn: Connection, company_id: int, date_from: str, date_to: str) -> bool:
    """Whether the company knows any e-qaimə of the days: read from the portal, in a
    purchase or sale, in a posting. None — they were likely not loaded yet."""
    return bool(
        conn.execute(
            """
            SELECT EXISTS (SELECT 1 FROM eqaime_portal WHERE company_id = :c
                           AND doc_date BETWEEN :a AND :b)
                OR EXISTS (SELECT 1 FROM inventory_documents WHERE company_id = :c
                           AND invoice IS NOT NULL AND doc_date BETWEEN :a AND :b)
                OR EXISTS (SELECT 1 FROM postings p
                           JOIN documents d ON d.company_id = p.company_id
                            AND d.id = p.document_id
                           WHERE p.company_id = :c AND p.invoice IS NOT NULL
                             AND d.doc_date BETWEEN :a AND :b) AS known
            """,
            {"c": company_id, "a": date_from, "b": date_to},
        ).fetchone()["known"]
    )


def _other_way(conn: Connection, company_id: int, payable: bool) -> set[str]:
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


def same_firm(conn: Connection, company_id: int, counterparty_id: int) -> tuple[set[int], str]:
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
    conn: Connection, company_id: int, on_date: str, payable: bool, parties: set[int]
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
    conn: Connection, company_id: int, on_date: str, payable: bool, tin: str
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
