"""«Сменить счёт у отмеченных» in the journal (D225): the postings of
the journal's own documents on one account go to another."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace

from modern_gl.application.common import moved_subconto
from modern_gl.application.ledger.documents import DocumentCommands
from modern_gl.application.ledger.posting_record import PostingRecord
from modern_gl.domain.errors import ValidationError
from modern_gl.i18n import tr
from modern_gl.infrastructure.db import Row, transaction


class AccountChangeCommands(DocumentCommands):
    """The account of many documents' postings changed in one step."""

    def change_posting_account(
        self, company_id: int, doc_ids: Sequence[int], old_id: int, new_id: int
    ) -> int:
        """The postings of these documents on `old_id` (either side) go to `new_id`: each
        document keeps its number and status, a posted one is posted again (D32) — all of
        them or none. A subconto of the same directory stays. A document without the
        account is left as it is; one a module made is refused. How many changed."""
        old, new = self._account(company_id, old_id), self._account(company_id, new_id)
        changed = 0
        with transaction(self.conn):
            for doc_id in doc_ids:
                doc = self._document(company_id, doc_id)
                records = [PostingRecord.from_row(p) for p in self._posting_rows(doc_id)]
                moved = [_moved(r, old, new) for r in records]
                if moved == records:
                    continue
                self._require_not_module_document(company_id, doc)
                self._replace_records(company_id, doc, moved)
                changed += 1
        return changed

    def _replace_records(self, company_id: int, doc: Row, records: list[PostingRecord]) -> None:
        posted = doc["status"] == "posted"
        snapshot = self._snapshot(doc)
        if posted:
            if doc["reversal_of"] is not None:
                raise ValidationError(
                    tr("сторно №{n} нельзя изменить, его можно только удалить", n=doc["number"])
                )
            self._require_changeable(company_id, doc)
            self.conn.execute(  # a posted document changes only by becoming a draft first
                "UPDATE documents SET status = 'draft', posted_at = NULL "
                "WHERE company_id = ? AND id = ?",
                (company_id, doc["id"]),
            )
        self.conn.execute(
            "DELETE FROM postings WHERE company_id = ? AND document_id = ?",
            (company_id, doc["id"]),
        )
        self._insert_records(company_id, doc["id"], records)
        if posted:
            self._post(company_id, doc["id"])
        self._audit(
            company_id, "document", doc["id"], "repost" if posted else "update_draft", snapshot
        )


def _moved(record: PostingRecord, old: Row, new: Row) -> PostingRecord:
    """The posting with each side on the old account taken to the new one."""
    if record.debit_account_id == old["id"]:
        sc = moved_subconto(old, new, (record.dt_sc1, record.dt_sc2, record.dt_sc3))
        record = replace(
            record, debit_account_id=new["id"], dt_sc1=sc[0], dt_sc2=sc[1], dt_sc3=sc[2]
        )
    if record.credit_account_id == old["id"]:
        sc = moved_subconto(old, new, (record.ct_sc1, record.ct_sc2, record.ct_sc3))
        record = replace(
            record, credit_account_id=new["id"], ct_sc1=sc[0], ct_sc2=sc[1], ct_sc3=sc[2]
        )
    return record
