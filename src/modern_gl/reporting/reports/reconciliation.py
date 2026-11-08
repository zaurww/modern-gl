"""Акт сверки (üzləşmə aktı): the settlements with one counterparty over a period, a line
per document, as both sides sign it — the opening balance, what each document did to it,
the closing balance. The accounts are the settlement ones carrying the element's
directory (60, 62, 76 — by type or, untyped, by the directory); ƏDV, revenue and costs
with the same counterparty are not a debt and stay out."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date

from modern_gl.application.books import COMMON, book_params
from modern_gl.domain.accounts import SETTLEMENT_TYPES
from modern_gl.domain.errors import NotFoundError
from modern_gl.i18n import tr
from modern_gl.infrastructure.db import Connection, Row
from modern_gl.reporting.report_common import _DOCS_CTE, Named, name_documents


@dataclass(frozen=True)
class Party:
    """A side of the act: the company or the counterparty, as the act names it."""

    name: str
    legal_name: str = ""
    tax_id: str = ""

    @property
    def title(self) -> str:
        return self.legal_name or self.name


@dataclass
class ActLine(Named):
    """One document: what it did to the debt (Dt — they owe us more, Kt — we owe more)."""

    doc_date: str
    number: int
    document_id: int
    memo: str
    invoice: str  # e-qaimə numbers of its lines, «, »-joined
    debit: int
    credit: int
    balance: int  # running net balance (Dt − Kt) after the document


@dataclass
class ReconciliationAct:
    company: Party
    partner: Party
    date_from: date
    date_to: date
    opening: int
    currency: str = "AZN"  # the company's base currency: the act is in it
    lines: list[ActLine] = field(default_factory=list)

    @property
    def closing(self) -> int:
        return self.lines[-1].balance if self.lines else self.opening

    @property
    def debit(self) -> int:
        return sum(ln.debit for ln in self.lines)

    @property
    def credit(self) -> int:
        return sum(ln.credit for ln in self.lines)


@dataclass(frozen=True)
class ActPartner:
    """A counterparty an act may be made for: it had a balance or a movement."""

    value_id: int
    name: str
    closing: int


# the settlement accounts of the directory :kind — (position, kind id) of the directory
_SETTLEMENT_CTE = """
settlement AS (
    SELECT a.id, CASE WHEN a.sc1_kind_id = :kind THEN 1
                      WHEN a.sc2_kind_id = :kind THEN 2 ELSE 3 END AS pos
    FROM accounts a
    WHERE a.company_id = :company_id
      AND :kind IN (a.sc1_kind_id, a.sc2_kind_id, a.sc3_kind_id)
      AND (a.account_type IS NULL
           OR a.account_type IN (SELECT value FROM json_each(:types)))
)"""


def reconciliation_act(
    conn: Connection,
    company_id: int,
    value_id: int,
    date_from: date | str,
    date_to: date | str,
    layers: Sequence[str] = COMMON,
) -> ReconciliationAct:
    """The act with the element over the period: documents that moved the debt on the
    settlement accounts, the balance before the first and after each."""
    params = book_params(conn, company_id, date_from, date_to, layers)
    partner = _partner(conn, company_id, value_id)
    params.update(value=value_id, kind=partner["kind_id"], types=_types())
    company, currency = _company(conn, company_id)
    act = ReconciliationAct(
        company,
        Party(partner["name"], partner["legal_name"] or "", partner["tax_id"] or ""),
        date.fromisoformat(params["date_from"]),
        date.fromisoformat(params["date_to"]),
        opening=0,
        currency=currency,
    )
    for r in _rows(conn, params):
        if r["doc_date"] < params["date_from"]:
            act.opening = r["balance"]
            continue
        act.lines.append(
            ActLine(
                r["doc_date"],
                r["number"],
                r["document_id"],
                r["memo"] or "",
                r["invoices"] or "",
                r["debit"],
                r["credit"],
                r["balance"],
            )
        )
    name_documents(conn, company_id, act.lines)
    return act


def act_partners(
    conn: Connection,
    company_id: int,
    kind_id: int,
    date_from: date | str,
    date_to: date | str,
    layers: Sequence[str] = COMMON,
) -> list[ActPartner]:
    """The elements of the directory that owed, were owed or moved up to the end of the
    period — every counterparty an act is worth making for, by name."""
    params = book_params(conn, company_id, date_from, date_to, layers)
    params.update(kind=kind_id, types=_types())
    rows = conn.execute(
        f"""
        WITH {_DOCS_CTE}, {_SETTLEMENT_CTE},
        sides AS (
            SELECT CASE s.pos WHEN 1 THEN p.dt_sc1 WHEN 2 THEN p.dt_sc2 ELSE p.dt_sc3 END
                   AS value_id, p.amount AS debit, 0 AS credit
            FROM postings p CROSS JOIN docs
            JOIN settlement s ON s.id = p.debit_account_id
            WHERE docs.id = p.document_id AND p.company_id = :company_id
            UNION ALL
            SELECT CASE s.pos WHEN 1 THEN p.ct_sc1 WHEN 2 THEN p.ct_sc2 ELSE p.ct_sc3 END,
                   0, p.amount
            FROM postings p CROSS JOIN docs
            JOIN settlement s ON s.id = p.credit_account_id
            WHERE docs.id = p.document_id AND p.company_id = :company_id
        )
        SELECT v.id, v.name, SUM(s.debit) - SUM(s.credit) AS closing
        FROM sides s
        JOIN subconto_values v ON v.company_id = :company_id AND v.id = s.value_id
        WHERE v.kind_id = :kind
        GROUP BY v.id, v.name
        ORDER BY v.name
        """,
        params,
    ).fetchall()
    return [ActPartner(r["id"], r["name"], r["closing"]) for r in rows]


def _types() -> str:
    return json.dumps(sorted(SETTLEMENT_TYPES))


def _partner(conn: Connection, company_id: int, value_id: int) -> Row:
    row = conn.execute(
        "SELECT kind_id, name, legal_name, tax_id FROM subconto_values"
        " WHERE company_id = ? AND id = ?",
        (company_id, value_id),
    ).fetchone()
    if row is None:
        raise NotFoundError(tr("элемент справочника не найден"))
    return row


def _company(conn: Connection, company_id: int) -> tuple[Party, str]:
    row = conn.execute(
        "SELECT name, tax_id, base_currency FROM companies WHERE id = ?", (company_id,)
    ).fetchone()
    return Party(row["name"], "", row["tax_id"] or ""), row["base_currency"]


def _rows(conn: Connection, params: dict) -> list[Row]:
    """A row per document that touched the element on a settlement account, with its Dt
    and Kt sums, the running balance over the whole history up to :date_to."""
    on = (
        "CASE WHEN :value IN (p.{sc}1, p.{sc}2, p.{sc}3)"
        " AND p.{side}_account_id IN (SELECT id FROM settlement) THEN p.amount ELSE 0 END"
    )
    return conn.execute(
        f"""
        WITH {_DOCS_CTE}, {_SETTLEMENT_CTE},
        lines AS (
            SELECT docs.doc_date, docs.number, docs.id AS document_id, docs.memo,
                   {on.format(sc="dt_sc", side="debit")} AS debit,
                   {on.format(sc="ct_sc", side="credit")} AS credit, p.invoice
            FROM postings p CROSS JOIN docs
            WHERE docs.id = p.document_id AND p.company_id = :company_id
        ),
        moved AS (SELECT * FROM lines WHERE debit <> 0 OR credit <> 0),
        invoices AS (
            SELECT document_id, string_agg(invoice, ', ') AS invoices
            FROM (SELECT DISTINCT document_id, invoice FROM moved WHERE invoice <> '')
            GROUP BY document_id
        ),
        by_document AS (
            SELECT m.doc_date, m.number, m.document_id, m.memo,
                   SUM(m.debit) AS debit, SUM(m.credit) AS credit
            FROM moved m
            GROUP BY m.doc_date, m.number, m.document_id, m.memo
        )
        SELECT b.*, i.invoices, SUM(b.debit - b.credit) OVER (
            ORDER BY b.doc_date, b.number ROWS UNBOUNDED PRECEDING
        ) AS balance
        FROM by_document b
        LEFT JOIN invoices i ON i.document_id = b.document_id
        ORDER BY b.doc_date, b.number
        """,
        params,
    ).fetchall()
