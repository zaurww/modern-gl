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
    fold_chart,
)

# a path of a row (its values from the first subconto on, an e-qaimə number last) -> its
# opening, debit and credit
Key = tuple[int | str | None, ...]
Sums = dict[Key, list[int]]


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
    params = _params(conn, company_id, date_from, date_to, layers)
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
    params = _params(conn, company_id, date_from, date_to, layers)
    accounts = _accounts(conn, company_id)
    params["accounts"] = json.dumps(_subtree(accounts, _find_account(accounts, account)["id"]))
    raw = _card_rows(conn, params, subconto, invoice)
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
            SELECT docs.doc_date, docs.number, docs.id AS document_id, docs.memo,
                   p.line_no, 0 AS side, p.credit_account_id AS corr_id, p.amount AS dt, 0 AS ct,
                   CASE WHEN own.currency <> 0 THEN p.currency_id END AS currency_id,
                   COALESCE(CASE WHEN own.currency <> 0 THEN p.currency_amount END, 0) AS cur_dt,
                   0 AS cur_ct, p.invoice, p.invoice_kind
            FROM postings p CROSS JOIN docs
            JOIN accounts own ON own.id = p.debit_account_id
            WHERE docs.id = p.document_id AND p.company_id = :company_id
              AND p.debit_account_id IN (SELECT value FROM json_each(:accounts))
              {_same_subconto("dt", subconto)}{one_invoice}
            UNION ALL
            SELECT docs.doc_date, docs.number, docs.id, docs.memo,
                   p.line_no, 1, p.debit_account_id, 0, p.amount,
                   CASE WHEN own.currency <> 0 THEN p.currency_id END,
                   0, COALESCE(CASE WHEN own.currency <> 0 THEN p.currency_amount END, 0),
                   p.invoice, p.invoice_kind
            FROM postings p CROSS JOIN docs
            JOIN accounts own ON own.id = p.credit_account_id
            WHERE docs.id = p.document_id AND p.company_id = :company_id
              AND p.credit_account_id IN (SELECT value FROM json_each(:accounts))
              {_same_subconto("ct", subconto)}{one_invoice}
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
