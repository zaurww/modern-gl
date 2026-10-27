"""Прибыли и убытки (D99, D102, D128): income and expense of a period by account type, in
the categories of IFRS 18 — operating, investing, financing, income tax — the second
statement of the «Финансовая отчётность» page, beside the balance sheet (statements).
A line opens into its accounts, an account into its items (the first subconto: the cost
items of 26 and 44).

Revenue is net of the ƏDV charged on the sales (IFRS 15.47): the gross sales and the
ƏDV show only in its detail. A leg of an income or expense is put in its category by its
type and the account on the other side: interest against a loan is financing, an exchange
difference goes where its account is (on money — investing, on a loan — financing, on a
debt of a partner — operating).

Amounts are minor units: income as Ct − Dt, expense as −(Dt − Ct), so the lines simply
add up."""

from __future__ import annotations

from collections import defaultdict
from datetime import date

from modern_gl.application.books import COMMON, FROM, book_params, docs_cte
from modern_gl.domain.accounts import DEFERRED_TAX_TYPES
from modern_gl.domain.period_input import Period
from modern_gl.i18n import N_, tr
from modern_gl.infrastructure.db import Connection, Row
from modern_gl.reporting.columns import Amounts, total
from modern_gl.reporting.report_common import _accounts
from modern_gl.reporting.statements import (
    ACCOUNTS,
    CLOSING_TYPES,
    ITEMS,
    TYPES,
    UNTYPED,
    Line,
    Names,
    Statement,
    _type_line,
)

__all__ = ["ACCOUNTS", "ITEMS", "TYPES", "profit_and_loss"]
SALES_VAT = "sales_vat"  # Dt sales Kt the output VAT account: taken off the revenue
FX_MONEY = "fx_money"  # an exchange difference on money: investing (IFRS 18 B)
FX_LOANS = "fx_loans"  # on a loan: financing
DEFERRED_TAX = "deferred_tax"
# the lines of a key that is no account type
TITLES = {
    FX_MONEY: N_("Курсовые разницы по денежным средствам"),
    FX_LOANS: N_("Курсовые разницы по кредитам"),
    DEFERRED_TAX: N_("Отложенный налог на прибыль"),
    f"{UNTYPED}:revenue": N_("Доходы без типа"),
    f"{UNTYPED}:expense": N_("Расходы без типа"),
}
# on a sales account only these are the buyer's side (a sale, a return); anything else
# written there — goods, a carrier (Dt 46 Kt 60), wages — is the cost of the sales
BUYER_TYPES = frozenset(
    {"receivable", "advance_received", "other_receivable", "cash", "bank", "transit"}
)
MONEY_TYPES = frozenset({"cash", "bank", "transit", "vat_deposit"})
LOAN_TYPES = frozenset({"short_term_loan", "long_term_loan"})
INVESTMENT_TYPES = frozenset({"investment", "long_term_investment"})
PL_CLASSES = ("revenue", "expense")
OPERATING = (
    "operating_expense",
    "other_income",
    "other_expense",
    f"{UNTYPED}:revenue",
    f"{UNTYPED}:expense",
)
INVESTING = ("finance_income", FX_MONEY)
FINANCING = ("finance_expense", FX_LOANS)
# (line, account, the account's first subconto) -> a figure per column
Turnovers = dict[tuple[str, int, int | None], Amounts]


def profit_and_loss(
    conn: Connection,
    company_id: int,
    date_from: date | str,
    date_to: date | str,
    layers: tuple[str, ...] = COMMON,
    detail: str = TYPES,
    periods: list[Period] | None = None,
) -> Statement:
    """Income and expense of the period, without the closing of them into the result
    (postings against a «Financial result» or «Retained earnings» account) and without
    the moves between income and expense accounts (26, 44 closed into 46): an expense
    shows where it was spent. `detail`: TYPES, or ACCOUNTS / ITEMS under each line.
    `periods`: a column per period (D107), else the one from `date_from` to `date_to`."""
    t: Turnovers = defaultdict(Amounts)
    columns = periods or [(date_from, date_to)]
    for i, (first, last) in enumerate(columns):
        for k, net in _turnovers(conn, company_id, first, last, layers).items():
            t[k] += Amounts.at(i, len(columns), net)
    names = Names.read(conn, company_id) if detail != TYPES else None
    return Statement(_Lines(t, names, detail == ITEMS).build())


class _Lines:
    """The lines of the statement in the order of IFRS 18, each with its detail."""

    def __init__(self, t: Turnovers, names: Names | None, items: bool) -> None:
        self.t, self.names, self.items = t, names, items
        self.lines: list[Line] = []

    def build(self) -> list[Line]:
        gross = self.revenue() + self.add("cost_of_sales")
        self.subtotal(N_("Валовая прибыль"), gross)
        operating = gross + sum((self.add(k) for k in OPERATING), Amounts())
        self.subtotal(N_("Операционная прибыль"), operating)
        investing = sum((self.add(k) for k in INVESTING), Amounts())
        before_financing = operating + investing
        mark = len(self.lines)
        financing = sum((self.add(k) for k in FINANCING), Amounts())
        if len(self.lines) > mark:  # IFRS 18: the subtotal before the financing
            self.lines.insert(
                mark,
                Line(
                    N_("Прибыль до финансирования и налога на прибыль"),
                    before_financing,
                    "subtotal",
                ),
            )
        before_tax = before_financing + financing
        self.subtotal(N_("Прибыль до налогообложения"), before_tax)
        net = before_tax + self.add("income_tax") + self.add(DEFERRED_TAX)
        self.lines.append(Line(N_("Чистая прибыль (убыток)"), net, "total"))
        return self.lines

    def subtotal(self, title: str, amount: Amounts) -> None:
        self.lines.append(Line(title, amount, "subtotal"))

    def amount(self, key: str) -> Amounts:
        return total(v for (k, _, _), v in self.t.items() if k == key)

    def add(self, key: str) -> Amounts:
        amount = self.amount(key)
        if amount:
            line = _pl_line(key, amount)
            self.lines.append(line)
            if self.names is not None:
                self.lines.extend(_detail(self.t, key, self.names, self.items, line))
        return amount

    def revenue(self) -> Amounts:
        """Revenue net of the ƏDV of the sales; its detail: the gross sales by account and
        the ƏDV taken off them."""
        sales, vat = self.amount("sales"), self.amount(SALES_VAT)
        net = sales + vat
        if not net and not sales:
            return net
        line = Line("Выручка", net, account_type="sales")
        self.lines.append(line)
        if self.names is None:
            return net
        self.lines.extend(_detail(self.t, "sales", self.names, self.items, line, bool(vat)))
        if vat:
            vat_accounts = {a for (k, a, _), v in self.t.items() if k == SALES_VAT and v}
            single = next(iter(vat_accounts)) if len(vat_accounts) == 1 else None
            self.lines.append(Line(tr("НДС с продаж"), vat, "account", account_id=single))
        return net


def _pl_line(key: str, amount: Amounts) -> Line:
    if key in TITLES:
        return Line(TITLES[key], amount, account_type=UNTYPED if key.startswith(":") else key)
    return _type_line(key, amount)


def _detail(
    t: Turnovers, key: str, names: Names, items: bool, line: Line, always: bool = False
) -> list[Line]:
    """The accounts of a line in the order of the chart, each with its items by name
    (the postings without one last). The only account of a line is not repeated under
    it (46 under the cost) unless `always`: the line itself leads to it."""
    by_account: dict[int, dict[int | None, Amounts]] = defaultdict(lambda: defaultdict(Amounts))
    for (k, account_id, value_id), amount in t.items():
        if k == key:
            by_account[account_id][value_id] += amount
    shown = [
        a for a in sorted(by_account, key=names.order.__getitem__) if total(by_account[a].values())
    ]
    one = len(shown) == 1 and not always
    if len(shown) == 1:
        line.account_id = shown[0]
    lines: list[Line] = []
    for account_id in shown:
        values = by_account[account_id]
        if not one:
            whole = total(values.values())
            lines.append(Line(names.accounts[account_id], whole, "account", account_id=account_id))
        if not items or set(values) == {None}:
            continue
        titles = {v: names.values.get(v, "") if v is not None else "" for v in values}
        lines.extend(
            Line(titles[v], values[v], "item", None, account_id, v, one)
            for v in sorted(values, key=lambda v: (v is None, titles[v]))
            if values[v]
        )
    return lines


def _turnovers(
    conn: Connection, company_id: int, date_from, date_to, layers
) -> dict[tuple[str, int, int | None], int]:
    """Income (Ct − Dt) and expense (−(Dt − Ct)) of the period by line, account and the
    account's first subconto, signed so they add; each leg judged by `_pl_key`. A posting
    in a currency with no amount in it is an exchange difference (the revaluation)."""
    params = book_params(conn, company_id, date_from, date_to, layers)
    accounts = _accounts(conn, company_id)
    output_vat = {
        r["account_id"]
        for r in conn.execute(
            "SELECT account_id FROM account_roles WHERE company_id = ? AND role = 'output_vat'",
            (company_id,),
        )
    }
    result: dict[tuple[str, int, int | None], int] = defaultdict(int)
    for r in conn.execute(
        f"""
        WITH {docs_cte(start=FROM)},
        moves AS (
            SELECT p.*, CASE WHEN p.currency_id IS NOT NULL AND p.currency_amount = 0
                             THEN 1 ELSE 0 END AS fx
            FROM postings p JOIN docs ON docs.id = p.document_id
            WHERE p.company_id = :company_id
        ),
        legs AS (
            SELECT debit_account_id AS account_id, credit_account_id AS other,
                   dt_sc1 AS sc, fx, -amount AS net
            FROM moves
            UNION ALL
            SELECT credit_account_id, debit_account_id, ct_sc1, fx, amount
            FROM moves
        )
        SELECT account_id, other, sc, fx, SUM(net) AS net
        FROM legs
        GROUP BY account_id, other, sc, fx, CASE WHEN net > 0 THEN 1 ELSE 0 END
        """,
        params,
    ):
        a, other = accounts[r["account_id"]], accounts[r["other"]]
        key = _pl_key(a, other, r["net"], output_vat, bool(r["fx"]))
        if key is not None:
            result[(key, r["account_id"], r["sc"])] += r["net"]
    return result


def _pl_key(a: Row, other: Row, net: int, output_vat: set[int], fx: bool) -> str | None:
    """The line of a leg on account `a` against `other`; None: not income or expense.
    - between two income / expense accounts (Dt 46 Kt 26) — a move: the expense counts
      where it was spent;
    - against «Financial result» or «Retained earnings» — the closing;
    - on a sales account against the output VAT account — the VAT of the sales (Dt 46
      Kt 68.2); against anything but the buyer or money — the cost of sales (Dt 46 Kt 41,
      a carrier Dt 46 Kt 60);
    - against a deferred tax account — the deferred tax;
    - an other income or expense, or one written straight to «Financial result» (the
      short chart: Dt 80 Kt 51 a bank fee, Dt 80 Kt 90 interest), by the other account:
      a loan — financing, an investment — investing, money in an exchange difference —
      investing; a tax on «Financial result» — the profit tax."""
    passes = other["account_class"] in PL_CLASSES or other["account_type"] in CLOSING_TYPES
    if passes or not (a["account_class"] in PL_CLASSES or a["account_type"] == "profit_loss"):
        return None
    if other["account_type"] in DEFERRED_TAX_TYPES:
        return DEFERRED_TAX
    kind = a["account_type"]
    if kind == "sales":
        if other["id"] in output_vat:
            return SALES_VAT
        return "cost_of_sales" if other["account_type"] not in (None, *BUYER_TYPES) else kind
    tax = other["account_type"] == "tax_payable" and other["id"] not in output_vat
    if kind == "profit_loss" and tax:
        return "income_tax"
    if kind in ("profit_loss", "other_income", "other_expense", None):
        side = _category(other["account_type"], fx)
        if side is not None:
            return side
    if kind == "profit_loss":
        return "other_income" if net > 0 else "other_expense"
    return kind or f"{UNTYPED}:{a['account_class']}"


def _category(other: str | None, fx: bool) -> str | None:
    """The line of an other income or expense outside the operating category, by the
    account on the other side; None: operating."""
    if other in LOAN_TYPES:
        return FX_LOANS if fx else "finance_expense"
    if other in INVESTMENT_TYPES:
        return "finance_income"
    if other in MONEY_TYPES and fx:
        return FX_MONEY
    if other == "transit":  # the exchange difference of a conversion (D37)
        return FX_MONEY
    return None
