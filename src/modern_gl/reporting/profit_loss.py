"""Прибыли и убытки (D99): income and expense of a period by account type — the second
statement of the «Финансовая отчётность» page, beside the balance sheet (statements).

Amounts are minor units: income as Ct − Dt, expense as −(Dt − Ct), so the lines simply
add up."""

from __future__ import annotations

from collections import defaultdict
from datetime import date

from modern_gl.infrastructure.db import Connection
from modern_gl.reporting.report_common import COMMON, _params
from modern_gl.reporting.statements import UNTYPED, Line, Statement, _type_line


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
