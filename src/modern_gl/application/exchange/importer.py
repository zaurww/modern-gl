"""Reading an exchange file into a company (D130): the names of its lines become the
company's accounts and elements, then `Ledger.import_documents` makes them — all or
nothing, a document imported before from the same source is left as it is."""

from __future__ import annotations

from dataclasses import dataclass, field

from modern_gl.application.catalog import Catalog
from modern_gl.application.exchange.format import ExchangeBatch
from modern_gl.application.exchange.lines import posting_lines
from modern_gl.application.ledger import ImportedDocument, Ledger


@dataclass
class ExchangeOutcome:
    """By the documents' own ids: made now, there from before, and what is wrong."""

    new: list[str] = field(default_factory=list)  # made now, or to be made (a check)
    created: list[tuple[str, int]] = field(default_factory=list)  # (external id, document id)
    existing: list[tuple[str, int]] = field(default_factory=list)
    errors: list[tuple[str, str]] = field(default_factory=list)  # (external id, message)

    @property
    def ok(self) -> bool:
        return not self.errors


def import_batch(
    ledger: Ledger,
    company_id: int,
    batch: ExchangeBatch,
    post: bool = False,
    check_only: bool = False,
) -> ExchangeOutcome:
    """Drafts (or, with `post`, posted documents) from the file. With any problem, or with
    `check_only`, nothing is written and every problem is named."""
    outcome = ExchangeOutcome()
    cat = Catalog(ledger.conn, company_id)
    documents: list[ImportedDocument] = []
    for doc in batch.documents:
        try:
            lines = posting_lines(cat, doc.postings, exact=True)
        except (LookupError, ValueError) as e:
            outcome.errors.append((doc.external_id, str(e)))
            continue
        documents.append(
            ImportedDocument(doc.doc_date, lines, doc.memo, doc.layer, doc.external_id)
        )
    if outcome.errors:
        return outcome
    result = ledger.import_documents(
        company_id, documents, post=post, check_only=check_only, source=batch.source
    )
    ids = [d.external_id for d in documents]
    outcome.errors = [(ids[i], message) for i, message in result.errors]
    outcome.existing = [(ids[i], doc_id) for i, doc_id in result.existing]
    there = {i for i, _ in result.existing}
    if not outcome.errors:
        outcome.new = [d for i, d in enumerate(ids) if i not in there]
    outcome.created = list(zip(outcome.new, result.ids, strict=False))  # none after a check
    return outcome
