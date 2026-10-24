"""Reading an exchange file into a company (D130): the names of its lines become the
company's accounts and elements, then `Ledger.import_documents` makes them — all or
nothing, a document imported before from the same source is left as it is."""

from __future__ import annotations

from dataclasses import dataclass, field

from modern_gl.application.catalog import Catalog
from modern_gl.application.exchange.format import ExchangeBatch
from modern_gl.application.exchange.lines import posting_lines
from modern_gl.application.ledger import ImportedDocument, Ledger
from modern_gl.infrastructure.db import Connection


@dataclass(frozen=True)
class Imported:
    """A document of the file in the company: its id there and the number people see."""

    external_id: str
    document_id: int
    number: int


@dataclass
class ExchangeOutcome:
    """By the documents' own ids: made now, there from before, and what is wrong."""

    new: list[str] = field(default_factory=list)  # made now, or to be made (a check)
    created: list[Imported] = field(default_factory=list)
    existing: list[Imported] = field(default_factory=list)
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
            lines = [] if doc.reverses else posting_lines(cat, doc.postings, exact=True)
        except (LookupError, ValueError) as e:
            outcome.errors.append((doc.external_id, str(e)))
            continue
        documents.append(
            ImportedDocument(
                doc.doc_date, lines, doc.memo, doc.layer, doc.external_id, doc.reverses
            )
        )
    if outcome.errors:
        return outcome
    result = ledger.import_documents(
        company_id, documents, post=post, check_only=check_only, source=batch.source
    )
    ids = [d.external_id for d in documents]
    outcome.errors = [(ids[i], message) for i, message in result.errors]
    there = {i for i, _ in result.existing}
    if not outcome.errors:
        outcome.new = [d for i, d in enumerate(ids) if i not in there]
    made = list(zip(outcome.new, result.ids, strict=False))  # none after a check
    numbers = _numbers(ledger.conn, company_id, [*result.ids, *(d for _, d in result.existing)])
    outcome.created = [Imported(e, d, numbers[d]) for e, d in made]
    outcome.existing = [Imported(ids[i], d, numbers[d]) for i, d in result.existing]
    return outcome


def _numbers(conn: Connection, company_id: int, doc_ids: list[int]) -> dict[int, int]:
    if not doc_ids:
        return {}
    rows = conn.execute(
        "SELECT id, number FROM documents WHERE company_id = ? AND id IN "
        f"({', '.join('?' * len(doc_ids))})",
        (company_id, *doc_ids),
    )
    return {r["id"]: r["number"] for r in rows}
