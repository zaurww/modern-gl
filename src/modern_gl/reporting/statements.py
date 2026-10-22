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


@dataclass
class Line:
    title: str  # Russian, for tr(): a type's name, or a caption of the statement
    amount: int = 0
    kind: str = "line"  # line | subtotal | total | heading
    account_type: str | None = None  # the type of a «line» (UNTYPED: none)


@dataclass
class Statement:
    lines: list[Line] = field(default_factory=list)
    # balance sheet: assets − (liabilities + equity); profit and loss: 0
    unbalanced: int = 0


def balance_sheet(
    conn: Connection, company_id: int, day: date | str, layers: tuple[str, ...] = COMMON
) -> Statement:
    """Assets, liabilities and equity on the day; the profit not yet closed into equity
    (the balances of income and expense accounts) is a line of equity."""
    by_type = _balances(conn, company_id, iso_date(day), layers)
    profit = -sum(v for t, v in by_type.items() if _class(t) in ("revenue", "expense"))
    lines: list[Line] = [Line("Активы", kind="heading")]
    current = _section(lines, "Оборотные активы", by_type, "asset", True)
    long_term = _section(lines, "Долгосрочные активы", by_type, "asset", False)
    assets = current + long_term
    lines.append(Line("Итого активы", assets, "total"))
    lines.append(Line("Обязательства и капитал", kind="heading"))
    short = _section(lines, "Краткосрочные обязательства", by_type, "liability", True, -1)
    long_debt = _section(lines, "Долгосрочные обязательства", by_type, "liability", False, -1)
    equity = _section(lines, "Капитал", by_type, "equity", None, -1, profit)
    total = short + long_debt + equity
    lines.append(Line("Итого обязательства и капитал", total, "total"))
    return Statement(lines, assets - total)


def profit_and_loss(
    conn: Connection,
    company_id: int,
    date_from: date | str,
    date_to: date | str,
    layers: tuple[str, ...] = COMMON,
) -> Statement:
    """Income and expense of the period, without the closing of them into the result
    (postings against a «Financial result» or «Retained earnings» account)."""
    t = _turnovers(conn, company_id, date_from, date_to, layers)
    lines: list[Line] = []

    def add(account_type: str) -> int:
        amount = t.get(account_type, 0)
        if amount:
            lines.append(_type_line(account_type, amount))
        return amount

    gross = add("sales") + add("cost_of_sales")
    lines.append(Line("Валовая прибыль", gross, "subtotal"))
    operating = gross + add("operating_expense")
    lines.append(Line("Операционная прибыль", operating, "subtotal"))
    other = add("other_income") + add("other_expense")
    for cls, title in (("revenue", "Доходы без типа"), ("expense", "Расходы без типа")):
        if t.get(f"{UNTYPED}:{cls}"):
            lines.append(Line(title, t[f"{UNTYPED}:{cls}"], account_type=UNTYPED))
            other += t[f"{UNTYPED}:{cls}"]
    before_tax = operating + other
    lines.append(Line("Прибыль до налогообложения", before_tax, "subtotal"))
    net = before_tax + add("income_tax")
    lines.append(Line("Чистая прибыль (убыток)", net, "total"))
    return Statement(lines)


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


def _balances(conn: Connection, company_id: int, day: str, layers) -> dict[str, int]:
    """Dt − Ct by type on the day; a two-sided account with a first subconto is split per
    counterparty (an advance is not netted against a debt)."""
    params = _params(conn, company_id, day, day, layers)
    accounts = _accounts(conn, company_id)
    by_type: dict[str, int] = defaultdict(int)
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
        by_type[key] += r["net"]
    return by_type


def _split_key(key: str, cls: str, net: int) -> str:
    """Where a counterparty's balance on a two-sided account belongs: a debit one among
    the assets, a credit one among the liabilities."""
    if cls == "asset" and net < 0:
        return FLIPPED.get(key, "other_liability")
    if cls == "liability" and net > 0:
        return FLIPPED.get(key, "other_receivable")
    return key


def _turnovers(conn: Connection, company_id: int, date_from, date_to, layers) -> dict[str, int]:
    """Income (Ct − Dt) and expense (−(Dt − Ct)) of the period by type, signed so they add."""
    params = _params(conn, company_id, date_from, date_to, layers)
    result: dict[str, int] = defaultdict(int)
    for r in conn.execute(
        """
        WITH docs AS (
            SELECT d.id FROM documents d JOIN layers l ON l.id = d.layer_id
            WHERE d.company_id = :company_id AND d.status = 'posted'
              AND d.doc_date BETWEEN :date_from AND :date_to
              AND l.code IN (SELECT value FROM json_each(:layers))
        ),
        legs AS (
            SELECT p.debit_account_id AS account_id, p.credit_account_id AS other,
                   -p.amount AS net
            FROM postings p JOIN docs ON docs.id = p.document_id
            WHERE p.company_id = :company_id
            UNION ALL
            SELECT p.credit_account_id, p.debit_account_id, p.amount
            FROM postings p JOIN docs ON docs.id = p.document_id
            WHERE p.company_id = :company_id
        )
        SELECT a.account_type, a.account_class, SUM(legs.net) AS net
        FROM legs
        JOIN accounts a ON a.company_id = :company_id AND a.id = legs.account_id
        JOIN accounts o ON o.company_id = :company_id AND o.id = legs.other
        WHERE a.account_class IN ('revenue', 'expense')
          AND COALESCE(o.account_type, '') NOT IN ('profit_loss', 'retained_earnings')  -- CLOSING
        GROUP BY a.account_type, a.account_class
        """,
        params,
    ):
        key = r["account_type"] or f"{UNTYPED}:{r['account_class']}"
        result[key] += r["net"]
    return result
