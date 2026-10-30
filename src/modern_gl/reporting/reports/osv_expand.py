"""Развороты ОСВ по месту (D-new-interactive-osv): the figures of one account — or of one
row under it — split by a subconto, by the corresponding accounts or by the months of
the period, as «Интерактивная ОСВ» for 1C 7.7 does it.

A row under an account is named by its steps: `(("sc1", 7), ("corr", 12))` — the
counterparty 7, its postings with the account 12. Each step narrows the moves (a subconto
value — only that value, a corr account — only the postings with it, a month — only that
month, the balance at its start) and the next kind splits what is left.
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from modern_gl.application.books import COMMON, book_params
from modern_gl.domain.dates import month_days, month_name
from modern_gl.domain.errors import ValidationError
from modern_gl.i18n import tr
from modern_gl.infrastructure.db import Connection, Row
from modern_gl.reporting.report_common import (
    _DOCS_CTE,
    Turnovers,
    _accounts,
    _subtree,
)
from modern_gl.reporting.reports.subconto import _value_names

# a kind of a split: a subconto position, the corresponding accounts, the months
SUBCONTO_KINDS = ("sc1", "sc2", "sc3")
CORR, MONTH = "corr", "month"
KINDS = (*SUBCONTO_KINDS, CORR, MONTH)

# (kind, value): a subconto value id (None — «не указано»), a corr account id, "YYYY-MM"
Step = tuple[str, int | str | None]


@dataclass
class ExpandRow(Turnovers):
    """One row of a split: the value it stands for and its name."""

    kind: str = ""
    value: int | str | None = None
    name: str = ""
    code: str = ""  # a corr account's code


def expand_rows(
    conn: Connection,
    company_id: int,
    account: int,
    date_from: date | str,
    date_to: date | str,
    layers: Sequence[str] = COMMON,
    steps: Sequence[Step] = (),
    by: str = "sc1",
) -> list[ExpandRow]:
    """The rows under one account (or under the row of its `steps`) split `by` a kind."""
    return expand_many(conn, company_id, [account], date_from, date_to, layers, steps, by)[account]


def expand_many(
    conn: Connection,
    company_id: int,
    accounts: Sequence[int],
    date_from: date | str,
    date_to: date | str,
    layers: Sequence[str] = COMMON,
    steps: Sequence[Step] = (),
    by: str = "sc1",
) -> dict[int, list[ExpandRow]]:
    """The same for several accounts in one query: account id -> its rows. A group
    account sums the rows of its subaccounts (a value's figures across them).
    Rows of a corr account split carry turnovers only: a balance «with an account» means
    nothing. A silent row (nothing at all) is left out."""
    if by not in KINDS:
        raise ValidationError(tr("неизвестный вид разворота: {kind}", kind=by))
    params = book_params(conn, company_id, date_from, date_to, layers)
    _narrow_to_months(params, steps)
    chart = _accounts(conn, company_id)
    subtrees = {a: _subtree(chart, a) for a in accounts}
    params["accounts"] = json.dumps(sorted({a for tree in subtrees.values() for a in tree}))
    raw = _sums(conn, params, steps, by)
    turnovers_only = by == CORR or any(kind == CORR for kind, _ in steps)
    names = _names(conn, company_id, chart, raw, by)
    result: dict[int, list[ExpandRow]] = {}
    for account, tree in subtrees.items():
        sums: dict[int | str | None, list[int]] = defaultdict(lambda: [0, 0, 0])
        for r in raw:
            if r["account_id"] in tree:
                total = sums[r["value"]]
                total[0] += r["opening"]
                total[1] += r["dt"]
                total[2] += r["ct"]
        if by == MONTH:
            rows = _month_rows(sums, params["date_from"], params["date_to"])
        else:
            rows = [_row(by, value, names, *figures) for value, figures in sums.items()]
            rows.sort(key=lambda r: (r.value is not None, r.code, r.name.casefold()))
        if turnovers_only:
            for row in rows:
                row.opening_dt = row.opening_ct = row.closing_dt = row.closing_ct = 0
        result[account] = [r for r in rows if not r.is_zero()]
    return result


def _narrow_to_months(params: dict, steps: Sequence[Step]) -> None:
    """A month step: the period is that month (cut to the report's own period)."""
    for kind, value in steps:
        if kind == MONTH:
            first, last = month_days(int(str(value)[:4]), int(str(value)[5:7]))
            params["date_from"] = max(params["date_from"], first.isoformat())
            params["date_to"] = min(params["date_to"], last.isoformat())
            if params["date_from"] > params["date_to"]:
                raise ValidationError(tr("месяц {month} вне периода", month=value))


def _sums(conn: Connection, params: dict, steps: Sequence[Step], by: str) -> list[Row]:
    """Opening (before the period) and turnovers per account and per value of `by`,
    among the moves the steps leave."""
    where = []
    for n, (kind, value) in enumerate(steps):
        if kind in SUBCONTO_KINDS:
            if value is None:
                where.append(f"AND m.{kind} IS NULL")
            else:
                where.append(f"AND m.{kind} = :step{n}")
                params[f"step{n}"] = value
        elif kind == CORR:
            where.append(f"AND m.corr = :step{n}")
            params[f"step{n}"] = value
    key = {CORR: "m.corr", MONTH: "substr(m.doc_date, 1, 7)"}.get(by, f"m.{by}")
    return conn.execute(
        f"""
        WITH {_DOCS_CTE},
        moves AS (
            SELECT docs.doc_date, p.debit_account_id AS account_id,
                   p.dt_sc1 AS sc1, p.dt_sc2 AS sc2, p.dt_sc3 AS sc3,
                   p.credit_account_id AS corr, p.amount AS dt, 0 AS ct
            FROM postings p CROSS JOIN docs
            WHERE docs.id = p.document_id AND p.company_id = :company_id
              AND p.debit_account_id IN (SELECT value FROM json_each(:accounts))
            UNION ALL
            SELECT docs.doc_date, p.credit_account_id, p.ct_sc1, p.ct_sc2, p.ct_sc3,
                   p.debit_account_id, 0, p.amount
            FROM postings p CROSS JOIN docs
            WHERE docs.id = p.document_id AND p.company_id = :company_id
              AND p.credit_account_id IN (SELECT value FROM json_each(:accounts))
        )
        SELECT m.account_id, {key} AS value,
               SUM(CASE WHEN m.doc_date <  :date_from THEN m.dt - m.ct ELSE 0 END) AS opening,
               SUM(CASE WHEN m.doc_date >= :date_from THEN m.dt ELSE 0 END)        AS dt,
               SUM(CASE WHEN m.doc_date >= :date_from THEN m.ct ELSE 0 END)        AS ct
        FROM moves m
        WHERE 1 = 1 {" ".join(where)}
        GROUP BY m.account_id, {key}
        """,
        params,
    ).fetchall()


def _names(
    conn: Connection, company_id: int, chart: dict[int, Row], raw: list[Row], by: str
) -> dict[int | str | None, tuple[str, str]]:
    """value -> (code, name) of what a row stands for."""
    if by == CORR:
        return {
            a["id"]: (a["code"] or "", a["name"])
            for a in chart.values()
            if a["id"] in {r["value"] for r in raw}
        }
    if by == MONTH:
        return {}
    values = _value_names(conn, company_id, {r["value"] for r in raw})
    return {v: ("", name) for v, name in values.items()}


def _row(
    by: str,
    value: int | str | None,
    names: dict[int | str | None, tuple[str, str]],
    opening: int,
    dt: int,
    ct: int,
) -> ExpandRow:
    code, name = names.get(value, ("", "—"))
    if by in SUBCONTO_KINDS and value is None:
        name = tr("<не указано>")
    row = ExpandRow(kind=by, value=value, name=name, code=code)
    row.add(Turnovers.from_net(opening, dt, ct))
    return row


def _month_rows(
    sums: dict[int | str | None, list[int]], date_from: str, date_to: str
) -> list[ExpandRow]:
    """Every month of the period with the balance running through it: the opening of a
    month is the balance at its start, and what moved before the period adds up."""
    opening = sum(figures[0] for figures in sums.values())
    rows = []
    year, month = int(date_from[:4]), int(date_from[5:7])
    while f"{year:04d}-{month:02d}" <= date_to[:7]:
        code = f"{year:04d}-{month:02d}"
        _, dt, ct = sums.get(code, [0, 0, 0])
        row = ExpandRow(kind=MONTH, value=code, name=month_name(code))
        row.add(Turnovers.from_net(opening, dt, ct))
        rows.append(row)
        opening += dt - ct
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return rows
