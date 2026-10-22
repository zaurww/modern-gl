"""A typed line saved: its new elements («+Name») added and the document posted (or kept
as a draft) — one transaction, nothing half-done when it fails (debts 9, 10)."""

from __future__ import annotations

from datetime import date

from modern_gl.application.ledger import Ledger, PostingInput
from modern_gl.application.quick_entry.parser import NewValue, QuickEntry, QuickLine
from modern_gl.domain.errors import ValidationError
from modern_gl.domain.money import from_minor
from modern_gl.i18n import tr
from modern_gl.infrastructure.db import transaction


def save_quick_entry(
    ledger: Ledger, company_id: int, entry: QuickEntry, working_date: date, post: bool
) -> int:
    """Post (or save as a draft) the parsed line; returns the document's id."""
    with transaction(ledger.conn):
        _add_new_values(ledger, company_id, entry)
        inputs = [posting_input(n, ln) for n, ln in enumerate(entry.lines, start=1)]
        day = entry.doc_date or working_date
        create = ledger.post_new if post else ledger.create_draft
        return create(company_id, day, inputs, entry.memo)


def _add_new_values(ledger: Ledger, company_id: int, entry: QuickEntry) -> None:
    for new in entry.new_values:  # a new counterparty comes before its new contract
        owner = new.owner.id if isinstance(new.owner, NewValue) else new.owner
        new.id = ledger.add_subconto_value(company_id, new.kind_id, new.name, owner_id=owner)
        for index, side, pos in new.cells:
            getattr(entry.lines[index], f"{side}_sc")[pos] = new.id


def posting_input(n: int, ln: QuickLine) -> PostingInput:
    if ln.debit is None or ln.credit is None:
        raise ValidationError(
            tr("строка {n}: в шаблоне не указан счёт — Ctrl+Enter откроет форму", n=n)
        )
    if ln.amount is None:
        raise ValidationError(tr("строка {n}: не указана сумма", n=n))
    return PostingInput(
        ln.debit,
        ln.credit,
        from_minor(ln.amount),
        tuple(ln.debit_sc),
        tuple(ln.credit_sc),
        ln.memo,
        ln.currency_id,
        None if ln.currency_amount is None else from_minor(ln.currency_amount),
        ln.invoice,
    )
