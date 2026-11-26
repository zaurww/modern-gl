"""«Сменить счёт у отмеченных» for purchases (D225): the lines of a
purchase without an item (a service, an expense) on one account go to another, and the
account the lines are owed on."""

from __future__ import annotations

from collections.abc import Sequence

from modern_gl.application.common import moved_subconto
from modern_gl.application.inventory.posting import PostingCommands
from modern_gl.infrastructure.db import Row, transaction


class LineAccountCommands(PostingCommands):
    def change_line_account(
        self, company_id: int, document_ids: Sequence[int], old_id: int, new_id: int
    ) -> int:
        """In these purchases the lines without an item on `old_id` go to `new_id`, and so
        does what is owed on `old_id`: each purchase keeps its number and status, a posted
        one is posted again in place — all of them or none. A subconto of the same
        directory stays. A line of goods keeps its item's account; a document that is not
        a purchase, or has no such line, is left as it is. How many changed."""
        old, new = self._account(company_id, old_id), self._account(company_id, new_id)
        changed = 0
        with transaction(self.conn):
            for document_id in dict.fromkeys(document_ids):
                doc = self._inventory_document(company_id, document_id)
                if doc["doc_type"] != "receipt" or not self._lines_on(company_id, doc, old_id):
                    continue
                if doc["status"] == "posted":
                    with self.reposting(company_id, document_id):
                        self._move_lines(company_id, doc, old, new)
                else:
                    self._move_lines(company_id, doc, old, new)
                self._audit(
                    company_id,
                    "inventory_document",
                    document_id,
                    "change_account",
                    {"old_account_id": old_id, "new_account_id": new_id},
                )
                changed += 1
        return changed

    def _lines_on(self, company_id: int, doc: Row, account_id: int) -> list[Row]:
        return self.conn.execute(
            "SELECT id, item_id, cost_account_id, cost_sc1, cost_sc2, cost_sc3, "
            "offset_account_id, offset_sc1, offset_sc2, offset_sc3 FROM inventory_lines "
            "WHERE company_id = ? AND document_id = ? AND (offset_account_id = ? "
            "OR (item_id IS NULL AND cost_account_id = ?)) ORDER BY line_no",
            (company_id, doc["id"], account_id, account_id),
        ).fetchall()

    def _move_lines(self, company_id: int, doc: Row, old: Row, new: Row) -> None:
        for line in self._lines_on(company_id, doc, old["id"]):
            if line["item_id"] is None and line["cost_account_id"] == old["id"]:
                sc = moved_subconto(old, new, [line[f"cost_sc{i}"] for i in (1, 2, 3)])
                self.conn.execute(
                    "UPDATE inventory_lines SET cost_account_id = ?, cost_sc1 = ?, cost_sc2 = ?, "
                    "cost_sc3 = ? WHERE company_id = ? AND id = ?",
                    (new["id"], *sc, company_id, line["id"]),
                )
            if line["offset_account_id"] == old["id"]:
                sc = moved_subconto(old, new, [line[f"offset_sc{i}"] for i in (1, 2, 3)])
                self.conn.execute(
                    "UPDATE inventory_lines SET offset_account_id = ?, offset_sc1 = ?, "
                    "offset_sc2 = ?, offset_sc3 = ? WHERE company_id = ? AND id = ?",
                    (new["id"], *sc, company_id, line["id"]),
                )
