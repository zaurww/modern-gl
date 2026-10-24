"""ОСВ: the trial balance by accounts, with their subconto and currencies."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from datetime import date

from modern_gl.domain.accounts import wrong_side
from modern_gl.infrastructure.db import Connection, Row
from modern_gl.reporting.report_common import (
    _DOCS_CTE,
    COMMON,
    CurrencyRow,
    Osv,
    OsvRow,
    Turnovers,
    _accounts,
    _params,
    fold_chart,
)
from modern_gl.reporting.reports.subconto import Sums, _add_up, _name_subconto


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
    """Opening balance and turnovers of each account per its subconto values (sc0…sc2)."""
    raw = conn.execute(
        f"""
        WITH {_DOCS_CTE},
        moves AS (
            SELECT docs.doc_date, p.debit_account_id AS account_id,
                   p.dt_sc1 AS sc0, p.dt_sc2 AS sc1, p.dt_sc3 AS sc2, p.amount AS dt, 0 AS ct
            FROM postings p CROSS JOIN docs
            WHERE docs.id = p.document_id AND p.company_id = :company_id
            UNION ALL
            SELECT docs.doc_date, p.credit_account_id, p.ct_sc1, p.ct_sc2, p.ct_sc3, 0, p.amount
            FROM postings p CROSS JOIN docs
            WHERE docs.id = p.document_id AND p.company_id = :company_id
        )
        SELECT account_id, sc0, sc1, sc2,
               SUM(CASE WHEN doc_date <  :date_from THEN dt - ct ELSE 0 END) AS opening,
               SUM(CASE WHEN doc_date >= :date_from THEN dt ELSE 0 END)      AS dt,
               SUM(CASE WHEN doc_date >= :date_from THEN ct ELSE 0 END)      AS ct
        FROM moves GROUP BY account_id, sc0, sc1, sc2
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
    dict[int, Sums],
]:
    """Each account's turnovers (expanded per first subconto for a two-sided account),
    whether its balance is on the wrong side, and its sums by every subconto it has (the
    rows of «Развернуть по субконто», D110)."""
    values: dict[int, Turnovers] = {}
    flags: dict[int, tuple[bool, bool]] = {}
    by_value: dict[int, Sums] = {}
    for account_id, parts in per_account.items():
        acc = accounts[account_id]
        levels = next((i - 1 for i in (1, 2, 3) if acc[f"sc{i}_kind_id"] is None), 3)
        sums: Sums = defaultdict(lambda: [0, 0, 0])
        for part in parts:
            _add_up(sums, tuple(part[f"sc{n}"] for n in range(levels)), part)
        if acc["two_sided"] and levels:
            t = Turnovers()
            for path, (opening, dt, ct) in sums.items():
                if len(path) == 1:
                    t.add(Turnovers.from_net(opening, dt, ct))
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
        if levels:
            by_value[account_id] = sums
    return values, flags, by_value


def _osv_rows(
    accounts: dict[int, Row],
    values: dict[int, Turnovers],
    flags: dict[int, tuple[bool, bool]],
) -> tuple[list[OsvRow], Turnovers]:
    """The rows in the order of the chart, groups summing their children; silent
    accounts (and their silent subtrees) are left out."""

    def make(acc: Row, depth: int) -> OsvRow:
        row = OsvRow(
            account_id=acc["id"],
            code=acc["code"] or "",
            name=acc["name"],
            depth=depth,
            is_group=bool(acc["is_group"]),
        )
        own = values.get(acc["id"])
        if own is not None:
            row.add(own)
            row.opening_wrong, row.closing_wrong = flags[acc["id"]]
        return row

    rows, tops = fold_chart(accounts, make, lambda row: not row.is_zero())
    total = Turnovers()
    for top in tops:
        total.add(top)
    return rows, total


def _currency_turnovers(conn: Connection, params: dict) -> dict[int, list[CurrencyRow]]:
    """Turnovers of currency accounts in each currency (only sides on a currency account)."""
    raw = conn.execute(
        f"""
        WITH {_DOCS_CTE},
        moves AS (
            SELECT docs.doc_date, p.debit_account_id AS account_id, p.currency_id,
                   p.currency_amount AS dt, 0 AS ct
            FROM postings p CROSS JOIN docs
            JOIN accounts a ON a.id = p.debit_account_id
            WHERE docs.id = p.document_id AND p.company_id = :company_id
              AND a.currency <> 0 AND p.currency_id IS NOT NULL
            UNION ALL
            SELECT docs.doc_date, p.credit_account_id, p.currency_id, 0, p.currency_amount
            FROM postings p CROSS JOIN docs
            JOIN accounts a ON a.id = p.credit_account_id
            WHERE docs.id = p.document_id AND p.company_id = :company_id
              AND a.currency <> 0 AND p.currency_id IS NOT NULL
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
