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
from modern_gl.domain.dates import ru_date
from modern_gl.domain.errors import ValidationError
from modern_gl.i18n import tr
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

    def _repost_item(self, company_id: int, item_id: int) -> None:
        """Another stock account of an item that has posted documents
        (D202): the warehouse's documents are posted again from the
        item's first one, so all its postings are on the new account — unless one of them
        is in the closed period."""
        with transaction(self.conn):
            first = self.conn.execute(
                "SELECT MIN(d.doc_date) AS day FROM inventory_lines l "
                "JOIN inventory_documents d ON d.company_id = l.company_id "
                "AND d.id = l.document_id "
                "WHERE l.company_id = ? AND l.item_id = ? AND d.status = 'posted'",
                (company_id, item_id),
            ).fetchone()["day"]
            if first is None:
                return
            closed = self._company(company_id)["closed_through"]
            if closed is not None and first <= closed:
                raise ValidationError(
                    tr(
                        "счёт товара менять нельзя: его документы есть в закрытом периоде "
                        "(по {date})",
                        date=ru_date(closed),
                    )
                )
            self.rebuild_postings(company_id, first)

    def _gl_contents(self, company_id: int, start: str) -> dict[int, tuple]:
        """What the GL documents of the warehouse documents from `start` on say."""
        # two plain joins, not one with OR: the OR kept SQLite from the documents' key and
        # it compared every warehouse document with every GL one (10 s on the demo year)
        return document_contents(
            self.conn.execute(
                "WITH gl AS ("
                "  SELECT i.gl_document_id AS id FROM inventory_documents i "
                "  WHERE i.company_id = ? AND i.doc_date >= ? AND i.gl_document_id IS NOT NULL "
                "  UNION "
                "  SELECT a.gl_document_id FROM inventory_documents i "
                "  JOIN inventory_accruals a ON a.company_id = i.company_id "
                "  AND a.document_id = i.id "
                "  WHERE i.company_id = ? AND i.doc_date >= ?"
                ") "
                "SELECT d.id AS document_id, d.doc_date, d.memo AS doc_memo, "
                f"{POSTING_CONTENT} FROM gl "
                "JOIN documents d ON d.company_id = ? AND d.id = gl.id "
                "JOIN postings p ON p.document_id = d.id ORDER BY d.id, p.line_no",
                (company_id, start, company_id, start, company_id),
            ),
        )
