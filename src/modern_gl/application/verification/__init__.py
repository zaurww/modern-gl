"""«Проверка книги» (D175): the program asks its own data whether they agree — what
QuickBooks calls Verify Data and SAP a ledger consistency check. The database already
refuses a wrong row (triggers, CHECK, keys — D149, D155); this finds what no single row
shows: a file damaged on the disk, a posted document today's rules would refuse, a storno
that does not mirror its document, a module's postings that are not what its documents
make, a bank account that does not agree with the bank's statements, a warehouse that
does not agree with its accounts.

Everything runs on a copy of the company in memory (`scratch_copy`): the file is only
read, so a company open for viewing (D80) is checked as well. What can be put right is
one scenario — `rebuild_modules`, the modules' postings built again (D101)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

from modern_gl.application.ledger import Ledger
from modern_gl.application.rebuild import rebuild_postings
from modern_gl.i18n import tr
from modern_gl.infrastructure.db import Connection, file_problems, scratch_copy

REBUILD = "rebuild"  # a result's repair: the modules' postings built again


@dataclass(frozen=True)
class Finding:
    """One thing that does not agree; `document_id` — the GL document it is about."""

    text: str
    document_id: int | None = None


@dataclass(frozen=True)
class CheckResult:
    """One check: its title, what it found (nothing — all is well), how to put it right."""

    title: str
    findings: tuple[Finding, ...]
    repair: str = ""  # REBUILD, or nothing the program can do for the accountant

    @property
    def ok(self) -> bool:
        return not self.findings


Check = Callable[[Ledger, int], CheckResult]


def checks() -> tuple[Check, ...]:
    """The checks in the order they are shown: the core's, then the modules'. The list is
    explicit, like `rebuild.module_rebuilders`: a new module adds its check here."""
    from modern_gl.application.bank.verification import statements_against_bank
    from modern_gl.application.inventory.verification import stock_against_accounts
    from modern_gl.application.verification.books import module_postings, posting_rules, storno

    return (posting_rules, storno, module_postings, statements_against_bank, stock_against_accounts)


def verify(conn: Connection, company_id: int) -> list[CheckResult]:
    """Every check of the company; the file itself first. Nothing in the file changes."""
    results = [
        CheckResult(
            tr("Файл компании цел"), tuple(Finding(problem) for problem in file_problems(conn))
        )
    ]
    copy = scratch_copy(conn)
    try:
        ledger = Ledger(copy, "verification")
        results += [check(ledger, company_id) for check in checks()]
    finally:
        copy.close()
    return results


def rebuild_modules(ledger: Ledger, company_id: int) -> list[int]:
    """Put right what `module_postings` found: the modules' GL documents of the open period
    built again from their documents (D101), one transaction; the documents that changed."""
    return rebuild_postings(ledger, company_id, date.min)
