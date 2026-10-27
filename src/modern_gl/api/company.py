"""One open company of the API (D130): reading as plain data, writing through `Ledger`."""

from __future__ import annotations

from datetime import date
from typing import Any, TypedDict

from modern_gl.application import queries
from modern_gl.application.exchange import Imported, import_batch, parse_batch
from modern_gl.application.ledger import Ledger
from modern_gl.infrastructure.db import Connection
from modern_gl.reporting import answers
from modern_gl.reporting.exchange import documents_file

API = "API · "  # the author of what the API writes, as «AI · » of the assistant (D82)


class ImportedDocument(TypedDict):
    """A document of the exchange file found in the company (made now or before)."""

    id: str  # the document's id in the exchange file
    number: int  # its number in the company


class ImportProblem(TypedDict):
    """Why a document of the file cannot be imported; nothing is then written."""

    id: str
    message: str


class ImportAnswer(TypedDict):
    """What `Company.import_documents` answers (docs/API.md)."""

    ok: bool
    new: list[str]  # ids of the documents made now (or to be made: `check`)
    created: list[ImportedDocument]
    existing: list[ImportedDocument]
    errors: list[ImportProblem]


class Company:
    def __init__(self, conn: Connection, company_id: int, actor: str, read_only: bool) -> None:
        self._conn = conn
        self._company_id = company_id
        self._actor = API + (actor or "script")
        self.read_only = read_only

    @property
    def name(self) -> str:
        return queries.company_name(self._conn, self._company_id)

    def chart_of_accounts(self) -> dict[str, Any]:
        """{"accounts": [{"code", "name", "group", "parent", "class", "type", …}]}."""
        return answers.chart_of_accounts(self._conn, self._company_id)

    def trial_balance(self, date_from: str, date_to: str, book: str = "common") -> dict[str, Any]:
        """ОСВ of the period in a book ("common", "ifrs", "tax"): rows with opening,
        turnover and closing as {"debit", "credit"}, and the total."""
        return answers.trial_balance(self._conn, self._company_id, date_from, date_to, book)

    def export_documents(
        self, date_from: date | str, date_to: date | str, book: str = "common"
    ) -> dict[str, Any]:
        """The posted documents of the period as an exchange file (docs/EXCHANGE.md)."""
        return documents_file(self._conn, self._company_id, date_from, date_to, book)

    def import_documents(
        self, data: object, *, post: bool = False, check: bool = False
    ) -> ImportAnswer:
        """An exchange file (decoded JSON, docs/EXCHANGE.md) into the company: drafts, or
        posted documents with `post`; `check` — only say what would happen. All or
        nothing; a document imported before from the same source is left as it is.
        A file of a wrong shape — FormatError; a company opened without `write` —
        ReadOnlyError."""
        batch = parse_batch(data)
        ledger = Ledger(self._conn, actor=self._actor)
        outcome = import_batch(ledger, self._company_id, batch, post=post, check_only=check)
        return {
            "ok": outcome.ok,
            "new": outcome.new,
            "created": [_imported(d) for d in outcome.created],
            "existing": [_imported(d) for d in outcome.existing],
            "errors": [{"id": e, "message": m} for e, m in outcome.errors],
        }


def _imported(d: Imported) -> ImportedDocument:
    return {"id": d.external_id, "number": d.number}
