"""«Заполнить остатком»: the balance of an account on a day, one line per subconto set —
the lines a document takes to write it off or move it elsewhere (12 to expenses, 60 to
76…). A group account gives the lines of each of its accounts."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from modern_gl.application.books import COMMON, IFRS, TAX, docs_cte
from modern_gl.domain.dates import iso_date
from modern_gl.i18n import sort_key
from modern_gl.infrastructure.db import Connection

# the book a document of a layer sees: an adjustment stands on the common postings
BOOK_OF_LAYER = {"common": COMMON, "ifrs_adj": IFRS, "tax_adj": TAX}


@dataclass(frozen=True)
class BalanceLine:
    """What one subconto set of an account holds: `amount` > 0 — a debit balance,
    < 0 — a credit one; in a currency also its amount (same sign)."""

    account_id: int
    subconto: tuple[int | None, int | None, int | None]
    amount: int
    currency_id: int | None = None
    currency_amount: int | None = None
    quantity: int | None = None  # a counted account (D-new): how many are left, same sign


def balance_lines(
    conn: Connection,
    company_id: int,
    account_id: int,
    on_date: date | str,
    layers: Sequence[str] = COMMON,
    without_document: int | None = None,
) -> list[BalanceLine]:
    """The balance of the account (with its subaccounts) at the end of `on_date` in the
    book, by account, subconto and currency; nothing left — no line. `without_document`:
    the document being filled, which is not part of what it writes off."""
    params = {
        "company_id": company_id,
        "date_to": iso_date(on_date),
        "layers": json.dumps(list(layers)),
        "account": account_id,
        "skip": without_document,
    }
    rows = conn.execute(
        f"""
        WITH RECURSIVE tree(id) AS (
            SELECT id FROM accounts WHERE company_id = :company_id AND id = :account
            UNION ALL
            SELECT a.id FROM accounts a JOIN tree ON a.parent_id = tree.id
            WHERE a.company_id = :company_id
        ),
        {docs_cte()},
        moves AS (
            SELECT p.debit_account_id AS account_id, p.dt_sc1 AS sc1, p.dt_sc2 AS sc2,
                   p.dt_sc3 AS sc3, p.currency_id, p.amount, p.currency_amount, p.quantity
            FROM postings p JOIN docs ON docs.id = p.document_id
            WHERE p.company_id = :company_id
              AND p.debit_account_id IN (SELECT id FROM tree)
              AND (:skip IS NULL OR p.document_id <> :skip)
            UNION ALL
            SELECT p.credit_account_id, p.ct_sc1, p.ct_sc2, p.ct_sc3, p.currency_id,
                   -p.amount, -p.currency_amount, -p.quantity
            FROM postings p JOIN docs ON docs.id = p.document_id
            WHERE p.company_id = :company_id
              AND p.credit_account_id IN (SELECT id FROM tree)
              AND (:skip IS NULL OR p.document_id <> :skip)
        )
        SELECT m.account_id, m.sc1, m.sc2, m.sc3, m.currency_id,
               SUM(m.amount) AS amount, SUM(m.currency_amount) AS currency_amount,
               SUM(m.quantity) AS quantity
        FROM moves m
        GROUP BY m.account_id, m.sc1, m.sc2, m.sc3, m.currency_id
        """,
        params,
    ).fetchall()
    lines = [
        BalanceLine(
            r["account_id"],
            (r["sc1"], r["sc2"], r["sc3"]),
            r["amount"],
            r["currency_id"],
            r["currency_amount"] if r["currency_id"] is not None else None,
            r["quantity"] or None,
        )
        for r in rows
        if r["amount"] or (r["currency_id"] is not None and r["currency_amount"]) or r["quantity"]
    ]
    return sorted(lines, key=_order(conn, company_id, lines))


def _order(conn: Connection, company_id: int, lines: list[BalanceLine]):
    """By the account's code, then the subconto names as a list shows them."""
    ids = {v for ln in lines for v in ln.subconto if v is not None}
    names = {
        r["id"]: r["name"]
        for r in conn.execute(
            "SELECT id, name FROM subconto_values "
            "WHERE company_id = ? AND id IN (SELECT value FROM json_each(?))",
            (company_id, json.dumps(sorted(ids))),
        )
    }
    codes = {
        r["id"]: (r["code"] or "", r["name"])
        for r in conn.execute(
            "SELECT id, code, name FROM accounts WHERE company_id = ?", (company_id,)
        )
    }

    def key(ln: BalanceLine):
        code, name = codes.get(ln.account_id, ("", ""))
        subconto = [sort_key(names.get(v, "")) if v is not None else () for v in ln.subconto]
        return (code, sort_key(name), *subconto, ln.currency_id or 0)

    return key
