"""Drafts the assistant prepares for a person to post (D84).

The assistant only ever writes drafts of journal documents, through `Ledger` — the same
checks as typing them in. It never posts, and changes or deletes only drafts it entered
itself: the audit trail names it as the author («AI · Claude»), which the document's head
shows (D82). Names, not ids, come from the model: accounts by code, directory elements by
name or VÖEN; an element missing from a directory is an error — the person adds it.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from modern_gl.application.authorship import document_authors
from modern_gl.application.catalog import Catalog
from modern_gl.application.exchange.lines import posting_lines
from modern_gl.application.ledger import Ledger
from modern_gl.application.queries import document_by_number, load_document
from modern_gl.assistant.companies import Companies
from modern_gl.i18n import tr
from modern_gl.infrastructure.db import Connection
from modern_gl.reporting import answers

AI = "AI · "  # an actor starting so is the assistant


@dataclass
class Drafts:
    companies: Companies
    client: Callable[[], str]  # the client's name, known after initialize

    @property
    def actor(self) -> str:
        return AI + (self.client() or "MCP")

    def create(self, date: str, memo: str, postings: list[dict], company: str = "") -> dict:
        with self._writing(company) as (ledger, company_id):
            lines = posting_lines(Catalog(ledger.conn, company_id), postings)
            doc_id = ledger.create_draft(company_id, date, lines, memo)
            return _answer(ledger, company_id, doc_id)

    def update(
        self, number: int, date: str, memo: str, postings: list[dict], company: str = ""
    ) -> dict:
        with self._writing(company) as (ledger, company_id):
            doc_id = self._own_draft(ledger.conn, company_id, number)
            lines = posting_lines(Catalog(ledger.conn, company_id), postings)
            ledger.update_draft(company_id, doc_id, date, lines, memo)
            return _answer(ledger, company_id, doc_id)

    def delete(self, number: int, company: str = "") -> dict:
        with self._writing(company) as (ledger, company_id):
            ledger.delete_draft(company_id, self._own_draft(ledger.conn, company_id, number))
            return {"deleted": number}

    @contextmanager
    def _writing(self, company: str) -> Iterator[tuple[Ledger, int]]:
        """The company file itself, briefly: the program may have it open — SQLite lets
        both write in turn; a file behind the program's schema is backed up first."""
        conn, company_id = self.companies.workspace.open(self.companies.path(company), lock=False)
        try:
            yield Ledger(conn, actor=self.actor), company_id
        finally:
            conn.close()

    def _own_draft(self, conn: Connection, company_id: int, number: int) -> int:
        doc_id = document_by_number(conn, company_id, number)
        authors = document_authors(conn, company_id, doc_id)
        if authors is None or not authors.entered_by.startswith(AI):
            raise ValueError(tr("документ №{n} ввёл не помощник — его меняет человек", n=number))
        return doc_id


def _answer(ledger: Ledger, company_id: int, doc_id: int) -> dict:
    number = load_document(ledger.conn, company_id, doc_id).number
    problem = ledger.posting_problem(company_id, doc_id)
    return {
        **answers.document(ledger.conn, company_id, number),
        "would_post": problem is None,
        **({"problem": problem} if problem else {}),
        "note": "a draft: the user checks and posts it in the program",
    }
