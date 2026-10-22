"""Read-side reports: ОСВ, ОСВ по субконто, карточка счёта, анализ счёта.

Aggregation happens in SQL; Python only folds the (small) account tree.
A book is a list of layer codes: ("common",), ("common", "ifrs_adj"), ("common", "tax_adj").
All amounts are int minor units.
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Sequence
from datetime import date

from modern_gl.domain.accounts import wrong_side
from modern_gl.domain.errors import ValidationError
from modern_gl.i18n import tr
from modern_gl.infrastructure.db import Connection, Row
from modern_gl.reporting.report_common import (
    _DOCS_CTE,
    COMMON,
    IFRS,
    TAX,
    AccountCard,
    CardLine,
    CorrRow,
    CurrencyRow,
    Osv,
    OsvRow,
    SubcontoRow,
    Turnovers,
    _accounts,
    _find_account,
    _params,
    _subtree,
)


def trial_balance(
    conn: Connection,
    company_id: int,
    date_from: date | str,
    date_to: date | str,
    layers: Sequence[str] = COMMON,
) -> Osv:
    """Оборотно-сальдовая ведомость.

    Active-passive accounts with subconto get an expanded balance (развёрнутое сальдо):
    debit and credit balances are netted per first subconto value, not across them,
    so receivables and payables of different counterparties do not cancel out.
    Group rows sum their children's columns.
    """
    params = _params(conn, company_id, date_from, date_to, layers)
    accounts = _accounts(conn, company_id)
    values, flags, by_value = _account_turnovers(accounts, _moves_by_account(conn, params))
    rows, total = _osv_rows(accounts, values, flags)
    return Osv(
        rows=rows,
        total=total,
        subconto=_name_subconto(conn, company_id, by_value),
        currency=_currency_turnovers(conn, params),
    )


def _moves_by_account(conn: Connection, params: dict) -> dict[int, list[Row]]:
    """Opening balance and turnovers of each account per its first subconto value."""
    raw = conn.execute(
        f"""
        WITH {_DOCS_CTE},
        moves AS (
            SELECT docs.doc_date, p.debit_account_id AS account_id, p.dt_sc1 AS sc,
                   p.amount AS dt, 0 AS ct
            FROM postings p JOIN docs ON docs.id = p.document_id
            UNION ALL
            SELECT docs.doc_date, p.credit_account_id, p.ct_sc1, 0, p.amount
            FROM postings p JOIN docs ON docs.id = p.document_id
        )
        SELECT account_id, sc,
               SUM(CASE WHEN doc_date <  :date_from THEN dt - ct ELSE 0 END) AS opening,
               SUM(CASE WHEN doc_date >= :date_from THEN dt ELSE 0 END)      AS dt,
               SUM(CASE WHEN doc_date >= :date_from THEN ct ELSE 0 END)      AS ct
        FROM moves GROUP BY account_id, sc
        """,
        params,
    ).fetchall()
    per_account: dict[int, list[Row]] = defaultdict(list)
    for r in raw:
        per_account[r["account_id"]].append(r)
    return per_account


def _account_turnovers(
    accounts: dict[int, Row], per_account: dict[int, list[Row]]
) -> tuple[
    dict[int, Turnovers],
    dict[int, tuple[bool, bool]],
    dict[int, list[tuple[int | None, Turnovers]]],
]:
    """Each account's turnovers (expanded per first subconto for a two-sided account),
    whether its balance is on the wrong side, and its parts by first subconto."""
    values: dict[int, Turnovers] = {}
    flags: dict[int, tuple[bool, bool]] = {}
    by_value: dict[int, list[tuple[int | None, Turnovers]]] = {}
    for account_id, parts in per_account.items():
        acc = accounts[account_id]
        if acc["two_sided"] and acc["sc1_kind_id"] is not None:
            t = Turnovers()
            for part in parts:
                t.add(Turnovers.from_net(part["opening"], part["dt"], part["ct"]))
        else:
            t = Turnovers.from_net(
                sum(p["opening"] for p in parts),
                sum(p["dt"] for p in parts),
                sum(p["ct"] for p in parts),
            )
        values[account_id] = t
        check = (acc["account_class"], bool(acc["contra"]), bool(acc["two_sided"]))
        flags[account_id] = (
            wrong_side(*check, t.opening_dt - t.opening_ct),
            wrong_side(*check, t.closing_dt - t.closing_ct),
        )
        if acc["sc1_kind_id"] is not None:
            by_value[account_id] = [
                (part["sc"], Turnovers.from_net(part["opening"], part["dt"], part["ct"]))
                for part in parts
            ]
    return values, flags, by_value


def _osv_rows(
    accounts: dict[int, Row],
    values: dict[int, Turnovers],
    flags: dict[int, tuple[bool, bool]],
) -> tuple[list[OsvRow], Turnovers]:
    """The rows in the order of the chart, groups summing their children; silent
    accounts (and their silent subtrees) are left out."""
    children: dict[int | None, list[int]] = defaultdict(list)
    for a in accounts.values():  # already ordered by code
        children[a["parent_id"]].append(a["id"])

    rows: list[OsvRow] = []
    total = Turnovers()

    def visit(account_id: int, depth: int) -> Turnovers:
        acc = accounts[account_id]
        row = OsvRow(
            account_id=account_id,
            code=acc["code"] or "",
            name=acc["name"],
            depth=depth,
            is_group=bool(acc["is_group"]),
        )
        position = len(rows)
        rows.append(row)
        own = values.get(account_id)
        if own is not None:
            row.add(own)
            row.opening_wrong, row.closing_wrong = flags[account_id]
        for child in children[account_id]:
            row.add(visit(child, depth + 1))
        if row.is_zero():
            del rows[position:]  # drop silent accounts (and their silent subtree)
        return row

    for top in children[None]:
        total.add(visit(top, 0))
    return rows, total


def _currency_turnovers(conn: Connection, params: dict) -> dict[int, list[CurrencyRow]]:
    """Turnovers of currency accounts in each currency (only sides on a currency account)."""
    raw = conn.execute(
        f"""
        WITH {_DOCS_CTE},
        moves AS (
            SELECT docs.doc_date, p.debit_account_id AS account_id, p.currency_id,
                   p.currency_amount AS dt, 0 AS ct
            FROM postings p JOIN docs ON docs.id = p.document_id
            JOIN accounts a ON a.id = p.debit_account_id
            WHERE a.currency <> 0 AND p.currency_id IS NOT NULL
            UNION ALL
            SELECT docs.doc_date, p.credit_account_id, p.currency_id, 0, p.currency_amount
            FROM postings p JOIN docs ON docs.id = p.document_id
            JOIN accounts a ON a.id = p.credit_account_id
            WHERE a.currency <> 0 AND p.currency_id IS NOT NULL
        )
        SELECT m.account_id, m.currency_id, c.code,
               SUM(CASE WHEN doc_date <  :date_from THEN dt - ct ELSE 0 END) AS opening,
               SUM(CASE WHEN doc_date >= :date_from THEN dt ELSE 0 END)      AS dt,
               SUM(CASE WHEN doc_date >= :date_from THEN ct ELSE 0 END)      AS ct
        FROM moves m JOIN currencies c ON c.id = m.currency_id
        GROUP BY m.account_id, m.currency_id ORDER BY c.code
        """,
        params,
    ).fetchall()
    result: dict[int, list[CurrencyRow]] = defaultdict(list)
    for r in raw:
        row = CurrencyRow(currency_id=r["currency_id"], code=r["code"])
        row.add(Turnovers.from_net(r["opening"], r["dt"], r["ct"]))
        if not row.is_zero():
            result[r["account_id"]].append(row)
    return dict(result)


def _name_subconto(
    conn: Connection,
    company_id: int,
    by_value: dict[int, list[tuple[int | None, Turnovers]]],
) -> dict[int, list[SubcontoRow]]:
    ids = {v for parts in by_value.values() for v, _ in parts if v is not None}
    names = {
        r["id"]: r["name"]
        for r in conn.execute(
            "SELECT id, name FROM subconto_values "
            "WHERE company_id = ? AND id IN (SELECT value FROM json_each(?))",
            (company_id, json.dumps(sorted(ids))),
        )
    }
    result = {}
    for account_id, parts in by_value.items():
        rows = []
        for value_id, turnovers in parts:
            row = SubcontoRow(value_id=value_id, name=names.get(value_id, "—"))
            row.add(turnovers)
            if not row.is_zero():
                rows.append(row)
        result[account_id] = sorted(rows, key=lambda r: r.name.casefold())
    return result


def subconto_balance(
    conn: Connection,
    company_id: int,
    account: int | str,
    date_from: date | str,
    date_to: date | str,
    layers: Sequence[str] = COMMON,
    position: int = 1,
    tag_id: int | None = None,
) -> list[SubcontoRow]:
    """ОСВ по субконто: balances of one account split by the subconto at `position`.
    With `tag_id` only the elements with that tag («Связанная сторона», D64)."""
    if position not in (1, 2, 3):
        raise ValidationError(tr("позиция субконто должна быть 1, 2 или 3"))
    params = _params(conn, company_id, date_from, date_to, layers)
    accounts = _accounts(conn, company_id)
    acc = _find_account(accounts, account)
    if acc[f"sc{position}_kind_id"] is None:
        raise ValidationError(
            tr("у счёта {code} нет субконто {i}", code=acc["code"] or acc["name"], i=position)
        )
    params["accounts"] = json.dumps(_subtree(accounts, acc["id"]))
    params["tag"] = tag_id
    raw = conn.execute(
        f"""
        WITH {_DOCS_CTE},
        moves AS (
            SELECT docs.doc_date, p.dt_sc{position} AS sc, p.amount AS dt, 0 AS ct
            FROM postings p JOIN docs ON docs.id = p.document_id
            WHERE p.debit_account_id IN (SELECT value FROM json_each(:accounts))
            UNION ALL
            SELECT docs.doc_date, p.ct_sc{position}, 0, p.amount
            FROM postings p JOIN docs ON docs.id = p.document_id
            WHERE p.credit_account_id IN (SELECT value FROM json_each(:accounts))
        )
        SELECT m.sc, v.name,
               SUM(CASE WHEN m.doc_date <  :date_from THEN m.dt - m.ct ELSE 0 END) AS opening,
               SUM(CASE WHEN m.doc_date >= :date_from THEN m.dt ELSE 0 END)        AS dt,
               SUM(CASE WHEN m.doc_date >= :date_from THEN m.ct ELSE 0 END)        AS ct
        FROM moves m LEFT JOIN subconto_values v ON v.id = m.sc
        WHERE :tag IS NULL OR m.sc IN (
            SELECT value_id FROM subconto_value_tags
            WHERE company_id = :company_id AND tag_id = :tag
        )
        GROUP BY m.sc ORDER BY v.name
        """,
        params,
    ).fetchall()
    in_currency = _subconto_currency(conn, params, position)
    result = []
    for r in raw:
        row = SubcontoRow(value_id=r["sc"], name=r["name"] or tr("<не указано>"))
        row.add(Turnovers.from_net(r["opening"], r["dt"], r["ct"]))
        row.currency_closing = in_currency.get(r["sc"], {})
        if not row.is_zero() or row.currency_closing:
            result.append(row)
    return result


def _subconto_currency(
    conn: Connection, params: dict, position: int
) -> dict[int | None, dict[str, int]]:
    """Net balance at the end in each currency, per subconto value (currency accounts:
    a foreign partner with invoices in USD and in EUR has both)."""
    found: dict[int | None, dict[str, int]] = defaultdict(dict)
    for r in conn.execute(
        f"""
        WITH {_DOCS_CTE},
        moves AS (
            SELECT p.dt_sc{position} AS sc, p.currency_id, p.currency_amount AS net
            FROM postings p JOIN docs ON docs.id = p.document_id
            JOIN accounts own ON own.id = p.debit_account_id
            WHERE p.debit_account_id IN (SELECT value FROM json_each(:accounts))
              AND own.currency <> 0 AND p.currency_id IS NOT NULL
            UNION ALL
            SELECT p.ct_sc{position}, p.currency_id, -p.currency_amount
            FROM postings p JOIN docs ON docs.id = p.document_id
            JOIN accounts own ON own.id = p.credit_account_id
            WHERE p.credit_account_id IN (SELECT value FROM json_each(:accounts))
              AND own.currency <> 0 AND p.currency_id IS NOT NULL
        )
        SELECT m.sc, c.code, SUM(m.net) AS net
        FROM moves m JOIN currencies c ON c.id = m.currency_id
        GROUP BY m.sc, c.code HAVING SUM(m.net) <> 0
        """,
        params,
    ):
        found[r["sc"]][r["code"]] = r["net"]
    return found


def account_card(
    conn: Connection,
    company_id: int,
    account: int | str,
    date_from: date | str,
    date_to: date | str,
    layers: Sequence[str] = COMMON,
) -> AccountCard:
    """Карточка счёта: opening balance, each movement with corr account, running balance.

    For a group account, movements of all its subaccounts are included.
    """
    params = _params(conn, company_id, date_from, date_to, layers)
    accounts = _accounts(conn, company_id)
    params["accounts"] = json.dumps(_subtree(accounts, _find_account(accounts, account)["id"]))
    raw = _card_rows(conn, params)
    opening = 0
    card = AccountCard(opening=0)
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
            continue
        card.lines.append(_card_line(r))
    card.opening = opening
    return card


def _card_rows(conn: Connection, params: dict) -> list[Row]:
    """Each posting line of the accounts, either side, with its corr account and the
    running balance; currency amounts only for currency accounts."""
    return conn.execute(
        f"""
        WITH {_DOCS_CTE},
        lines AS (
            SELECT docs.doc_date, docs.number, docs.id AS document_id, docs.memo,
                   p.line_no, 0 AS side, p.credit_account_id AS corr_id, p.amount AS dt, 0 AS ct,
                   CASE WHEN own.currency <> 0 THEN p.currency_id END AS currency_id,
                   COALESCE(CASE WHEN own.currency <> 0 THEN p.currency_amount END, 0) AS cur_dt,
                   0 AS cur_ct, p.invoice, p.invoice_kind
            FROM postings p JOIN docs ON docs.id = p.document_id
            JOIN accounts own ON own.id = p.debit_account_id
            WHERE p.debit_account_id IN (SELECT value FROM json_each(:accounts))
            UNION ALL
            SELECT docs.doc_date, docs.number, docs.id, docs.memo,
                   p.line_no, 1, p.debit_account_id, 0, p.amount,
                   CASE WHEN own.currency <> 0 THEN p.currency_id END,
                   0, COALESCE(CASE WHEN own.currency <> 0 THEN p.currency_amount END, 0),
                   p.invoice, p.invoice_kind
            FROM postings p JOIN docs ON docs.id = p.document_id
            JOIN accounts own ON own.id = p.credit_account_id
            WHERE p.credit_account_id IN (SELECT value FROM json_each(:accounts))
        ),
        running AS (
            SELECT *, SUM(dt - ct) OVER (
                ORDER BY doc_date, number, line_no, side ROWS UNBOUNDED PRECEDING
            ) AS balance
            FROM lines
        )
        SELECT r.*, COALESCE(a.code, a.name) AS corr_code, c.code AS currency
        FROM running r JOIN accounts a ON a.id = r.corr_id
        LEFT JOIN currencies c ON c.id = r.currency_id
        ORDER BY r.doc_date, r.number, r.line_no, r.side
        """,
        params,
    ).fetchall()


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
    params = _params(conn, company_id, date_from, date_to, layers)
    accounts = _accounts(conn, company_id)
    params["accounts"] = json.dumps(_subtree(accounts, _find_account(accounts, account)["id"]))
    raw = conn.execute(
        f"""
        WITH {_DOCS_CTE},
        moves AS (
            SELECT p.credit_account_id AS corr_id, p.amount AS dt, 0 AS ct
            FROM postings p JOIN docs ON docs.id = p.document_id
            WHERE docs.doc_date >= :date_from
              AND p.debit_account_id IN (SELECT value FROM json_each(:accounts))
            UNION ALL
            SELECT p.debit_account_id, 0, p.amount
            FROM postings p JOIN docs ON docs.id = p.document_id
            WHERE docs.doc_date >= :date_from
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


__all__ = [
    "COMMON",
    "IFRS",
    "TAX",
    "AccountCard",
    "CardLine",
    "CorrRow",
    "CurrencyRow",
    "Osv",
    "OsvRow",
    "SubcontoRow",
    "Turnovers",
    "account_analysis",
    "account_card",
    "subconto_balance",
    "trial_balance",
]
