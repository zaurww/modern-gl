"""Прибыли и убытки (D99, D102): income and expense of a period by account type — the
second statement of the «Финансовая отчётность» page, beside the balance sheet
(statements). A line opens into its accounts, an account into its items (the first
subconto: the cost items of 26 and 44).

Amounts are minor units: income as Ct − Dt, expense as −(Dt − Ct), so the lines simply
add up."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date

from modern_gl.infrastructure.db import Connection, Row
from modern_gl.reporting.report_common import COMMON, _accounts, _params
from modern_gl.reporting.statements import CLOSING_TYPES, UNTYPED, Line, Statement, _type_line

TYPES, ACCOUNTS, ITEMS = "types", "accounts", "items"  # how much a line shows under it
SALES_VAT = "sales_vat"  # Dt sales Kt the output VAT account: a line of its own
PL_CLASSES = ("revenue", "expense")
# (line, account, the account's first subconto) -> amount
Turnovers = dict[tuple[str, int, int | None], int]


def profit_and_loss(
    conn: Connection,
    company_id: int,
    date_from: date | str,
    date_to: date | str,
    layers: tuple[str, ...] = COMMON,
    detail: str = TYPES,
) -> Statement:
    """Income and expense of the period, without the closing of them into the result
    (postings against a «Financial result» or «Retained earnings» account) and without
    the moves between income and expense accounts (26, 44 closed into 46): an expense
    shows where it was spent. `detail`: TYPES, or ACCOUNTS / ITEMS under each line."""
    t = _turnovers(conn, company_id, date_from, date_to, layers)
    names = _Names.read(conn, company_id) if detail != TYPES else None
    lines: list[Line] = []

    def add(key: str) -> int:
        amount = sum(v for (k, _, _), v in t.items() if k == key)
        if amount:
            lines.append(_pl_line(key, amount))
            if names is not None:
                lines.extend(_detail(t, key, names, detail == ITEMS))
        return amount

    gross = add("sales") + add(SALES_VAT) + add("cost_of_sales")
    lines.append(Line("Валовая прибыль", gross, "subtotal"))
    operating = gross + add("operating_expense")
    lines.append(Line("Операционная прибыль", operating, "subtotal"))
    other = add("other_income") + add("other_expense")
    other += add(f"{UNTYPED}:revenue") + add(f"{UNTYPED}:expense")
    before_tax = operating + other
    lines.append(Line("Прибыль до налогообложения", before_tax, "subtotal"))
    net = before_tax + add("income_tax")
    lines.append(Line("Чистая прибыль (убыток)", net, "total"))
    return Statement(lines)


def _pl_line(key: str, amount: int) -> Line:
    if key == SALES_VAT:
        return Line("НДС с продаж", amount, account_type=SALES_VAT)
    if key.startswith(":"):
        title = "Доходы без типа" if key.endswith(":revenue") else "Расходы без типа"
        return Line(title, amount, account_type=UNTYPED)
    return _type_line(key, amount)


@dataclass
class _Names:
    accounts: dict[int, str]  # «26  Ümumtəsərrüfat xərcləri»
    order: dict[int, int]  # the place in the chart
    values: dict[int, str]

    @classmethod
    def read(cls, conn: Connection, company_id: int) -> _Names:
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


def _detail(t: Turnovers, key: str, names: _Names, items: bool) -> list[Line]:
    """The accounts of a line in the order of the chart, each with its items by name
    (the postings without one last)."""
    by_account: dict[int, dict[int | None, int]] = defaultdict(lambda: defaultdict(int))
    for (k, account_id, value_id), amount in t.items():
        if k == key:
            by_account[account_id][value_id] += amount
    lines: list[Line] = []
    for account_id in sorted(by_account, key=names.order.__getitem__):
        values = by_account[account_id]
        if total := sum(values.values()):
            lines.append(Line(names.accounts[account_id], total, "account", account_id=account_id))
        if not total or not items or set(values) == {None}:
            continue
        titles = {v: names.values.get(v, "") if v is not None else "" for v in values}
        for value_id in sorted(values, key=lambda v: (v is None, titles[v])):
            if values[value_id]:
                lines.append(
                    Line(titles[value_id], values[value_id], "item", None, account_id, value_id)
                )
    return lines


def _turnovers(conn: Connection, company_id: int, date_from, date_to, layers) -> Turnovers:
    """Income (Ct − Dt) and expense (−(Dt − Ct)) of the period by line, account and the
    account's first subconto, signed so they add; each leg judged by `_pl_key`."""
    params = _params(conn, company_id, date_from, date_to, layers)
    accounts = _accounts(conn, company_id)
    output_vat = {
        r["account_id"]
        for r in conn.execute(
            "SELECT account_id FROM account_roles WHERE company_id = ? AND role = 'output_vat'",
            (company_id,),
        )
    }
    result: Turnovers = defaultdict(int)
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
                   p.dt_sc1 AS sc, -p.amount AS net
            FROM postings p JOIN docs ON docs.id = p.document_id
            WHERE p.company_id = :company_id
            UNION ALL
            SELECT p.credit_account_id, p.debit_account_id, p.ct_sc1, p.amount
            FROM postings p JOIN docs ON docs.id = p.document_id
            WHERE p.company_id = :company_id
        )
        SELECT account_id, other, sc, SUM(net) AS net
        FROM legs
        GROUP BY account_id, other, sc, CASE WHEN net > 0 THEN 1 ELSE 0 END
        """,
        params,
    ):
        a, other = accounts[r["account_id"]], accounts[r["other"]]
        key = _pl_key(a, other, r["net"], output_vat)
        if key is not None:
            result[(key, r["account_id"], r["sc"])] += r["net"]
    return result


def _pl_key(a: Row, other: Row, net: int, output_vat: set[int]) -> str | None:
    """The line of a leg on account `a` against `other`; None: not income or expense.
    - between two income / expense accounts (Dt 46 Kt 26) — a move: the expense counts
      where it was spent;
    - against «Financial result» or «Retained earnings» — the closing;
    - on a sales account against inventory — the cost of sales (Dt 46 Kt 41), against
      the output VAT account — the VAT of the sales (Dt 46 Kt 68.2);
    - on «Financial result» itself against anything else (the short chart writes there
      directly: Dt 80 Kt 51 a bank fee, Dt 52 Kt 80 an exchange gain) — other income or
      expense; against a tax — the profit tax."""
    passes = other["account_class"] in PL_CLASSES or other["account_type"] in CLOSING_TYPES
    if a["account_type"] == "profit_loss":
        if passes:
            return None
        if other["account_type"] == "tax_payable" and other["id"] not in output_vat:
            return "income_tax"
        return "other_income" if net > 0 else "other_expense"
    if a["account_class"] not in PL_CLASSES or passes:
        return None
    if a["account_type"] == "sales" and other["id"] in output_vat:
        return SALES_VAT
    if a["account_type"] == "sales" and other["account_type"] == "inventory":
        return "cost_of_sales"
    return a["account_type"] or f"{UNTYPED}:{a['account_class']}"
