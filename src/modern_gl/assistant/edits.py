"""Edits the assistant makes to what is posted (--allow-edits): the mistakes a person
points at — a duplicate, a wrong e-qaimə number, a wrong line.

Every edit is one scenario of `Ledger` or of the bank module — the rules of the program:
an open period only, a module's document through its module, the old content and the
reason in the audit trail under the assistant's name («AI · Claude»). The assistant
never deletes and never posts a draft: a duplicate is unposted, the person deletes it.
One document a call; the file is copied before the first edit of a run.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from modern_gl.application.catalog import Catalog
from modern_gl.application.exchange.lines import posting_lines
from modern_gl.application.ledger import Ledger
from modern_gl.application.queries import document_by_number, document_owner
from modern_gl.assistant.drafts import Drafts
from modern_gl.i18n import tr
from modern_gl.reporting import answers

BANK = "bank"


@dataclass
class Edits:
    drafts: Drafts  # the way into the company file, and the assistant's name
    _copied: set[Path] = field(default_factory=set[Path])

    def change_document(
        self,
        number: int,
        date: str,
        memo: str,
        postings: list[dict],
        reason: str,
        company: str = "",
    ) -> dict:
        """A journal document replaced whole: a posted one in place, a draft as a draft."""
        why = _reason(reason)
        backup = self._copy_first(company)
        with self.drafts.writing(company) as (ledger, company_id):
            doc_id = document_by_number(ledger.conn, company_id, number)
            before = answers.document(ledger.conn, company_id, number)
            if document_owner(ledger.conn, company_id, doc_id) is not None:
                raise ValueError(
                    tr(
                        "документ №{n} сделан разделом программы (банк, склад…): целиком "
                        "его меняет человек там",
                        n=number,
                    )
                )
            lines = posting_lines(Catalog(ledger.conn, company_id), postings)
            if before["status"] == "posted":
                ledger.repost(company_id, doc_id, date, lines, memo, _layer(before), why)
            else:
                ledger.update_draft(company_id, doc_id, date, lines, memo, _layer(before))
            return _answer(ledger, company_id, number, before, backup)

    def set_e_qaime(self, number: int, old: str, new: str, reason: str, company: str = "") -> dict:
        """The e-qaimə number of a document's lines: `old` becomes `new`, nothing else."""
        why = _reason(reason)
        backup = self._copy_first(company)
        with self.drafts.writing(company) as (ledger, company_id):
            doc_id = document_by_number(ledger.conn, company_id, number)
            before = answers.document(ledger.conn, company_id, number)
            owner = document_owner(ledger.conn, company_id, doc_id)
            if owner is None:
                changed = ledger.change_posting_invoice(company_id, doc_id, old, new, why)
            elif owner.module == BANK:
                changed = ledger.bank.change_line_invoice(company_id, owner.id, old, new, why)
            else:
                raise ValueError(_not_here(number))
            answer = _answer(ledger, company_id, number, before, backup)
            return {**answer, "changed_lines": changed}

    def unpost_document(self, number: int, reason: str, company: str = "") -> dict:
        """A posted document back to a draft (a duplicate): out of the books, not deleted."""
        why = _reason(reason)
        backup = self._copy_first(company)
        with self.drafts.writing(company) as (ledger, company_id):
            doc_id = document_by_number(ledger.conn, company_id, number)
            before = answers.document(ledger.conn, company_id, number)
            owner = document_owner(ledger.conn, company_id, doc_id)
            if owner is None:
                ledger.unpost(company_id, doc_id, why)
            elif owner.module == BANK:
                ledger.bank.unpost_bank_operation(company_id, owner.id, why)
            else:
                raise ValueError(_not_here(number))
            return _answer(ledger, company_id, number, before, backup)

    def _copy_first(self, company: str) -> Path | None:
        """The copy of the file made before the first edit of this run; None after it."""
        companies = self.drafts.companies
        path = companies.path(company)
        if path in self._copied:
            return None
        made = companies.workspace.backup_file(path, tr("до правок AI"))
        self._copied.add(path)
        return made


def _reason(reason: str) -> str:
    if not reason.strip():
        raise ValueError(tr("укажите причину правки (reason) — она остаётся в истории документа"))
    return reason.strip()


def _not_here(number: int) -> str:
    return tr(
        "документ №{n} сделан складом, конвертацией или другим разделом: его правит "
        "человек в программе",
        n=number,
    )


def _layer(document: dict) -> str:
    return str(document["book_layer"])


def _answer(
    ledger: Ledger, company_id: int, number: int, before: dict, backup: Path | None
) -> dict:
    return {
        "before": before,
        "after": answers.document(ledger.conn, company_id, number),
        **({"backup": str(backup)} if backup else {}),
        "note": "done; the old content and the reason are in the document's history",
    }
