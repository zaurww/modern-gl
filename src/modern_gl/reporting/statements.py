"""Финансовая отчётность (D99): the balance sheet on a day (the profit and loss — in
`profit_loss.py`), read from the accounts' types (D35) — whatever the codes of the chart. Level 2 of
the classification: a line per type, current and long-term apart (D89).

Amounts are minor units: assets and expenses as Dt − Ct, liabilities, equity and income
as Ct − Dt; in the profit and loss an expense is negative, so the lines simply add up.
A figure is `Amounts`, one per column of the statement (D107, `columns`)."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date

from modern_gl.application.books import AFTER, COMMON, book_params, docs_cte
from modern_gl.domain.accounts import ACCOUNT_TYPES, NONCURRENT_TYPES, TYPE_CLASS
from modern_gl.domain.dates import iso_date
from modern_gl.i18n import N_
from modern_gl.infrastructure.db import Connection
from modern_gl.reporting.columns import Amounts, total
from modern_gl.reporting.report_common import _accounts

UNTYPED = ""  # an account without a type: its own line, so it is seen and given one
# a debit balance of a counterparty on a liability account is an advance paid, a credit
# one on an asset account an advance received (развёрнутое сальдо, as in ОСВ)
FLIPPED = {"payable": "advance_paid", "receivable": "advance_received"}
# where income and expense are closed: such postings are not income or expense (CLOSING)
CLOSING_TYPES = ("profit_loss", "retained_earnings")
TYPES, ACCOUNTS, ITEMS = "types", "accounts", "items"  # how much a line shows under it


@dataclass
class Line:
    title: str  # Russian, for tr(): a type's name, or a caption of the statement
    amount: Amounts = field(default_factory=Amounts)  # a figure per column
    kind: str = "line"  # line | account | item | subtotal | total | heading
    account_type: str | None = None  # the type of a «line» (UNTYPED: none)
    # the detail under a line of the profit and loss (D102): an «account», an «item» of
    # it (its first subconto, None: not given); their titles are names, not for tr()
    account_id: int | None = None
    value_id: int | None = None
    # an item right under its line: the line's only account is not shown (D108)
    under_line: bool = False


@dataclass
class Statement:
    lines: list[Line] = field(default_factory=list)
    # balance sheet: assets − (liabilities + equity); profit and loss: 0
    unbalanced: Amounts = field(default_factory=Amounts)


def balance_sheet(
    conn: Connection,
    company_id: int,
    day: date | str,
    layers: tuple[str, ...] = COMMON,
    detail: str = TYPES,
    days: Sequence[date | str] | None = None,
) -> Statement:
    """Assets, liabilities and equity on the day; the profit not yet closed into equity
    (the balances of income and expense accounts) is a line of equity. `detail` ACCOUNTS:
    each line opens into its accounts (D102). `days`: a column per day (D107)."""
    balances = _balances(conn, company_id, [iso_date(x) for x in days or [day]], layers)
    by_type: dict[str, Amounts] = defaultdict(Amounts)
    for (key, _), net in balances.items():
        by_type[key] += net
    names = Names.read(conn, company_id) if detail != TYPES else None
    profit = -total(v for t, v in by_type.items() if _class(t) in ("revenue", "expense"))
    lines: list[Line] = [Line("Активы", kind="heading")]

    def section(title: str, cls: str, current: bool | None, sign: int = 1, profit=None) -> Amounts:
        start = len(lines)
        total = _section(lines, title, by_type, cls, current, sign, profit)
        if names is not None:
            _open_accounts(lines, start, balances, names, sign, cls)
        return total

    current = section("Оборотные активы", "asset", True)
    long_term = section("Долгосрочные активы", "asset", False)
    assets = current + long_term
    lines.append(Line(N_("Итого активы"), assets, "total"))
    lines.append(Line(N_("Обязательства и капитал"), kind="heading"))
    short = section("Краткосрочные обязательства", "liability", True, -1)
    long_debt = section("Долгосрочные обязательства", "liability", False, -1)
    equity = section("Капитал", "equity", None, -1, profit)
    sources = short + long_debt + equity
    lines.append(Line(N_("Итого обязательства и капитал"), sources, "total"))
    return Statement(lines, assets - sources)


@dataclass
class Names:
    """What the detail of a statement is titled by and ordered in."""

    accounts: dict[int, str]  # «26  Ümumtəsərrüfat xərcləri»
    order: dict[int, int]  # the place in the chart
    values: dict[int, str]  # subconto values

    @classmethod
    def read(cls, conn: Connection, company_id: int) -> Names:
        accounts = _accounts(conn, company_id)
        values = {
            r["id"]: r["name"]
            for r in conn.execute(
                "SELECT id, name FROM subconto_values WHERE company_id = ?", (company_id,)
            )
        }
        return cls(
            {i: f"{a['code'] or ''}  {a['name']}".strip() for i, a in accounts.items()},
            {i: n for n, i in enumerate(accounts)},
            values,
        )

    def account_lines(self, amounts: dict[int, Amounts], sign: int = 1) -> list[Line]:
        """A line per account with an amount, in the order of the chart."""
        return [
            Line(self.accounts[i], amounts[i] * sign, "account", account_id=i)
            for i in sorted(amounts, key=self.order.__getitem__)
            if amounts[i]
        ]


def _open_accounts(
    lines: list[Line], start: int, by_key: dict, names: Names, sign: int, cls: str
) -> None:
    """Put under each type line from `start` on its accounts (`by_key`: (key, account) ->
    amount; the untyped accounts of the class under «Счета без типа»)."""
    opened: list[Line] = lines[:start]
    for line in lines[start:]:
        opened.append(line)
        if line.kind == "line" and line.account_type is not None:
            key = line.account_type or f"{UNTYPED}:{cls}"
            amounts: dict[int, Amounts] = defaultdict(Amounts)
            for (k, account_id), net in by_key.items():
                if k == key:
                    amounts[account_id] += net
            opened.extend(names.account_lines(amounts, sign))
    lines[:] = opened


# ---- the parts ---------------------------------------------------------------------------


def _class(key: str) -> str | None:
    """The class of a type, or of an untyped key «:asset»."""
    return key.split(":", 1)[1] if key.startswith(":") else TYPE_CLASS.get(key)


def _type_line(account_type: str, amount: Amounts) -> Line:
    title = dict((t, name) for t, _, name in ACCOUNT_TYPES)[account_type]
    return Line(title, amount, account_type=account_type)


def _section(
    lines: list[Line],
    title: str,
    by_type: dict[str, Amounts],
    cls: str,
    current: bool | None,
    sign: int = 1,
    profit: Amounts | None = None,
) -> Amounts:
    """A heading, a line per type of the class (in the program's order), the subtotal;
    a section without lines is left out."""
    lines.append(Line(title, kind="heading"))
    result = Amounts()
    for account_type, type_class, _ in ACCOUNT_TYPES:
        long_term = account_type in NONCURRENT_TYPES
        if type_class != cls or (current is not None and long_term == current):
            continue
        amount = by_type.get(account_type, Amounts()) * sign
        if amount:
            lines.append(_type_line(account_type, amount))
            result += amount
    untyped = by_type.get(f"{UNTYPED}:{cls}", Amounts()) * sign
    if untyped and current is not False:  # untyped assets and debts count as current
        lines.append(Line(N_("Счета без типа"), untyped, account_type=UNTYPED))
        result += untyped
    if profit:
        lines.append(Line(N_("Прибыль (убыток) текущего периода"), profit))
        result += profit
    if lines[-1].kind == "heading":  # nothing in it: not shown at all
        lines.pop()
        return Amounts()
    lines.append(Line(title, result, "subtotal"))  # «Итого: …» when shown
    return result


def _balances(
    conn: Connection, company_id: int, days: list[str], layers
) -> dict[tuple[str, int], Amounts]:
    """Dt − Ct by (type, account) on each day, a column per day; a two-sided account with
    a first subconto is split per counterparty (an advance is not netted against a debt).
    One query per stretch between the days, added up: not a read from the start per day."""
    accounts = _accounts(conn, company_id)
    by_key: dict[tuple[str, int], Amounts] = defaultdict(Amounts)
    running: dict[tuple[int, int | None], int] = defaultdict(int)  # (account, subconto)
    after = ""
    for day in sorted(set(days)):
        for r in _moves(conn, company_id, after, day, layers):
            running[(r["account_id"], r["sc"])] += r["net"]
        after = day
        for column in (i for i, d in enumerate(days) if d == day):
            for (account_id, _sc), net in running.items():
                if not net:
                    continue
                a = accounts[account_id]
                key = a["account_type"] or f"{UNTYPED}:{a['account_class']}"
                if a["two_sided"] and a["sc1_kind_id"] is not None:
                    key = _split_key(key, a["account_class"], net)
                by_key[(key, account_id)] += Amounts.at(column, len(days), net)
    return by_key


def _moves(conn: Connection, company_id: int, after: str, day: str, layers):
    """Dt − Ct by account and its first subconto of the documents after `after` (""
    from the start) up to the day."""
    params = book_params(conn, company_id, day, day, layers)
    params["after"] = after
    return conn.execute(
        f"""
        WITH {docs_cte(start=AFTER)},
        moves AS (
            SELECT p.debit_account_id AS account_id, p.dt_sc1 AS sc, p.amount AS net
            FROM postings p JOIN docs ON docs.id = p.document_id
            WHERE p.company_id = :company_id
            UNION ALL
            SELECT p.credit_account_id, p.ct_sc1, -p.amount
            FROM postings p JOIN docs ON docs.id = p.document_id
            WHERE p.company_id = :company_id
        )
        SELECT account_id, sc, SUM(net) AS net FROM moves GROUP BY account_id, sc
        """,
        params,
    )


def _split_key(key: str, cls: str, net: int) -> str:
    """Where a counterparty's balance on a two-sided account belongs: a debit one among
    the assets, a credit one among the liabilities."""
    if cls == "asset" and net < 0:
        return FLIPPED.get(key, "other_liability")
    if cls == "liability" and net > 0:
        return FLIPPED.get(key, "other_receivable")
    return key
