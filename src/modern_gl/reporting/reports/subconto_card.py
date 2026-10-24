"""Карточка субконто (as in 1C 7.7, D126): every posting that carries one element of a
directory, on any account or on one — a counterparty on 60 and 62, an order on the
client's, the suppliers' and the revenue accounts — with the running balance."""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import date

from modern_gl.application.books import COMMON, book_params
from modern_gl.domain.errors import NotFoundError
from modern_gl.i18n import tr
from modern_gl.infrastructure.db import Connection, Row
from modern_gl.reporting.report_common import (
    _DOCS_CTE,
    SubcontoCard,
    SubcontoCardLine,
    _accounts,
    _find_account,
    _subtree,
)


def subconto_card(
    conn: Connection,
    company_id: int,
    value_id: int,
    date_from: date | str,
    date_to: date | str,
    layers: Sequence[str] = COMMON,
    account: int | str | None = None,
) -> SubcontoCard:
    """The element's postings in the period, each with both accounts and the amount on
    the side(s) the element is on; the running balance nets every account carrying it
    (what is owed to us less what we owe, the revenue less the costs). With `account`
    only that account (a group — with its subaccounts)."""
    params = book_params(conn, company_id, date_from, date_to, layers)
    params["value"] = value_id
    if (
        conn.execute(
            "SELECT id FROM subconto_values WHERE company_id = ? AND id = ?", (company_id, value_id)
        ).fetchone()
        is None
    ):
        raise NotFoundError(tr("элемент справочника не найден"))
    only = ""
    if account is not None:
        accounts = _accounts(conn, company_id)
        params["accounts"] = json.dumps(_subtree(accounts, _find_account(accounts, account)["id"]))
        only = " AND p.{side}_account_id IN (SELECT value FROM json_each(:accounts))"
    card = SubcontoCard(opening=0)
    for r in _lines(conn, params, only):
        if r["doc_date"] < params["date_from"]:
            card.opening = r["balance"]
            continue
        card.lines.append(_line(r))
    return card


def _lines(conn: Connection, params: dict, only: str) -> list[Row]:
    on = "CASE WHEN :value IN (p.{side_sc}1, p.{side_sc}2, p.{side_sc}3){only} THEN 1 ELSE 0 END"
    on_dt = on.format(side_sc="dt_sc", only=only.format(side="debit"))
    on_ct = on.format(side_sc="ct_sc", only=only.format(side="credit"))
    return conn.execute(
        f"""
        WITH {_DOCS_CTE},
        lines AS (
            SELECT docs.doc_date, docs.number, docs.id AS document_id, docs.memo, p.line_no,
                   p.debit_account_id, p.credit_account_id, p.amount, p.invoice, p.invoice_kind,
                   {on_dt} AS on_dt, {on_ct} AS on_ct
            FROM postings p CROSS JOIN docs
            WHERE docs.id = p.document_id AND p.company_id = :company_id
        ),
        running AS (
            SELECT *, SUM(amount * on_dt - amount * on_ct) OVER (
                ORDER BY doc_date, number, line_no ROWS UNBOUNDED PRECEDING
            ) AS balance
            FROM lines
            WHERE on_dt = 1 OR on_ct = 1
        )
        SELECT r.*, COALESCE(d.code, d.name) AS debit_code, COALESCE(c.code, c.name) AS credit_code
        FROM running r
        JOIN accounts d ON d.id = r.debit_account_id
        JOIN accounts c ON c.id = r.credit_account_id
        ORDER BY r.doc_date, r.number, r.line_no
        """,
        params,
    ).fetchall()


def _line(r: Row) -> SubcontoCardLine:
    return SubcontoCardLine(
        doc_date=r["doc_date"],
        number=r["number"],
        document_id=r["document_id"],
        memo=r["memo"],
        debit_code=r["debit_code"],
        credit_code=r["credit_code"],
        debit=r["amount"] if r["on_dt"] else 0,
        credit=r["amount"] if r["on_ct"] else 0,
        balance=r["balance"],
        debit_id=r["debit_account_id"],
        credit_id=r["credit_account_id"],
        invoice=r["invoice"] or "",
        invoice_kind=r["invoice_kind"] or "",
    )
