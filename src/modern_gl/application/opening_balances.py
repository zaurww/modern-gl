"""Opening balances stored as an ordinary, balanced GL document."""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta

from modern_gl.application.ledger import Ledger, PostingInput
from modern_gl.domain.accounts import OPENING_BALANCE
from modern_gl.domain.dates import iso_date
from modern_gl.domain.errors import ValidationError
from modern_gl.domain.money import format_minor, to_minor
from modern_gl.i18n import tr
from modern_gl.infrastructure.db import transaction


@dataclass(frozen=True)
class OpeningBalanceDocument:
    document_id: int
    effective_date: str


def opening_document(conn: sqlite3.Connection, company_id: int) -> OpeningBalanceDocument | None:
    row = conn.execute(
        "SELECT document_id, effective_date FROM opening_balance_documents WHERE company_id = ?",
        (company_id,),
    ).fetchone()
    return OpeningBalanceDocument(**dict(row)) if row is not None else None


def is_opening_document(conn: sqlite3.Connection, company_id: int, document_id: int) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM opening_balance_documents WHERE company_id = ? AND document_id = ?",
            (company_id, document_id),
        ).fetchone()
        is not None
    )


def ensure_opening_account(ledger: Ledger, company_id: int) -> int:
    """Return the hidden technical counter-account, creating it on first use."""
    existing = ledger.account_role(company_id, OPENING_BALANCE)
    if existing is not None:
        return existing
    with transaction(ledger.conn):
        account_id = ledger.add_account(
            company_id,
            None,
            tr("Технический счёт начальных остатков"),
            account_class="equity",
            account_type="other_equity",
            two_sided=True,
        )
        ledger.set_account_role(company_id, OPENING_BALANCE, account_id)
    return account_id


def save_opening_document(
    ledger: Ledger,
    company_id: int,
    effective_date: date | str,
    postings: Sequence[PostingInput],
    *,
    post: bool,
    memo: str,
) -> int:
    """Create or replace the company's opening balances.

    Every input line has the technical account on exactly one side.  Debit balances
    credit it; credit balances debit it.  Equal totals make that account close to zero.
    """
    control = ensure_opening_account(ledger, company_id)
    if not postings:
        raise ValidationError(tr("не введены начальные остатки"))
    debit = credit = 0
    for line, item in enumerate(postings, start=1):
        on_debit = item.debit_account_id == control
        on_credit = item.credit_account_id == control
        if on_debit == on_credit:
            raise ValidationError(
                tr("строка {line}: неверная строка начальных остатков", line=line)
            )
        amount = to_minor(item.amount)
        if amount <= 0:
            raise ValidationError(tr("строка {line}: сумма должна быть больше нуля", line=line))
        if on_credit:  # real account is on debit
            debit += amount
        else:  # real account is on credit
            credit += amount
    if debit != credit:
        raise ValidationError(
            tr(
                "Дебетовые и кредитовые остатки не сходятся: {debit} и {credit}",
                debit=format_minor(debit),
                credit=format_minor(credit),
            )
        )

    effective = date.fromisoformat(iso_date(effective_date))
    document_date = effective - timedelta(days=1)
    with transaction(ledger.conn):
        current = opening_document(ledger.conn, company_id)
        if current is None:
            doc_id = ledger.create_draft(company_id, document_date, postings, memo)
            ledger.conn.execute(
                "INSERT INTO opening_balance_documents "
                "(company_id, document_id, effective_date) VALUES (?, ?, ?)",
                (company_id, doc_id, effective.isoformat()),
            )
            if post:
                ledger.post(company_id, doc_id)
            return doc_id

        doc_id = current.document_id
        status = ledger.conn.execute(
            "SELECT status FROM documents WHERE company_id = ? AND id = ?", (company_id, doc_id)
        ).fetchone()["status"]
        ledger.conn.execute(
            "UPDATE opening_balance_documents SET effective_date = ? WHERE company_id = ?",
            (effective.isoformat(), company_id),
        )
        if status == "posted":
            ledger.repost(company_id, doc_id, document_date, postings, memo)
        else:
            ledger.update_draft(company_id, doc_id, document_date, postings, memo)
            if post:
                ledger.post(company_id, doc_id)
        return doc_id
