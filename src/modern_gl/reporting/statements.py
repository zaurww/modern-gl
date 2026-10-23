"""Финансовая отчётность (D99): the balance sheet on a day and the profit and loss for a
period, read from the accounts' types (D35) — whatever the codes of the chart. Level 2 of
the classification: a line per type, current and long-term apart (D89).

Amounts are minor units: assets and expenses as Dt − Ct, liabilities, equity and income
as Ct − Dt; in the profit and loss an expense is negative, so the lines simply add up."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date

from modern_gl.domain.accounts import ACCOUNT_TYPES, NONCURRENT_TYPES, TYPE_CLASS
from modern_gl.domain.dates import iso_date
from modern_gl.infrastructure.db import Connection
from modern_gl.reporting.report_common import COMMON, _accounts, _params

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
    amount: int = 0
    kind: str = "line"  # line | account | item | subtotal | total | heading
    account_type: str | None = None  # the type of a «line» (UNTYPED: none)
    # the detail under a line of the profit and loss (D102): an «account», an «item» of
    # it (its first subconto, None: not given); their titles are names, not for tr()
    account_id: int | None = None
    value_id: int | None = None


@dataclass
class Statement:
    lines: list[Line] = field(default_factory=list)
    # balance sheet: assets − (liabilities + equity); profit and loss: 0
    unbalanced: int = 0


def balance_sheet(
    conn: Connection,
    company_id: int,
    day: date | str,
    layers: tuple[str, ...] = COMMON,
    detail: str = TYPES,
) -> Statement:
    """Assets, liabilities and equity on the day; the profit not yet closed into equity
    (the balances of income and expense accounts) is a line of equity. `detail` ACCOUNTS:
    each line opens into its accounts (D102)."""
    balances = _balances(conn, company_id, iso_date(day), layers)
    by_type: dict[str, int] = defaultdict(int)
    for (key, _), net in balances.items():
        by_type[key] += net
    names = Names.read(conn, company_id) if detail != TYPES else None
    profit = -sum(v for t, v in by_type.items() if _class(t) in ("revenue", "expense"))
    lines: list[Line] = [Line("Активы", kind="heading")]

    def section(title: str, cls: str, current: bool | None, sign: int = 1, profit=None) -> int:
        start = len(lines)
        total = _section(lines, title, by_type, cls, current, sign, profit)
        if names is not None:
            _open_accounts(lines, start, balances, names, sign, cls)
        return total

    current = section("Оборотные активы", "asset", True)
    long_term = section("Долгосрочные активы", "asset", False)
    assets = current + long_term
    lines.append(Line("Итого активы", assets, "total"))
    lines.append(Line("Обязательства и капитал", kind="heading"))
    short = section("Краткосрочные обязательства", "liability", True, -1)
    long_debt = section("Долгосрочные обязательства", "liability", False, -1)
    equity = section("Капитал", "equity", None, -1, profit)
    total = short + long_debt + equity
    lines.append(Line("Итого обязательства и капитал", total, "total"))
    return Statement(lines, assets - total)


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

    def account_lines(self, amounts: dict[int, int], sign: int = 1) -> list[Line]:
        """A line per account with an amount, in the order of the chart."""
        return [
            Line(self.accounts[i], sign * amounts[i], "account", account_id=i)
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
            amounts: dict[int, int] = defaultdict(int)
            for (k, account_id), net in by_key.items():
                if k == key:
                    amounts[account_id] += net
            opened.extend(names.account_lines(amounts, sign))
    lines[:] = opened


# ---- the parts ---------------------------------------------------------------------------


def _class(key: str) -> str | None:
    """The class of a type, or of an untyped key «:asset»."""
    return key.split(":", 1)[1] if key.startswith(":") else TYPE_CLASS.get(key)


def _type_line(account_type: str, amount: int) -> Line:
    title = dict((t, name) for t, _, name in ACCOUNT_TYPES)[account_type]
    return Line(title, amount, account_type=account_type)


def _section(
    lines: list[Line],
    title: str,
    by_type: dict[str, int],
    cls: str,
    current: bool | None,
    sign: int = 1,
    profit: int | None = None,
) -> int:
    """A heading, a line per type of the class (in the program's order), the subtotal;
    a section without lines is left out."""
    lines.append(Line(title, kind="heading"))
    total = 0
    for account_type, type_class, _ in ACCOUNT_TYPES:
        long_term = account_type in NONCURRENT_TYPES
        if type_class != cls or (current is not None and long_term == current):
            continue
        amount = sign * by_type.get(account_type, 0)
        if amount:
            lines.append(_type_line(account_type, amount))
            total += amount
    untyped = sign * by_type.get(f"{UNTYPED}:{cls}", 0)
    if untyped and current is not False:  # untyped assets and debts count as current
        lines.append(Line("Счета без типа", untyped, account_type=UNTYPED))
        total += untyped
    if profit:
        lines.append(Line("Прибыль (убыток) текущего периода", profit))
        total += profit
    if lines[-1].kind == "heading":  # nothing in it: not shown at all
        lines.pop()
        return 0
    lines.append(Line(title, total, "subtotal"))  # «Итого: …» when shown
    return total


def _balances(conn: Connection, company_id: int, day: str, layers) -> dict[tuple[str, int], int]:
    """Dt − Ct by (type, account) on the day; a two-sided account with a first subconto
    is split per counterparty (an advance is not netted against a debt)."""
    params = _params(conn, company_id, day, day, layers)
    accounts = _accounts(conn, company_id)
    by_key: dict[tuple[str, int], int] = defaultdict(int)
    for r in conn.execute(
        """
        WITH docs AS (
            SELECT d.id FROM documents d JOIN layers l ON l.id = d.layer_id
            WHERE d.company_id = :company_id AND d.status = 'posted'
              AND d.doc_date <= :date_to
              AND l.code IN (SELECT value FROM json_each(:layers))
        ),
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
    ):
        a = accounts[r["account_id"]]
        key = a["account_type"] or f"{UNTYPED}:{a['account_class']}"
        if a["two_sided"] and a["sc1_kind_id"] is not None:
            key = _split_key(key, a["account_class"], r["net"])
        by_key[(key, r["account_id"])] += r["net"]
    return by_key


def _split_key(key: str, cls: str, net: int) -> str:
    """Where a counterparty's balance on a two-sided account belongs: a debit one among
    the assets, a credit one among the liabilities."""
    if cls == "asset" and net < 0:
        return FLIPPED.get(key, "other_liability")
    if cls == "liability" and net > 0:
        return FLIPPED.get(key, "other_receivable")
    return key
