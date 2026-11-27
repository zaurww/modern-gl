"""The e-qaimə number of a journal document's lines put right: one number for another,
nothing else of the document touched."""

from __future__ import annotations

from dataclasses import replace

from modern_gl.application.ledger.account_change import AccountChangeCommands
from modern_gl.application.ledger.posting_record import PostingRecord
from modern_gl.domain.errors import ValidationError
from modern_gl.domain.invoice import normalize_invoice
from modern_gl.i18n import tr
from modern_gl.infrastructure.db import transaction


class InvoiceChangeCommands(AccountChangeCommands):
    """One e-qaimə number of a document for another."""

    def change_posting_invoice(
        self, company_id: int, doc_id: int, old: str, new: str, reason: str = ""
    ) -> int:
        """The lines of the document that carry the e-qaimə `old` get `new` instead (an
        empty `old` — the only line without a number; an empty `new` takes the number
        off). The document keeps its number and status, a posted one is posted again
        (D32); one a module made is refused. How many lines changed."""
        was, now = normalize_invoice(old), normalize_invoice(new)
        with transaction(self.conn):
            doc = self._document(company_id, doc_id)
            self._require_not_module_document(company_id, doc)
            records = [PostingRecord.from_row(p) for p in self._posting_rows(doc_id)]
            found = [r for r in records if r.invoice == was]
            require_lines(doc["number"], was, now, len(found))
            changed = [
                replace(r, invoice=now, invoice_kind=r.invoice_kind if now else None)
                if r.invoice == was
                else r
                for r in records
            ]
            self._replace_records(company_id, doc, changed, reason)
        return len(found)


def require_lines(number: int, was: str | None, now: str | None, found: int) -> None:
    """Refuse a change of number that names no line, or more than one line by no number."""
    if was == now:
        raise ValidationError(tr("номер e-qaimə тот же — менять нечего"))
    if found == 0 and was is None:
        raise ValidationError(tr("в документе №{n} нет строки без e-qaimə", n=number))
    if found == 0:
        raise ValidationError(
            tr("в документе №{n} нет строки с e-qaimə {invoice}", n=number, invoice=was)
        )
    if found > 1 and was is None:
        raise ValidationError(
            tr("в документе №{n} несколько строк без e-qaimə — уточняет человек", n=number)
        )
