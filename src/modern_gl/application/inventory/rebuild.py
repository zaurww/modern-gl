"""Building the warehouse's GL documents again (D101): every posted document from a day
on is taken out of the sequence and posted again in date order, as after a backdated
edit — the cost, the movements and the postings follow today's rules and settings."""

from __future__ import annotations

from datetime import date

from modern_gl.application.inventory.posting import PostingCommands, sequence_key
from modern_gl.application.ledger.module import (
    POSTING_CONTENT,
    changed_documents,
    document_contents,
    rebuild_start,
)
from modern_gl.infrastructure.db import transaction


class RebuildCommands(PostingCommands):
    def rebuild_postings(self, company_id: int, since: date | str) -> list[int]:
        """Post every warehouse document from `since` on (not in the closed period) again;
        the GL documents that changed. Numbers stay; an error rolls everything back."""
        with transaction(self.conn):
            start = rebuild_start(self._company(company_id), since)
            docs = self.conn.execute(
                "SELECT * FROM inventory_documents "
                "WHERE company_id = ? AND status = 'posted' AND doc_date >= ?",
                (company_id, start),
            ).fetchall()
            if not docs:
                return []
            before = self._gl_contents(company_id, start)
            for doc in sorted(docs, key=sequence_key, reverse=True):
                self._withdraw(company_id, doc)
            self._apply_in_order(company_id, None, [doc["id"] for doc in docs])
            return changed_documents(before, self._gl_contents(company_id, start))

    def _gl_contents(self, company_id: int, start: str) -> dict[int, tuple]:
        """What the GL documents of the warehouse documents from `start` on say."""
        return document_contents(
            self.conn.execute(
                "SELECT d.id AS document_id, d.doc_date, d.memo AS doc_memo, "
                f"{POSTING_CONTENT} FROM inventory_documents i "
                "JOIN documents d ON d.company_id = i.company_id "
                "AND (d.id = i.gl_document_id OR d.id IN "
                "(SELECT a.gl_document_id FROM inventory_accruals a WHERE a.document_id = i.id)) "
                "JOIN postings p ON p.document_id = d.id "
                "WHERE i.company_id = ? AND i.doc_date >= ? ORDER BY d.id, p.line_no",
                (company_id, start),
            ),
        )
