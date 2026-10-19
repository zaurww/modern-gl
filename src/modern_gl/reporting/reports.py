"""Read-side reports: ОСВ, ОСВ по субконто, карточка счёта, анализ счёта.

Aggregation happens in SQL; Python only folds the (small) account tree.
A book is a list of layer codes: ("common",), ("common", "ifrs_adj"), ("common", "tax_adj").
All amounts are int minor units.
"""

from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date

from modern_gl.domain.dates import iso_date
from modern_gl.domain.errors import NotFoundError, ValidationError
from modern_gl.i18n import tr

COMMON = ("common",)
IFRS = ("common", "ifrs_adj")
TAX = ("common", "tax_adj")

# Posted documents of the requested book up to :date_to.
_DOCS_CTE = """
docs AS (
    SELECT d.id, d.doc_date, d.number, d.memo
    FROM documents d
    JOIN layers l ON l.id = d.layer_id
    WHERE d.company_id = :company_id
      AND d.status = 'posted'
      AND d.doc_date <= :date_to
      AND l.code IN (SELECT value FROM json_each(:layers))
)"""


@dataclass
class Turnovers:
    opening_dt: int = 0
    opening_ct: int = 0
    turnover_dt: int = 0
    turnover_ct: int = 0
    closing_dt: int = 0
    closing_ct: int = 0

    def add(self, other: Turnovers) -> None:
        self.opening_dt += other.opening_dt
        self.opening_ct += other.opening_ct
        self.turnover_dt += other.turnover_dt
        self.turnover_ct += other.turnover_ct
        self.closing_dt += other.closing_dt
        self.closing_ct += other.closing_ct

    def is_zero(self) -> bool:
        return not any(
            (
                self.opening_dt,
                self.opening_ct,
                self.turnover_dt,
                self.turnover_ct,
                self.closing_dt,
                self.closing_ct,
            )
        )

    @classmethod
    def from_net(cls, opening: int, dt: int, ct: int) -> Turnovers:
        t = cls(turnover_dt=dt, turnover_ct=ct)
        t.opening_dt, t.opening_ct = _split(opening)
        t.closing_dt, t.closing_ct = _split(opening + dt - ct)
        return t


@dataclass
class OsvRow(Turnovers):
    account_id: int = 0
    code: str = ""
    name: str = ""
    depth: int = 0
    is_group: bool = False


@dataclass
class Osv:
    rows: list[OsvRow]
    total: Turnovers
    # account id -> balances split by its first subconto (only accounts that have one)
    subconto: dict[int, list[SubcontoRow]] = field(default_factory=dict)


@dataclass
class SubcontoRow(Turnovers):
    value_id: int | None = None
    name: str = ""


@dataclass
class CardLine:
    doc_date: str
    number: int
    document_id: int
    memo: str
    corr_code: str
    debit: int
    credit: int
    balance: int  # running net balance (Dt - Ct) after this line


@dataclass
class AccountCard:
    opening: int
    lines: list[CardLine] = field(default_factory=list)

    @property
    def closing(self) -> int:
        return self.lines[-1].balance if self.lines else self.opening


@dataclass
class CorrRow:
    corr_code: str
    corr_name: str
    debit: int  # account debited, corr account credited
    credit: int  # account credited, corr account debited


def _split(net: int) -> tuple[int, int]:
    return (net, 0) if net >= 0 else (0, -net)


def _params(conn, company_id, date_from, date_to, layers) -> dict:
    date_from, date_to = iso_date(date_from), iso_date(date_to)
    if date_from > date_to:
        raise ValidationError(tr("начало периода позже конца"))
    known = {
        r["code"]
        for r in conn.execute("SELECT code FROM layers WHERE company_id = ?", (company_id,))
    }
    unknown = set(layers) - known
    if unknown:
        raise NotFoundError(tr("неизвестные слои: {layers}", layers=sorted(unknown)))
    return {
        "company_id": company_id,
        "date_from": date_from,
        "date_to": date_to,
        "layers": json.dumps(list(layers)),
    }


def _accounts(conn: sqlite3.Connection, company_id: int) -> dict[int, sqlite3.Row]:
    return {
        r["id"]: r
        for r in conn.execute(
            "SELECT * FROM accounts WHERE company_id = ? ORDER BY code", (company_id,)
        )
    }


def _subtree(accounts: dict[int, sqlite3.Row], root_id: int) -> list[int]:
    children = defaultdict(list)
    for a in accounts.values():
        children[a["parent_id"]].append(a["id"])
    result, stack = [], [root_id]
    while stack:
        current = stack.pop()
        result.append(current)
        stack.extend(children[current])
    return result


def _find_account(accounts: dict[int, sqlite3.Row], code: str) -> sqlite3.Row:
    for a in accounts.values():
        if a["code"] == code:
            return a
    raise NotFoundError(tr("счёт {code} не найден", code=code))


def trial_balance(
    conn: sqlite3.Connection,
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

    accounts = _accounts(conn, company_id)
    per_account: dict[int, list[sqlite3.Row]] = defaultdict(list)
    for r in raw:
        per_account[r["account_id"]].append(r)

    values: dict[int, Turnovers] = {}
    by_value: dict[int, list[tuple[int | None, Turnovers]]] = {}
    for account_id, parts in per_account.items():
        acc = accounts[account_id]
        if acc["kind"] == "AP" and acc["sc1_kind_id"] is not None:
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
        if acc["sc1_kind_id"] is not None:
            by_value[account_id] = [
                (part["sc"], Turnovers.from_net(part["opening"], part["dt"], part["ct"]))
                for part in parts
            ]

    children: dict[int | None, list[int]] = defaultdict(list)
    for a in accounts.values():  # already ordered by code
        children[a["parent_id"]].append(a["id"])

    rows: list[OsvRow] = []
    total = Turnovers()

    def visit(account_id: int, depth: int) -> Turnovers:
        acc = accounts[account_id]
        row = OsvRow(
            account_id=account_id,
            code=acc["code"],
            name=acc["name"],
            depth=depth,
            is_group=bool(acc["is_group"]),
        )
        position = len(rows)
        rows.append(row)
        own = values.get(account_id)
        if own is not None:
            row.add(own)
        for child in children[account_id]:
            row.add(visit(child, depth + 1))
        if row.is_zero():
            del rows[position:]  # drop silent accounts (and their silent subtree)
        return row

    for top in children[None]:
        total.add(visit(top, 0))
    return Osv(rows=rows, total=total, subconto=_name_subconto(conn, by_value))


def _name_subconto(
    conn: sqlite3.Connection, by_value: dict[int, list[tuple[int | None, Turnovers]]]
) -> dict[int, list[SubcontoRow]]:
    ids = {v for parts in by_value.values() for v, _ in parts if v is not None}
    names = {
        r["id"]: r["name"]
        for r in conn.execute(
            "SELECT id, name FROM subconto_values WHERE id IN (SELECT value FROM json_each(?))",
            (json.dumps(sorted(ids)),),
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
    conn: sqlite3.Connection,
    company_id: int,
    account_code: str,
    date_from: date | str,
    date_to: date | str,
    layers: Sequence[str] = COMMON,
    position: int = 1,
) -> list[SubcontoRow]:
    """ОСВ по субконто: balances of one account split by the subconto at `position`."""
    if position not in (1, 2, 3):
        raise ValidationError(tr("позиция субконто должна быть 1, 2 или 3"))
    params = _params(conn, company_id, date_from, date_to, layers)
    accounts = _accounts(conn, company_id)
    acc = _find_account(accounts, account_code)
    if acc[f"sc{position}_kind_id"] is None:
        raise ValidationError(tr("у счёта {code} нет субконто {i}", code=account_code, i=position))
    params["accounts"] = json.dumps(_subtree(accounts, acc["id"]))
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
        GROUP BY m.sc ORDER BY v.name
        """,
        params,
    ).fetchall()
    result = []
    for r in raw:
        row = SubcontoRow(value_id=r["sc"], name=r["name"] or "<не указано>")
        row.add(Turnovers.from_net(r["opening"], r["dt"], r["ct"]))
        if not row.is_zero():
            result.append(row)
    return result


def account_card(
    conn: sqlite3.Connection,
    company_id: int,
    account_code: str,
    date_from: date | str,
    date_to: date | str,
    layers: Sequence[str] = COMMON,
) -> AccountCard:
    """Карточка счёта: opening balance, each movement with corr account, running balance.

    For a group account, movements of all its subaccounts are included.
    """
    params = _params(conn, company_id, date_from, date_to, layers)
    accounts = _accounts(conn, company_id)
    params["accounts"] = json.dumps(_subtree(accounts, _find_account(accounts, account_code)["id"]))
    raw = conn.execute(
        f"""
        WITH {_DOCS_CTE},
        lines AS (
            SELECT docs.doc_date, docs.number, docs.id AS document_id, docs.memo,
                   p.line_no, 0 AS side, p.credit_account_id AS corr_id, p.amount AS dt, 0 AS ct
            FROM postings p JOIN docs ON docs.id = p.document_id
            WHERE p.debit_account_id IN (SELECT value FROM json_each(:accounts))
            UNION ALL
            SELECT docs.doc_date, docs.number, docs.id, docs.memo,
                   p.line_no, 1, p.debit_account_id, 0, p.amount
            FROM postings p JOIN docs ON docs.id = p.document_id
            WHERE p.credit_account_id IN (SELECT value FROM json_each(:accounts))
        ),
        running AS (
            SELECT *, SUM(dt - ct) OVER (
                ORDER BY doc_date, number, line_no, side ROWS UNBOUNDED PRECEDING
            ) AS balance
            FROM lines
        )
        SELECT r.*, a.code AS corr_code
        FROM running r JOIN accounts a ON a.id = r.corr_id
        ORDER BY r.doc_date, r.number, r.line_no, r.side
        """,
        params,
    ).fetchall()
    opening = 0
    card = AccountCard(opening=0)
    for r in raw:
        if r["doc_date"] < params["date_from"]:
            opening = r["balance"]
            continue
        card.lines.append(
            CardLine(
                doc_date=r["doc_date"],
                number=r["number"],
                document_id=r["document_id"],
                memo=r["memo"],
                corr_code=r["corr_code"],
                debit=r["dt"],
                credit=r["ct"],
                balance=r["balance"],
            )
        )
    card.opening = opening
    return card


def account_analysis(
    conn: sqlite3.Connection,
    company_id: int,
    account_code: str,
    date_from: date | str,
    date_to: date | str,
    layers: Sequence[str] = COMMON,
) -> list[CorrRow]:
    """Анализ счёта: period turnovers of the account broken down by corresponding account."""
    params = _params(conn, company_id, date_from, date_to, layers)
    accounts = _accounts(conn, company_id)
    params["accounts"] = json.dumps(_subtree(accounts, _find_account(accounts, account_code)["id"]))
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
        SELECT a.code, a.name, SUM(m.dt) AS dt, SUM(m.ct) AS ct
        FROM moves m JOIN accounts a ON a.id = m.corr_id
        GROUP BY a.id ORDER BY a.code
        """,
        params,
    ).fetchall()
    return [
        CorrRow(corr_code=r["code"], corr_name=r["name"], debit=r["dt"], credit=r["ct"])
        for r in raw
    ]
