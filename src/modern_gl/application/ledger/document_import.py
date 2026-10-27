"""Importing documents from a journal file: all of them or none."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import replace
from functools import partial

from modern_gl.application.ledger.documents import DocumentCommands
from modern_gl.application.ledger.inputs import ImportedDocument, ImportOutcome
from modern_gl.domain.errors import LedgerError, NotFoundError
from modern_gl.i18n import tr
from modern_gl.infrastructure.db import transaction


class _DiscardError(Exception):
    """Rolls back an import that had problems or was only a check."""


class DocumentImportCommands(DocumentCommands):
    def import_documents(
        self,
        company_id: int,
        documents: Sequence[ImportedDocument],
        new_values: Sequence[tuple[int, str, int | None]] = (),
        post: bool = True,
        check_only: bool = False,
        source: str = "",
    ) -> ImportOutcome:
        """Create many documents at once (import from Excel): all or nothing.

        `new_values` are (kind id, name, owner) directory elements to add first; a posting
        refers to the i-th of them by the subconto id -(i + 1), and so may the owner (a new
        contract of a new counterparty). Every document is checked on its
        own (a savepoint each), so all problems are reported, not only the first. With any
        problem, or with `check_only`, nothing is kept.

        With a `source` (the program the file came from, D130) a document is marked with
        its `external_id`; one imported before from the same source is left as it is and
        named in `existing` — the same file twice makes no duplicates.
        """
        outcome = ImportOutcome()
        try:
            with transaction(self.conn):
                created: list[int] = []
                for kind_id, name, ref in new_values:
                    owner = created[-ref - 1] if ref is not None and ref < 0 else ref
                    created.append(
                        self.add_subconto_value(company_id, kind_id, name, owner_id=owner)
                    )

                def real(values: Sequence[int | None]) -> tuple[int | None, ...]:
                    return tuple(created[-v - 1] if v is not None and v < 0 else v for v in values)

                seen: set[str] = set()
                for index, doc in enumerate(documents):
                    sourced = bool(source and doc.external_id)
                    if sourced and not self._first_of(
                        company_id, source, doc, index, seen, outcome
                    ):
                        continue
                    postings = [
                        replace(
                            p,
                            debit_subconto=real(p.debit_subconto),
                            credit_subconto=real(p.credit_subconto),
                        )
                        for p in doc.postings
                    ]
                    create = self.post_new if post else self.create_draft
                    make = partial(create, company_id, doc.doc_date, postings, doc.memo, doc.layer)
                    if doc.reverses:
                        make = self._storno(company_id, source, doc)
                    doc_id = self._import_one(index, outcome, make)
                    if doc_id is not None and sourced:
                        self._mark_source(company_id, doc_id, source, doc.external_id)
                if outcome.errors or check_only:
                    raise _DiscardError
        except _DiscardError:
            outcome.ids = []
        return outcome

    def _first_of(
        self,
        company_id: int,
        source: str,
        doc: ImportedDocument,
        index: int,
        seen: set[str],
        outcome: ImportOutcome,
    ) -> bool:
        """Whether the document is to be made: not twice in the file, not imported before."""
        if doc.external_id in seen:
            outcome.errors.append((index, tr("документ «{id}» в файле дважды", id=doc.external_id)))
            return False
        seen.add(doc.external_id)
        existing = self._sourced(company_id, source, doc.external_id)
        if existing is not None:
            outcome.existing.append((index, existing))
            return False
        return True

    def _storno(self, company_id: int, source: str, doc: ImportedDocument) -> Callable[[], int]:
        """The red storno of a document imported before from the same source (D5)."""
        original = self._sourced(company_id, source, doc.reverses)

        def reverse() -> int:
            if original is None:
                raise NotFoundError(
                    tr("сторно: документа «{id}» нет среди загруженных", id=doc.reverses)
                )
            return self.reverse(company_id, original, doc.doc_date, doc.memo or None)

        return reverse

    def _sourced(self, company_id: int, source: str, external_id: str) -> int | None:
        row = self.conn.execute(
            "SELECT document_id FROM document_sources "
            "WHERE company_id = ? AND source = ? AND external_id = ?",
            (company_id, source, external_id),
        ).fetchone()
        return None if row is None else row["document_id"]

    def _import_one(
        self, index: int, outcome: ImportOutcome, create: Callable[[], int]
    ) -> int | None:
        """One document in a transaction of its own (a savepoint inside the import's):
        its problem is noted and undone."""
        try:
            with transaction(self.conn):
                doc_id = create()
        except LedgerError as e:
            outcome.errors.append((index, str(e)))
            return None
        outcome.ids.append(doc_id)
        return doc_id

    def _mark_source(self, company_id: int, doc_id: int, source: str, external_id: str) -> None:
        self.conn.execute(
            "INSERT INTO document_sources (company_id, document_id, source, external_id) "
            "VALUES (?, ?, ?, ?)",
            (company_id, doc_id, source, external_id),
        )
