"""The bank in «Проверка книги» (D175): the books agree with what the bank says — what
SAP reconciles as the bank's statement against the GL account. A statement whose balance
by the bank was entered ends with that balance in the books, and a period of the ƏDV
deposit marked reconciled with the portal (D118) still has its figures. A posting made to
51 by hand in the journal, after the statement was reconciled, shows here."""

from __future__ import annotations

from modern_gl.application.bank.deposit_reconciliation import changed_since
from modern_gl.application.bank.places import BankPlace, bank_places
from modern_gl.application.bank.statements import DIFF, BankStatement, bank_statements
from modern_gl.application.ledger import Ledger
from modern_gl.application.verification import CheckResult, Finding
from modern_gl.domain.dates import ru_date
from modern_gl.domain.money import format_minor
from modern_gl.i18n import tr


def statements_against_bank(ledger: Ledger, company_id: int) -> CheckResult:
    """Each bank account: its statements by the bank, then its reconciled ƏDV periods."""
    findings: list[Finding] = []
    for place in bank_places(ledger.conn, company_id):
        findings += [
            Finding(_differs(place, st))
            for st in bank_statements(ledger.conn, company_id, place)
            if st.status == DIFF
        ]
        findings += [
            Finding(f"{_name(place)}: {change}")
            for change in changed_since(ledger.conn, company_id, place)
        ]
    return CheckResult(tr("Банк сходится с выписками банка"), tuple(findings))


def _differs(place: BankPlace, st: BankStatement) -> str:
    period = ru_date(st.date_from)
    if st.date_to != st.date_from:
        period += f"–{ru_date(st.date_to)}"
    return tr(
        "{place}, выписка {period}: по банку {bank}, в программе {books}, разница {diff}",
        place=_name(place),
        period=period,
        bank=_amount(place, st.bank_closing or 0),
        books=_amount(place, st.closing),
        diff=_amount(place, st.difference or 0),
    )


def _name(place: BankPlace) -> str:
    return f"{place.name} ({place.account_code})"


def _amount(place: BankPlace, minor: int) -> str:
    text = format_minor(minor)
    return f"{text} {place.currency}" if place.currency else text
