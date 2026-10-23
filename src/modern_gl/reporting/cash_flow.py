"""Движение денежных средств (D100), direct method: every posting between a money account
(cash, bank, ƏDV deposit, money in transit) and another account is money in or out, put
under the activity of that other account's type. Money moved between money accounts is
not a flow. The lines are the types of the other accounts, as in the balance sheet."""

from __future__ import annotations

from collections import defaultdict
from datetime import date

from modern_gl.domain.accounts import ACCOUNT_TYPES
from modern_gl.infrastructure.db import Connection
from modern_gl.reporting.report_common import COMMON, _accounts, _params
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
) -> Statement:
    """Money at the start, the flows of the period by activity, money at the end;
    `unbalanced` is what the end differs from start + flows by (0 when all is read).
    `detail` ACCOUNTS: a line opens into the other accounts (D102)."""
    params = _params(conn, company_id, date_from, date_to, layers)
    accounts = _accounts(conn, company_id)
    money = {i for i, a in accounts.items() if a["account_type"] in MONEY_TYPES}
    opening = closing = 0
    flows: dict[str, int] = defaultdict(int)
    by_account: dict[str, dict[int, int]] = defaultdict(lambda: defaultdict(int))
    for r in conn.execute(
        """
        SELECT d.doc_date, p.debit_account_id AS dt, p.credit_account_id AS ct, p.amount
        FROM postings p
        JOIN documents d ON d.company_id = p.company_id AND d.id = p.document_id
        JOIN layers l ON l.id = d.layer_id
        WHERE p.company_id = :company_id AND d.status = 'posted'
          AND d.doc_date <= :date_to
          AND l.code IN (SELECT value FROM json_each(:layers))
        """,
        params,
    ):
        change = (r["amount"] if r["dt"] in money else 0) - (r["amount"] if r["ct"] in money else 0)
        closing += change
        if r["doc_date"] < params["date_from"]:
            opening += change
        elif change:
            other = accounts[r["ct"] if r["dt"] in money else r["dt"]]
            flows[other["account_type"] or UNTYPED] += change
            by_account[other["account_type"] or UNTYPED][other["id"]] += change
    names = Names.read(conn, company_id) if detail != TYPES else None
    lines = [Line("Деньги на начало периода", opening, "subtotal")]
    net = 0
    for index, (title, subtotal) in enumerate(ACTIVITIES):
        lines.append(Line(title, kind="heading"))
        total = 0
        for account_type, _, name in ACCOUNT_TYPES:
            if activity(account_type) == index and flows.get(account_type):
                lines.append(Line(name, flows[account_type], account_type=account_type))
                total += flows[account_type]
                if names is not None:
                    lines.extend(names.account_lines(by_account[account_type]))
        if index == 0 and flows.get(UNTYPED):
            lines.append(Line("Счета без типа", flows[UNTYPED], account_type=UNTYPED))
            total += flows[UNTYPED]
            if names is not None:
                lines.extend(names.account_lines(by_account[UNTYPED]))
        if lines[-1].kind == "heading":  # nothing in it: not shown
            lines.pop()
            continue
        lines.append(Line(subtotal, total, "subtotal"))
        net += total
    lines.append(Line("Изменение денег за период", net, "subtotal"))
    lines.append(Line("Деньги на конец периода", closing, "total"))
    return Statement(lines, closing - opening - net)
