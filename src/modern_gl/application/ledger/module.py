"""What documents of modules share (currency conversion, bank operations): their GL
documents are written and removed only by them, never by the journal.

Every module that makes GL documents can build them again from its own documents from a
day on (`rebuild_postings`, D101): after a rule is fixed, the books follow the documents.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from datetime import date

from modern_gl.application.common import closed_on
from modern_gl.application.ledger.chart import ChartCommands
from modern_gl.application.ledger.documents import DocumentCommands
from modern_gl.application.ledger.inputs import PostingInput
from modern_gl.domain.dates import iso_date, next_day, ru_date
from modern_gl.domain.errors import LedgerError, ValidationError
from modern_gl.infrastructure.db import Row, transaction

# what a GL document says, posting by posting — as `DocumentCommands._same_content` compares
POSTING_CONTENT = (
    "p.debit_account_id, p.credit_account_id, p.amount, p.dt_sc1, p.dt_sc2, p.dt_sc3, "
    "p.ct_sc1, p.ct_sc2, p.ct_sc3, p.memo, p.currency_id, p.currency_amount, p.invoice, "
    "p.invoice_kind"
)


def rebuild_start(company: Row, since: date | str) -> str:
    """The first day a rebuild may change (ISO): `since`, or the day after the closed
    period — what is closed stays as it is (D5)."""
    day = iso_date(since)
    return next_day(company["closed_through"]) if closed_on(company, day) else day


def document_contents(rows: Iterable[Row]) -> dict[int, tuple]:
    """(date, memo, postings) of each GL document, from rows whose columns are
    `document_id`, `doc_date`, `doc_memo`, then `POSTING_CONTENT`, ordered by line."""
    contents: dict[int, tuple] = {}
    for row in rows:
        doc_id = row["document_id"]
        _, _, postings = contents.setdefault(doc_id, (row["doc_date"], row["doc_memo"], []))
        postings.append(tuple(row)[3:])
    return contents


def changed_documents(before: dict[int, tuple], after: dict[int, tuple]) -> list[int]:
    """GL documents whose date, memo or postings differ (made or removed ones too)."""
    return sorted(i for i in before.keys() | after.keys() if before.get(i) != after.get(i))


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
                "AND name = ? AND is_group = 0 ORDER BY active DESC, id LIMIT 1",
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

    def _rebuild_each(
        self,
        company_id: int,
        since: date | str,
        table: str,
        rebuild: Callable[[int], list[int]],
        explain: Callable[[int, str, LedgerError], str],
    ) -> list[int]:
        """`rebuild_postings` of a module: each posted document of `table` (its `id`, the GL
        `document_id`) from `since` on, not in the closed period, in date order goes to
        `rebuild(id)` — the GL documents that changed. An error stops it all and names the
        document: `explain(number, date as the user reads it, error)`."""
        changed: list[int] = []
        with transaction(self.conn):
            start = rebuild_start(self._company(company_id), since)
            for row in self.conn.execute(
                f"SELECT m.id, d.number, d.doc_date FROM {table} m JOIN documents d "
                "ON d.company_id = m.company_id AND d.id = m.document_id "
                "WHERE m.company_id = ? AND d.status = 'posted' AND d.doc_date >= ? "
                "ORDER BY d.doc_date, d.number",
                (company_id, start),
            ).fetchall():
                try:
                    changed += rebuild(row["id"])
                except LedgerError as exc:
                    message = explain(row["number"], ru_date(row["doc_date"]), exc)
                    raise ValidationError(message) from exc
        return changed

    def _rebuild_module_document(
        self,
        company_id: int,
        doc_id: int,
        doc_date: date | str,
        postings: Sequence[PostingInput],
        memo: str,
    ) -> bool:
        """Write a posted module document again from its source; True if it changed.
        A document that may not change (a landed cost uses it…) stops the rebuild."""
        doc = self._document(company_id, doc_id)
        if self._same_content(doc, doc_date, postings, memo):
            return False
        self._require_changeable(company_id, doc)
        self._write_module_document(company_id, doc_id, doc_date, postings, memo)
        return True

    def _remove_document(self, company_id: int, doc: Row) -> None:
        snapshot = self._snapshot(doc)
        if doc["status"] == "posted":  # immutability triggers allow only this path
            self.conn.execute(
                "UPDATE documents SET status = 'draft', posted_at = NULL WHERE id = ?",
                (doc["id"],),
            )
        self.conn.execute("DELETE FROM documents WHERE id = ?", (doc["id"],))
        self._audit(company_id, "document", doc["id"], "delete", snapshot)
