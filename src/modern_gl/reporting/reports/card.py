"""Карточка счёта and анализ счёта: an account's postings and its corresponding accounts."""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import date

from modern_gl.application.books import COMMON, book_params
from modern_gl.application.quantities import counted_accounts
from modern_gl.infrastructure.db import Connection, Row
from modern_gl.reporting.report_common import (
    _DOCS_CTE,
    LINE_MEMO,
    AccountCard,
    CardLine,
    CorrRow,
    _accounts,
    _find_account,
    _subtree,
)


def account_card(
    conn: Connection,
    company_id: int,
    account: int | str,
    date_from: date | str,
    date_to: date | str,
    layers: Sequence[str] = COMMON,
    subconto: Sequence[int | None] = (),
    invoice: str | None = None,
) -> AccountCard:
    """Карточка счёта: opening balance, each movement with corr account, running balance.

    For a group account, movements of all its subaccounts are included. `subconto` —
    the card of one counterparty, or of one of its contracts: the values of the account's
    own side from the first subconto on (None = «не указано»). `invoice` — only the lines
    of that e-qaimə ("" — the lines without one; D110).
    """
    params = book_params(conn, company_id, date_from, date_to, layers)
    accounts = _accounts(conn, company_id)
    params["accounts"] = json.dumps(_subtree(accounts, _find_account(accounts, account)["id"]))
    raw = _card_rows(conn, params, subconto, invoice)
    opening = 0
    card = AccountCard(opening=0)
    if set(json.loads(params["accounts"])) & counted_accounts(conn, company_id):
        card.quantity_opening = 0
    for r in raw:
        if r["currency"]:
            net = r["cur_dt"] - r["cur_ct"]
            if r["doc_date"] < params["date_from"]:
                card.currency_opening[r["currency"]] = (
                    card.currency_opening.get(r["currency"], 0) + net
                )
            card.currency_closing[r["currency"]] = card.currency_closing.get(r["currency"], 0) + net
        if r["doc_date"] < params["date_from"]:
            opening = r["balance"]
            if card.quantity_opening is not None:
                card.quantity_opening = r["q_balance"]
            continue
        card.lines.append(_card_line(r))
    card.opening = opening
    return card


def _card_rows(
    conn: Connection, params: dict, subconto: Sequence[int | None], invoice: str | None
) -> list[Row]:
    """Each posting line of the accounts, either side, with its corr account and the
    running balance; currency amounts only for currency accounts."""
    for i, value in enumerate(subconto, 1):
        params[f"sc{i}"] = value
    params["invoice"] = invoice
    one_invoice = "" if invoice is None else " AND COALESCE(p.invoice, '') = :invoice"
    return conn.execute(
        f"""
        WITH {_DOCS_CTE},
        lines AS (
            SELECT docs.doc_date, docs.number, docs.id AS document_id, {LINE_MEMO},
                   p.line_no, 0 AS side, p.credit_account_id AS corr_id, p.amount AS dt, 0 AS ct,
                   CASE WHEN own.currency <> 0 THEN p.currency_id END AS currency_id,
                   COALESCE(CASE WHEN own.currency <> 0 THEN p.currency_amount END, 0) AS cur_dt,
                   0 AS cur_ct, p.invoice, p.invoice_kind,
                   COALESCE(p.quantity, 0) AS q_dt, 0 AS q_ct
            FROM postings p CROSS JOIN docs
            JOIN accounts own ON own.id = p.debit_account_id
            WHERE docs.id = p.document_id AND p.company_id = :company_id
              AND p.debit_account_id IN (SELECT value FROM json_each(:accounts))
              {_same_subconto("dt", subconto)}{one_invoice}
            UNION ALL
            SELECT docs.doc_date, docs.number, docs.id, {LINE_MEMO},
                   p.line_no, 1, p.debit_account_id, 0, p.amount,
                   CASE WHEN own.currency <> 0 THEN p.currency_id END,
                   0, COALESCE(CASE WHEN own.currency <> 0 THEN p.currency_amount END, 0),
                   p.invoice, p.invoice_kind, 0, COALESCE(p.quantity, 0)
            FROM postings p CROSS JOIN docs
            JOIN accounts own ON own.id = p.credit_account_id
            WHERE docs.id = p.document_id AND p.company_id = :company_id
              AND p.credit_account_id IN (SELECT value FROM json_each(:accounts))
              {_same_subconto("ct", subconto)}{one_invoice}
        ),
        running AS (
            SELECT *, SUM(dt - ct) OVER (
                ORDER BY doc_date, number, line_no, side ROWS UNBOUNDED PRECEDING
            ) AS balance, SUM(q_dt - q_ct) OVER (
                ORDER BY doc_date, number, line_no, side ROWS UNBOUNDED PRECEDING
            ) AS q_balance
            FROM lines
        )
        SELECT r.*, COALESCE(a.code, a.name) AS corr_code, c.code AS currency
        FROM running r JOIN accounts a ON a.id = r.corr_id
        LEFT JOIN currencies c ON c.id = r.currency_id
        ORDER BY r.doc_date, r.number, r.line_no, r.side
        """,
        params,
    ).fetchall()


def _same_subconto(side: str, subconto: Sequence[int | None]) -> str:
    """AND p.dt_sc1 = :sc1 AND p.dt_sc2 IS NULL… — the lines of one counterparty."""
    return "".join(
        f" AND p.{side}_sc{i} = :sc{i}" if value is not None else f" AND p.{side}_sc{i} IS NULL"
        for i, value in enumerate(subconto, 1)
    )


def _card_line(r: Row) -> CardLine:
    return CardLine(
        doc_date=r["doc_date"],
        number=r["number"],
        document_id=r["document_id"],
        memo=r["memo"],
        corr_code=r["corr_code"],
        corr_id=r["corr_id"],
        debit=r["dt"],
        credit=r["ct"],
        balance=r["balance"],
        currency=r["currency"] or "",
        currency_debit=r["cur_dt"],
        currency_credit=r["cur_ct"],
        invoice=r["invoice"] or "",
        invoice_kind=r["invoice_kind"] or "",
        quantity_debit=r["q_dt"],
        quantity_credit=r["q_ct"],
        quantity_balance=r["q_balance"],
    )


def account_analysis(
    conn: Connection,
    company_id: int,
    account: int | str,
    date_from: date | str,
    date_to: date | str,
    layers: Sequence[str] = COMMON,
) -> list[CorrRow]:
    """Анализ счёта: period turnovers of the account broken down by corresponding account."""
    params = book_params(conn, company_id, date_from, date_to, layers)
    accounts = _accounts(conn, company_id)
    params["accounts"] = json.dumps(_subtree(accounts, _find_account(accounts, account)["id"]))
    raw = conn.execute(
        f"""
        WITH {_DOCS_CTE},
        moves AS (
            SELECT p.credit_account_id AS corr_id, p.amount AS dt, 0 AS ct
            FROM postings p CROSS JOIN docs
            WHERE docs.id = p.document_id AND p.company_id = :company_id
              AND docs.doc_date >= :date_from
              AND p.debit_account_id IN (SELECT value FROM json_each(:accounts))
            UNION ALL
            SELECT p.debit_account_id, 0, p.amount
            FROM postings p CROSS JOIN docs
            WHERE docs.id = p.document_id AND p.company_id = :company_id
              AND docs.doc_date >= :date_from
              AND p.credit_account_id IN (SELECT value FROM json_each(:accounts))
        )
        SELECT a.id, a.code, a.name, SUM(m.dt) AS dt, SUM(m.ct) AS ct
        FROM moves m JOIN accounts a ON a.id = m.corr_id
        GROUP BY a.id ORDER BY a.code IS NULL, a.code, a.name
        """,
        params,
    ).fetchall()
    return [
        CorrRow(
            corr_code=r["code"] or "",
            corr_name=r["name"],
            debit=r["dt"],
            credit=r["ct"],
            corr_id=r["id"],
        )
        for r in raw
    ]
