"""Анализ субконто (as in 1C 7.7, D122): the elements of one directory across every
account that carries it — a counterparty on 60, 62 and 76 at once; an order or a project
on the client's, the suppliers' and the revenue accounts. An element whose accounts all
close at zero is a closed case."""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Sequence
from datetime import date

from modern_gl.domain.errors import NotFoundError
from modern_gl.i18n import tr
from modern_gl.infrastructure.db import Connection, Row
from modern_gl.reporting.report_common import (
    _DOCS_CTE,
    COMMON,
    SubcontoAnalysisRow,
    Turnovers,
    _accounts,
    _params,
)

Key = tuple[int | None, int]  # (the element — None: the position left empty, the account)


def subconto_analysis(
    conn: Connection,
    company_id: int,
    kind_id: int,
    date_from: date | str,
    date_to: date | str,
    layers: Sequence[str] = COMMON,
    value_id: int | None = None,
    only_open: bool = False,
) -> list[SubcontoAnalysisRow]:
    """The elements of the directory `kind_id` (one of them with `value_id`), each with
    the accounts it moved on in the book: opening, turnovers and closing per account and
    summed for the element. `only_open`: the elements with a closing balance on a balance
    sheet account (a case settled with the client and the suppliers is closed, whatever
    stays on revenue and expenses). «<не указано>» first, then the elements by name;
    accounts in chart order."""
    params = _params(conn, company_id, date_from, date_to, layers)
    params["kind"], params["value"] = kind_id, value_id
    if (
        conn.execute(
            "SELECT id FROM subconto_kinds WHERE company_id = ? AND id = ?", (company_id, kind_id)
        ).fetchone()
        is None
    ):
        raise NotFoundError(tr("справочник не найден"))
    sums: dict[Key, list[int]] = defaultdict(lambda: [0, 0, 0])
    for r in conn.execute(
        f"""
        WITH {_DOCS_CTE},
        moves AS ({_moves("p.amount AS dt, 0 AS ct", "0, p.amount")})
        SELECT m.value_id, m.account_id,
               SUM(CASE WHEN m.doc_date <  :date_from THEN m.dt - m.ct ELSE 0 END) AS opening,
               SUM(CASE WHEN m.doc_date >= :date_from THEN m.dt ELSE 0 END)        AS dt,
               SUM(CASE WHEN m.doc_date >= :date_from THEN m.ct ELSE 0 END)        AS ct
        FROM moves m
        WHERE :value IS NULL OR m.value_id = :value
        GROUP BY m.value_id, m.account_id
        """,
        params,
    ):
        sums[r["value_id"], r["account_id"]] = [r["opening"], r["dt"], r["ct"]]
    accounts = _accounts(conn, company_id)
    names = _element_names(conn, company_id, {v for v, _ in sums})
    rows: list[SubcontoAnalysisRow] = []
    for value in sorted(
        {v for v, _ in sums}, key=lambda v: (v is not None, names.get(v, "").casefold())
    ):
        element = SubcontoAnalysisRow(value_id=value, name=names.get(value, "—"))
        under = [
            SubcontoAnalysisRow(
                value_id=value,
                name=accounts[a]["name"],
                depth=1,
                account_id=a,
                code=accounts[a]["code"] or "",
            )
            for a in accounts  # chart order
            if (value, a) in sums
        ]
        for row in under:
            row.add(Turnovers.from_net(*sums[value, row.account_id or 0]))
            element.add(row)
        if element.is_zero() or (only_open and not _open(under, accounts)):
            continue
        rows += [element, *(r for r in under if not r.is_zero())]
    _add_currency(conn, params, rows)
    return rows


def _open(under: list[SubcontoAnalysisRow], accounts: dict[int, Row]) -> bool:
    """Something is still owed or held: a closing balance on an account that is not revenue
    or expense."""
    return any(
        (row.closing_dt or row.closing_ct)
        and accounts[row.account_id or 0]["account_class"] not in ("revenue", "expense")
        for row in under
    )


def _moves(debit: str, credit: str) -> str:
    """Every posting side whose account has the directory at a position, with the element
    there: `debit` / `credit` — the amount columns of that side (dt, ct)."""
    branches = []
    for i in (1, 2, 3):
        for side, column, amounts in (
            ("debit", f"p.dt_sc{i}", debit),
            ("credit", f"p.ct_sc{i}", credit),
        ):
            branches.append(f"""
            SELECT docs.doc_date, {column} AS value_id, p.{side}_account_id AS account_id,
                   p.currency_id, p.currency_amount, {amounts}
            FROM postings p CROSS JOIN docs
            JOIN accounts a ON a.id = p.{side}_account_id
            WHERE docs.id = p.document_id AND p.company_id = :company_id
              AND a.sc{i}_kind_id = :kind""")
    return "\n            UNION ALL".join(branches)


def _element_names(conn: Connection, company_id: int, ids: set[int | None]) -> dict:
    """An element's name; one that belongs to another (a contract) — with its owner's."""
    names: dict[int | None, str] = {None: tr("<не указано>")}
    owners: dict[int, int] = {}
    for r in conn.execute(
        "SELECT id, name, owner_id FROM subconto_values "
        "WHERE company_id = ? AND id IN (SELECT value FROM json_each(?))",
        (company_id, json.dumps(sorted(v for v in ids if v is not None))),
    ):
        names[r["id"]] = r["name"]
        if r["owner_id"] is not None:
            owners[r["id"]] = r["owner_id"]
    if owners:
        owner_names = _element_names(conn, company_id, set(owners.values()))
        for value, owner in owners.items():
            names[value] = f"{names[value]} ({owner_names[owner]})"
    return names


def _add_currency(conn: Connection, params: dict, rows: list[SubcontoAnalysisRow]) -> None:
    """Net balance at the end in each currency on the currency accounts, per account row
    and summed in its element."""
    if not rows:
        return
    found: dict[Key, dict[str, int]] = defaultdict(dict)
    for r in conn.execute(
        f"""
        WITH {_DOCS_CTE},
        moves AS ({_moves("p.currency_amount AS net, 0 AS ct", "-p.currency_amount, 0")})
        SELECT m.value_id, m.account_id, c.code, SUM(m.net) AS net
        FROM moves m
        JOIN accounts own ON own.id = m.account_id
        JOIN currencies c ON c.id = m.currency_id
        WHERE (:value IS NULL OR m.value_id = :value)
          AND own.currency <> 0 AND m.currency_id IS NOT NULL
        GROUP BY m.value_id, m.account_id, c.code HAVING SUM(m.net) <> 0
        """,
        params,
    ):
        found[r["value_id"], r["account_id"]][r["code"]] = r["net"]
    element: SubcontoAnalysisRow | None = None
    for row in rows:
        if row.depth == 0:
            element = row
            continue
        row.currency_closing = found.get((row.value_id, row.account_id or 0), {})
        if element is not None:
            for code, net in row.currency_closing.items():
                total = element.currency_closing.get(code, 0) + net
                element.currency_closing[code] = total
    for row in rows:
        row.currency_closing = {c: n for c, n in row.currency_closing.items() if n}
