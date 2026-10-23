"""Движение денежных средств (D100), direct method: every posting between a money account
(cash, bank, ƏDV deposit, money in transit) and another account is money in or out, put
under the activity of that other account's type. Money moved between money accounts is
not a flow. The lines are the types of the other accounts, as in the balance sheet."""

from __future__ import annotations

from collections import defaultdict
from datetime import date

from modern_gl.domain.accounts import ACCOUNT_TYPES
from modern_gl.domain.dates import iso_date
from modern_gl.domain.period_input import Period
from modern_gl.infrastructure.db import Connection
from modern_gl.reporting.columns import Amounts
from modern_gl.reporting.report_common import COMMON, _accounts, _params, docs_cte
from modern_gl.reporting.statements import TYPES, UNTYPED, Line, Names, Statement

MONEY_TYPES = frozenset({"cash", "bank", "vat_deposit", "transit"})
INVESTING = frozenset(
    {"fixed_asset", "intangible", "investment", "long_term_investment", "other_noncurrent_asset"}
)
FINANCING = frozenset(
    {
        "share_capital",
        "other_equity",
        "retained_earnings",
        "short_term_loan",
        "long_term_loan",
        "other_long_term_liability",
    }
)
ACTIVITIES = (
    ("Операционная деятельность", "Чистый поток от операционной деятельности"),
    ("Инвестиционная деятельность", "Чистый поток от инвестиционной деятельности"),
    ("Финансовая деятельность", "Чистый поток от финансовой деятельности"),
)


def activity(account_type: str) -> int:
    """0 operating, 1 investing, 2 financing (an untyped account: operating)."""
    return 1 if account_type in INVESTING else 2 if account_type in FINANCING else 0


def cash_flow(
    conn: Connection,
    company_id: int,
    date_from: date | str,
    date_to: date | str,
    layers: tuple[str, ...] = COMMON,
    detail: str = TYPES,
    periods: list[Period] | None = None,
) -> Statement:
    """Money at the start, the flows of the period by activity, money at the end;
    `unbalanced` is what the end differs from start + flows by (0 when all is read).
    `detail` ACCOUNTS: a line opens into the other accounts (D102). `periods`: a column
    per period (D107), read in one pass."""
    columns = [(iso_date(a), iso_date(b)) for a, b in periods or [(date_from, date_to)]]
    accounts = _accounts(conn, company_id)
    opening, closing, flows, by_account = _read(conn, company_id, columns, layers, accounts)
    names = Names.read(conn, company_id) if detail != TYPES else None
    lines = [Line("Деньги на начало периода", opening, "subtotal")]
    net = Amounts()
    for index, (title, subtotal) in enumerate(ACTIVITIES):
        lines.append(Line(title, kind="heading"))
        result = Amounts()
        for account_type, _, name in ACCOUNT_TYPES:
            if activity(account_type) == index and flows.get(account_type):
                lines.append(Line(name, flows[account_type], account_type=account_type))
                result += flows[account_type]
                if names is not None:
                    lines.extend(names.account_lines(by_account[account_type]))
        if index == 0 and flows.get(UNTYPED):
            lines.append(Line("Счета без типа", flows[UNTYPED], account_type=UNTYPED))
            result += flows[UNTYPED]
            if names is not None:
                lines.extend(names.account_lines(by_account[UNTYPED]))
        if lines[-1].kind == "heading":  # nothing in it: not shown
            lines.pop()
            continue
        lines.append(Line(subtotal, result, "subtotal"))
        net += result
    lines.append(Line("Изменение денег за период", net, "subtotal"))
    lines.append(Line("Деньги на конец периода", closing, "total"))
    return Statement(lines, closing - opening - net)


def _read(conn: Connection, company_id: int, columns: list[tuple[str, str]], layers, accounts):
    """Money at the start and the end of each column, and its flows by the other
    account's type and by the other account."""
    first = min(a for a, _ in columns)
    params = _params(conn, company_id, first, max(b for _, b in columns), layers)
    money = {i for i, a in accounts.items() if a["account_type"] in MONEY_TYPES}
    n = len(columns)
    opening, closing = Amounts(), Amounts()
    flows: dict[str, Amounts] = defaultdict(Amounts)
    by_account: dict[str, dict[int, Amounts]] = defaultdict(lambda: defaultdict(Amounts))
    for r in conn.execute(
        f"""
        WITH {docs_cte("d.id, d.doc_date")}
        SELECT docs.doc_date, p.debit_account_id AS dt, p.credit_account_id AS ct,
               SUM(p.amount) AS amount
        FROM postings p JOIN docs ON docs.id = p.document_id
        WHERE p.company_id = :company_id
        GROUP BY docs.doc_date, p.debit_account_id, p.credit_account_id
        """,
        params,
    ):
        change = (r["amount"] if r["dt"] in money else 0) - (r["amount"] if r["ct"] in money else 0)
        if not change:
            continue
        other = accounts[r["ct"] if r["dt"] in money else r["dt"]]
        key = other["account_type"] or UNTYPED
        for i, (first, last) in enumerate(columns):
            if r["doc_date"] > last:
                continue
            closing += Amounts.at(i, n, change)
            if r["doc_date"] < first:
                opening += Amounts.at(i, n, change)
            else:
                flows[key] += Amounts.at(i, n, change)
                by_account[key][other["id"]] += Amounts.at(i, n, change)
    return opening, closing, flows, by_account
