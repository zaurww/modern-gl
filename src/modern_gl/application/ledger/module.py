"""What the modules share (bank, currency conversion, e-qaimə, the warehouse): a module's
write object is built on `ModuleBase` — it holds the ledger and calls it (`self.ledger`,
composition, D162); it is not the ledger, so none of the core's scenarios appear on it.
Its GL documents go through `ModuleDocuments` (`self.documents`): written, built again
and removed only by the module, never by the journal.

Every module that makes GL documents can build them again from its own documents from a
day on (`rebuild_postings`, D101): after a rule is fixed, the books follow the documents.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import date

from modern_gl.application.common import (
    account_kinds,
    batches,
    closed_on,
    company_row,
    fill_subconto,
    write_audit,
)
from modern_gl.application.ledger import Ledger
from modern_gl.application.ledger.base import LedgerBase
from modern_gl.application.ledger.inputs import PostingInput
from modern_gl.application.ledger.posting_record import PostingRecord
from modern_gl.domain.dates import iso_date, next_day, ru_date
from modern_gl.domain.errors import LedgerError, ValidationError
from modern_gl.i18n import tr
from modern_gl.infrastructure.db import Connection, Row, transaction

# what a GL document says, posting by posting — as `DocumentCommands._same_content` compares
POSTING_CONTENT = ", ".join(f"p.{column}" for column in PostingRecord.COLUMNS)


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


class ModuleBase(LedgerBase):
    """What a module's write object starts from: the connection and the author with the
    lookups every write object shares (`LedgerBase`), the ledger it calls for the core's
    scenarios (`self.ledger`) and its GL documents (`self.documents`). `ledger` given —
    the one that holds the module (`ledger.bank`); else a ledger of its own."""

    def __init__(self, conn: Connection, actor: str = "local", ledger: Ledger | None = None):
        super().__init__(conn, actor)
        self.ledger = ledger if ledger is not None else Ledger(conn, actor=actor)
        self.documents = ModuleDocuments(self.ledger)

    def named_subconto(self, company_id: int, account_id: int, name: str) -> tuple[int | None, ...]:
        """The account's subconto filled with an element of this name (an item of other
        income and expenses, a cost item…), made on first use."""
        account = self._account(company_id, account_id)
        kinds = {kind for kind in account_kinds(account) if kind is not None}
        return fill_subconto(
            account, {kind: self._named_value(company_id, kind, name) for kind in kinds}
        )

    def _named_value(self, company_id: int, kind_id: int, name: str) -> int:
        """The element of the directory with this name, made on first use."""
        found = self.conn.execute(
            "SELECT id FROM subconto_values WHERE company_id = ? AND kind_id = ? "
            "AND name = ? AND is_group = 0 ORDER BY active DESC, id LIMIT 1",
            (company_id, kind_id, name),
        ).fetchone()
        return found[0] if found else self.ledger.add_subconto_value(company_id, kind_id, name)


class ModuleDocuments:
    """The GL documents a module makes, over the ledger: the one place that reaches the
    ledger's internals (its door for modules — `ledger/`, not a module); a module itself
    sees only this and the ledger's scenarios."""

    def __init__(self, ledger: Ledger) -> None:
        self.ledger = ledger
        self.conn = ledger.conn

    def new(self, company_id: int, doc_date: date | str, memo: str) -> int:
        """A module's GL document, a draft without postings yet, in the common layer."""
        return self.ledger._insert_document(company_id, doc_date, memo, "common")

    def get(self, company_id: int, doc_id: int) -> Row:
        """The GL document's row (with its layer code); NotFoundError if it is not there."""
        return self.ledger._document(company_id, doc_id)

    def set_header(self, company_id: int, doc_id: int, doc_date: date | str, memo: str) -> None:
        """The date and memo of a draft (its postings are built when it is posted)."""
        self.conn.execute(
            "UPDATE documents SET doc_date = ?, memo = ? WHERE company_id = ? AND id = ?",
            (iso_date(doc_date), memo, company_id, doc_id),
        )

    def require_changeable(self, company_id: int, doc: Row) -> None:
        """Refuse what deleting or changing this posted document would refuse (the closed
        period, another module uses it, a storno of it)."""
        self.ledger._require_changeable(company_id, doc)

    def write(
        self,
        company_id: int,
        doc_id: int,
        doc_date: date | str,
        postings: Sequence[PostingInput],
        memo: str,
    ) -> None:
        """Post the module's GL document anew; a posted one is changed in place (D32) and
        the audit trail keeps what it was, unless nothing changed."""
        ledger = self.ledger
        doc = ledger._document(company_id, doc_id)
        if doc["status"] == "posted":
            if ledger._same_content(doc, doc_date, postings, memo):
                return
            snapshot = ledger._snapshot(doc)
            ledger._rewrite(company_id, doc_id, doc_date, postings, memo, "common")
            ledger._audit(company_id, "document", doc_id, "repost", snapshot)
            return
        self.set_header(company_id, doc_id, doc_date, memo)
        self.conn.execute(
            "DELETE FROM postings WHERE company_id = ? AND document_id = ?", (company_id, doc_id)
        )
        ledger._insert_postings(company_id, doc_id, postings)
        ledger._post(company_id, doc_id)

    def rebuild(
        self,
        company_id: int,
        doc_id: int,
        doc_date: date | str,
        postings: Sequence[PostingInput],
        memo: str,
    ) -> bool:
        """Write a posted module document again from its source; True if it changed.
        A document that may not change (a landed cost uses it…) stops the rebuild."""
        doc = self.ledger._document(company_id, doc_id)
        if self.ledger._same_content(doc, doc_date, postings, memo):
            return False
        self.require_changeable(company_id, doc)
        self.write(company_id, doc_id, doc_date, postings, memo)
        return True

    def rebuild_each[T](
        self,
        company_id: int,
        since: date | str,
        table: str,
        load: Callable[[Sequence[int]], Mapping[int, T]],
        rebuild: Callable[[T], list[int]],
        explain: Callable[[int, str, LedgerError], str],
    ) -> list[int]:
        """`rebuild_postings` of a module: each posted document of `table` (its `id`, the GL
        `document_id`) from `since` on, not in the closed period, in date order goes to
        `rebuild(document)` — the GL documents that changed; `load(ids)` reads the module's
        documents a part at a time, not one by one. An error stops it all and names the
        document: `explain(number, date as the user reads it, error)`."""
        changed: list[int] = []
        with transaction(self.conn):
            start = rebuild_start(company_row(self.conn, company_id), since)
            rows = self.conn.execute(
                f"SELECT m.id, d.number, d.doc_date FROM {table} m JOIN documents d "
                "ON d.company_id = m.company_id AND d.id = m.document_id "
                "WHERE m.company_id = ? AND d.status = 'posted' AND d.doc_date >= ? "
                "ORDER BY d.doc_date, d.number",
                (company_id, start),
            ).fetchall()
            for part in batches(rows):
                documents = load([row["id"] for row in part])
                for row in part:
                    try:
                        changed += rebuild(documents[row["id"]])
                    except LedgerError as exc:
                        message = explain(row["number"], ru_date(row["doc_date"]), exc)
                        raise ValidationError(message) from exc
        return changed

    def unpost(self, company_id: int, doc: Row) -> None:
        """Back to a draft: its postings go (the audit trail keeps them)."""
        if doc["status"] != "posted":
            raise ValidationError(tr("документ №{n} не проведён", n=doc["number"]))
        self.require_changeable(company_id, doc)
        snapshot = self.ledger._snapshot(doc)
        self.conn.execute(
            "UPDATE documents SET status = 'draft', posted_at = NULL "
            "WHERE company_id = ? AND id = ?",
            (company_id, doc["id"]),
        )
        self.conn.execute(
            "DELETE FROM postings WHERE company_id = ? AND document_id = ?",
            (company_id, doc["id"]),
        )
        self._audit(company_id, doc["id"], "unpost", snapshot)

    def remove(self, company_id: int, doc: Row) -> None:
        """The GL document goes with the module's document (a posted one in an open
        period only); the audit trail keeps its content."""
        if doc["status"] == "posted":
            self.require_changeable(company_id, doc)
        snapshot = self.ledger._snapshot(doc)
        if doc["status"] == "posted":  # immutability triggers allow only this path
            self.conn.execute(
                "UPDATE documents SET status = 'draft', posted_at = NULL "
                "WHERE company_id = ? AND id = ?",
                (company_id, doc["id"]),
            )
        self.conn.execute(
            "DELETE FROM documents WHERE company_id = ? AND id = ?", (company_id, doc["id"])
        )
        self._audit(company_id, doc["id"], "delete", snapshot)

    def _audit(self, company_id: int, doc_id: int, action: str, details: dict) -> None:
        write_audit(self.conn, company_id, self.ledger.actor, "document", doc_id, action, details)
