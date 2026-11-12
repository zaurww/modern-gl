"""Accountable persons and advance reports (D-new-advance-reports): money given to an
employee to spend for the company (71) and his report of what it went on. Reading —
`people` (who owes what, one person's movements) and `model` (a report); writing —
`AccountableModule`, built over a ledger as the warehouse is (`AccountableModule(conn,
actor, ledger=ledger)`): the core knows nothing of it."""

from __future__ import annotations

from modern_gl.application.accountable.commands import AdvanceReportCommands
from modern_gl.application.accountable.model import (
    AdvanceLine,
    AdvanceReport,
    AdvanceReportInput,
    load_advance_report,
    load_advance_reports,
    report_of_document,
)
from modern_gl.application.accountable.people import (
    AccountableAccount,
    Person,
    PersonLine,
    PersonStatement,
    accountable_account,
    accountable_people,
    employee_balance,
    person_statement,
)


class AccountableModule(AdvanceReportCommands):
    """The advance reports' write scenarios: save, post, unpost, delete, rebuild."""


__all__ = [
    "AccountableAccount",
    "AccountableModule",
    "AdvanceLine",
    "AdvanceReport",
    "AdvanceReportCommands",
    "AdvanceReportInput",
    "Person",
    "PersonLine",
    "PersonStatement",
    "accountable_account",
    "accountable_people",
    "employee_balance",
    "load_advance_report",
    "load_advance_reports",
    "person_statement",
    "report_of_document",
]
