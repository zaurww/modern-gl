"""An advance report as the paper to sign (D218): its lines with the
accounts as the accountant reads them («26 · Yanacaq»), and what the employee had before
it — the same figure the form shows."""

from __future__ import annotations

from modern_gl.application.accountable.model import load_advance_report
from modern_gl.application.accountable.people import accountable_account, employee_balance
from modern_gl.infrastructure.advance_report_file import AdvancePaper, AdvancePaperLine
from modern_gl.infrastructure.db import Connection


def advance_paper(conn: Connection, company_id: int, report_id: int) -> AdvancePaper:
    report = load_advance_report(conn, company_id, report_id)
    company = conn.execute(
        "SELECT name, tax_id FROM companies WHERE id = ?", (company_id,)
    ).fetchone()
    employee = _name(conn, company_id, report.employee_id)
    account = accountable_account(conn, company_id)
    given = (
        employee_balance(
            conn,
            company_id,
            account,
            report.employee_id,
            report.doc_date,
            without=report.document_id,
        )
        if account is not None and report.employee_id is not None
        else 0
    )
    credit = " · ".join(x for x in (account.code if account else "", employee) if x)
    lines = [
        AdvancePaperLine(
            line.memo or report.memo,
            _account(conn, company_id, line.account_id, line.subconto),
            credit,
            line.amount,
        )
        for line in report.lines
    ]
    return AdvancePaper(
        company["name"],
        company["tax_id"] or "",
        report.number,
        report.doc_date,
        employee,
        given,
        lines,
    )


def _name(conn: Connection, company_id: int, value_id: int | None) -> str:
    if value_id is None:
        return ""
    row = conn.execute(
        "SELECT name FROM subconto_values WHERE company_id = ? AND id = ?", (company_id, value_id)
    ).fetchone()
    return row[0] if row else ""


def _account(conn: Connection, company_id: int, account_id: int | None, subconto) -> str:
    """«26 · Yanacaq»: the code and the subconto chosen on the line."""
    if account_id is None:
        return ""
    row = conn.execute(
        "SELECT COALESCE(code, name) FROM accounts WHERE company_id = ? AND id = ?",
        (company_id, account_id),
    ).fetchone()
    names = [_name(conn, company_id, v) for v in subconto if v is not None]
    return " · ".join([row[0] if row else "", *names])
