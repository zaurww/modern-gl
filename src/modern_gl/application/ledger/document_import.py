"""Importing documents from a journal file: all of them or none."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace

from modern_gl.application.ledger.documents import DocumentCommands
from modern_gl.application.ledger.inputs import ImportedDocument, ImportOutcome
from modern_gl.domain.errors import LedgerError
from modern_gl.infrastructure.db import transaction


class _Discard(Exception):
    """Rolls back an import that had problems or was only a check."""


class DocumentImportCommands(DocumentCommands):
    def import_documents(
        self,
        company_id: int,
        documents: Sequence[ImportedDocument],
        new_values: Sequence[tuple[int, str, int | None]] = (),
        post: bool = True,
        check_only: bool = False,
    ) -> ImportOutcome:
        """Create many documents at once (import from Excel): all or nothing.

        `new_values` are (kind id, name, owner) directory elements to add first; a posting
        refers to the i-th of them by the subconto id -(i + 1), and so may the owner (a new
        contract of a new counterparty). Every document is checked on its
        own (a savepoint each), so all problems are reported, not only the first. With any
        problem, or with `check_only`, nothing is kept.
        """
        outcome = ImportOutcome()
        try:
            with transaction(self.conn):
                created: list[int] = []
                for kind_id, name, owner in new_values:
                    if owner is not None and owner < 0:
                        owner = created[-owner - 1]
                    created.append(
                        self.add_subconto_value(company_id, kind_id, name, owner_id=owner)
                    )

                def real(values: Sequence[int | None]) -> tuple[int | None, ...]:
                    return tuple(created[-v - 1] if v is not None and v < 0 else v for v in values)

                for index, doc in enumerate(documents):
                    postings = [
                        replace(
                            p,
                            debit_subconto=real(p.debit_subconto),
                            credit_subconto=real(p.credit_subconto),
                        )
                        for p in doc.postings
                    ]
                    self.conn.execute("SAVEPOINT import_document")
                    try:
                        create = self.post_new if post else self.create_draft
                        outcome.ids.append(
                            create(company_id, doc.doc_date, postings, doc.memo, doc.layer)
                        )
                    except LedgerError as e:
                        self.conn.execute("ROLLBACK TO import_document")
                        outcome.errors.append((index, str(e)))
                    self.conn.execute("RELEASE import_document")
                if outcome.errors or check_only:
                    raise _Discard
        except _Discard:
            outcome.ids = []
        return outcome
