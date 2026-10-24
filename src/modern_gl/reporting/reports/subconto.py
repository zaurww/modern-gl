"""ОСВ по субконто: balances of an account by its subconto values, as a tree."""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Sequence
from datetime import date

from modern_gl.application.books import COMMON, book_params
from modern_gl.domain.errors import ValidationError
from modern_gl.i18n import tr
from modern_gl.infrastructure.db import Connection, Row
from modern_gl.reporting.report_common import (
    _DOCS_CTE,
    SubcontoRow,
    Turnovers,
    _accounts,
    _find_account,
    _subtree,
)

# a path of a row (its values from the first subconto on, an e-qaimə number last) -> its
# opening, debit and credit
Key = tuple[int | str | None, ...]
Sums = dict[Key, list[int]]


def _name_subconto(
    conn: Connection, company_id: int, by_value: dict[int, Sums]
) -> dict[int, list[SubcontoRow]]:
    """The subconto rows of each account in tree order (a counterparty, its contracts)."""
    ids = {v for sums in by_value.values() for path in sums for v in path}
    names = _value_names(conn, company_id, ids)
    return {
        account_id: _subconto_tree(sums, {}, names, max(map(len, sums), default=0))
        for account_id, sums in by_value.items()
    }


def subconto_balance(
    conn: Connection,
    company_id: int,
    account: int | str,
    date_from: date | str,
    date_to: date | str,
    layers: Sequence[str] = COMMON,
    position: int = 1,
    tag_id: int | None = None,
    levels: int = 1,
    invoices: bool = False,
) -> list[SubcontoRow]:
    """ОСВ по субконто: balances of one account split by the subconto at `position`.
    With `levels` > 1 each row is split further by the next subconto (a counterparty,
    under it its contracts): the rows come in tree order, `depth` tells the level and a
    row sums the rows under it. `invoices`: the last level split further by the e-qaimə
    of the posting lines (D110; "" — the lines without one). With `tag_id` only the
    elements of the first level with that tag («Связанная сторона», D64)."""
    positions = tuple(range(position, position + levels))
    if levels < 1 or not set(positions) <= {1, 2, 3}:
        raise ValidationError(tr("позиция субконто должна быть 1, 2 или 3"))
    params = book_params(conn, company_id, date_from, date_to, layers)
    accounts = _accounts(conn, company_id)
    acc = _find_account(accounts, account)
    for i in positions:
        if acc[f"sc{i}_kind_id"] is None:
            raise ValidationError(
                tr("у счёта {code} нет субконто {i}", code=acc["code"] or acc["name"], i=i)
            )
    params["accounts"] = json.dumps(_subtree(accounts, acc["id"]))
    params["tag"] = tag_id
    depth = levels + invoices
    keys = ", ".join(f"m.sc{n}" for n in range(depth))
    raw = conn.execute(
        f"""
        WITH {_DOCS_CTE},
        moves AS (
            SELECT docs.doc_date, {_sides("dt", positions, invoices)}, p.amount AS dt, 0 AS ct
            FROM postings p CROSS JOIN docs
            WHERE docs.id = p.document_id AND p.company_id = :company_id
              AND p.debit_account_id IN (SELECT value FROM json_each(:accounts))
            UNION ALL
            SELECT docs.doc_date, {_sides("ct", positions, invoices)}, 0, p.amount
            FROM postings p CROSS JOIN docs
            WHERE docs.id = p.document_id AND p.company_id = :company_id
              AND p.credit_account_id IN (SELECT value FROM json_each(:accounts))
        )
        SELECT {keys},
               SUM(CASE WHEN m.doc_date <  :date_from THEN m.dt - m.ct ELSE 0 END) AS opening,
               SUM(CASE WHEN m.doc_date >= :date_from THEN m.dt ELSE 0 END)        AS dt,
               SUM(CASE WHEN m.doc_date >= :date_from THEN m.ct ELSE 0 END)        AS ct
        FROM moves m
        WHERE :tag IS NULL OR m.sc0 IN (
            SELECT value_id FROM subconto_value_tags
            WHERE company_id = :company_id AND tag_id = :tag
        )
        GROUP BY {keys}
        """,
        params,
    ).fetchall()
    sums: Sums = defaultdict(lambda: [0, 0, 0])
    for r in raw:
        _add_up(sums, tuple(r[f"sc{n}"] for n in range(depth)), r)
    in_currency = _subconto_currency(conn, params, positions, invoices)
    names = _value_names(conn, company_id, {v for path in sums for v in path})
    return _subconto_tree(sums, in_currency, names, depth)


def _add_up(sums: Sums, path: Key, r: Row) -> None:
    for k in range(1, len(path) + 1):  # the row itself and every row above it
        total = sums[path[:k]]
        total[0] += r["opening"]
        total[1] += r["dt"]
        total[2] += r["ct"]


def _sides(side: str, positions: tuple[int, ...], invoices: bool = False) -> str:
    """The subconto columns of one side of a posting: p.dt_sc1 AS sc0, p.dt_sc2 AS sc1…;
    `invoices`: the e-qaimə of the line after them ("" — none)."""
    columns = [f"p.{side}_sc{i} AS sc{n}" for n, i in enumerate(positions)]
    if invoices:
        columns.append(f"COALESCE(p.invoice, '') AS sc{len(positions)}")
    return ", ".join(columns)


def _value_names(
    conn: Connection, company_id: int, ids: set[int | str | None]
) -> dict[int | None, str]:
    return {
        r["id"]: r["name"]
        for r in conn.execute(
            "SELECT id, name FROM subconto_values "
            "WHERE company_id = ? AND id IN (SELECT value FROM json_each(?))",
            (company_id, json.dumps(sorted(v for v in ids if isinstance(v, int)))),
        )
    }


def _subconto_tree(
    sums: Sums,
    in_currency: dict[Key, dict[str, int]],
    names: dict[int | None, str],
    levels: int,
) -> list[SubcontoRow]:
    """The rows in tree order: each value, then the values under it; «не указано» first,
    the rest by name (e-qaimə by number). A silent row (nothing at all) is left out with
    what is under it."""
    children: dict[Key, list[Key]] = defaultdict(list)
    for path in sums:
        children[path[:-1]].append(path)

    def title(value: int | str | None) -> str:
        if isinstance(value, str):  # an e-qaimə (D110)
            return value or tr("<без e-qaimə>")
        return names.get(value, "—") if value is not None else tr("<не указано>")

    def under(parent: Key) -> list[SubcontoRow]:
        paths = children[parent]
        paths.sort(key=lambda p: (p[-1] is not None and p[-1] != "", title(p[-1]).casefold()))
        result = []
        for path in paths:
            value = path[-1]
            row = SubcontoRow(name=title(value), depth=len(parent))
            if isinstance(value, str):
                row.path, row.invoice = _values(path[:-1]), value
            else:
                row.value_id, row.path = value, _values(path)
            row.add(Turnovers.from_net(*sums[path]))
            row.currency_closing = in_currency.get(path, {})
            if not row.is_zero() or row.currency_closing:
                result.append(row)
                if len(path) < levels:
                    result += under(path)
        return result

    return under(())


def _values(path: Key) -> tuple[int | None, ...]:
    """The subconto values of a path (an e-qaimə is the last of it only)."""
    return tuple(v for v in path if not isinstance(v, str))


def _subconto_currency(
    conn: Connection, params: dict, positions: tuple[int, ...], invoices: bool = False
) -> dict[Key, dict[str, int]]:
    """Net balance at the end in each currency, per subconto value and per each row above
    it (currency accounts: a foreign partner with invoices in USD and in EUR has both)."""
    depth = len(positions) + invoices
    keys = ", ".join(f"m.sc{n}" for n in range(depth))
    found: dict[Key, dict[str, int]] = defaultdict(dict)
    for r in conn.execute(
        f"""
        WITH {_DOCS_CTE},
        moves AS (
            SELECT {_sides("dt", positions, invoices)}, p.currency_id, p.currency_amount AS net
            FROM postings p CROSS JOIN docs
            JOIN accounts own ON own.id = p.debit_account_id
            WHERE docs.id = p.document_id AND p.company_id = :company_id
              AND p.debit_account_id IN (SELECT value FROM json_each(:accounts))
              AND own.currency <> 0 AND p.currency_id IS NOT NULL
            UNION ALL
            SELECT {_sides("ct", positions, invoices)}, p.currency_id, -p.currency_amount
            FROM postings p CROSS JOIN docs
            JOIN accounts own ON own.id = p.credit_account_id
            WHERE docs.id = p.document_id AND p.company_id = :company_id
              AND p.credit_account_id IN (SELECT value FROM json_each(:accounts))
              AND own.currency <> 0 AND p.currency_id IS NOT NULL
        )
        SELECT {keys}, c.code, SUM(m.net) AS net
        FROM moves m JOIN currencies c ON c.id = m.currency_id
        GROUP BY {keys}, c.code HAVING SUM(m.net) <> 0
        """,
        params,
    ):
        path = tuple(r[f"sc{n}"] for n in range(depth))
        for k in range(1, len(path) + 1):
            amounts = found[path[:k]]
            amounts[r["code"]] = amounts.get(r["code"], 0) + r["net"]
    return {path: {c: n for c, n in amounts.items() if n} for path, amounts in found.items()}
