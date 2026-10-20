"""What documents of modules share (currency conversion, bank operations): their GL
documents are written and removed only by them, never by the journal."""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from datetime import date

from modern_gl.application.ledger.chart import ChartCommands
from modern_gl.application.ledger.documents import DocumentCommands
from modern_gl.application.ledger.inputs import PostingInput
from modern_gl.domain.dates import iso_date


class ModuleDocumentCommands(ChartCommands, DocumentCommands):
    def named_subconto(self, company_id: int, account_id: int, name: str) -> tuple[int | None, ...]:
        """The account's subconto filled with an element of this name (an item of other
        income and expenses, a cost item…), made on first use."""
        account = self._account(company_id, account_id)
        values: list[int | None] = []
        for i in (1, 2, 3):
            kind_id = account[f"sc{i}_kind_id"]
            if kind_id is None:
                values.append(None)
                continue
            found = self.conn.execute(
                "SELECT id FROM subconto_values WHERE company_id = ? AND kind_id = ? "
                "AND name = ? ORDER BY active DESC, id LIMIT 1",
                (company_id, kind_id, name),
            ).fetchone()
            values.append(found[0] if found else self.add_subconto_value(company_id, kind_id, name))
        return tuple(values)

    def _write_module_document(
        self,
        company_id: int,
        doc_id: int,
        doc_date: date | str,
        postings: Sequence[PostingInput],
        memo: str,
    ) -> None:
        """Post a module's GL document anew; a posted one is changed in place (D32) and
        the audit trail keeps what it was, unless nothing changed."""
        doc = self._document(company_id, doc_id)
        if doc["status"] == "posted":
            if self._same_content(doc, doc_date, postings, memo):
                return
            snapshot = self._snapshot(doc)
            self._rewrite(company_id, doc_id, doc_date, postings, memo, "common")
            self._audit(company_id, "document", doc_id, "repost", snapshot)
            return
        self.conn.execute(
            "UPDATE documents SET doc_date = ?, memo = ? WHERE id = ?",
            (iso_date(doc_date), memo, doc_id),
        )
        self.conn.execute("DELETE FROM postings WHERE document_id = ?", (doc_id,))
        self._insert_postings(company_id, doc_id, postings)
        self._post(company_id, doc_id)

    def _remove_document(self, company_id: int, doc: sqlite3.Row) -> None:
        snapshot = self._snapshot(doc)
        if doc["status"] == "posted":  # immutability triggers allow only this path
            self.conn.execute(
                "UPDATE documents SET status = 'draft', posted_at = NULL WHERE id = ?",
                (doc["id"],),
            )
        self.conn.execute("DELETE FROM documents WHERE id = ?", (doc["id"],))
        self._audit(company_id, "document", doc["id"], "delete", snapshot)
