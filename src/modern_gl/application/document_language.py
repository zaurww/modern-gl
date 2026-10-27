"""The language a company's documents are written in (D152): the texts the program puts
into postings itself («Bank komissiyası» / «Комиссия банка») are `i18n.trd`, in this
language whatever the interface is. A new company writes in Azerbaijani; a file of an older
program has no setting — the texts it holds tell which language they were written in."""

from __future__ import annotations

from modern_gl.application.ledger import Ledger
from modern_gl.i18n import language, set_document_language
from modern_gl.i18n_az import AZ
from modern_gl.infrastructure.db import Connection

# Texts an older program wrote in the interface language: which of them a file holds more
# of tells its language
_WRITTEN = ("НДС", "Комиссия банка", "Курсовая разница при конвертации")


def stored(conn: Connection, company_id: int) -> str | None:
    row = conn.execute(
        "SELECT document_language FROM companies WHERE id = ?", (company_id,)
    ).fetchone()
    return None if row is None else row[0]


def guess(conn: Connection, company_id: int) -> str:
    """The language of the texts a file of an older program holds; none — the interface's."""
    counts = {}
    for code, texts in (("ru", _WRITTEN), ("az", tuple(AZ[t] for t in _WRITTEN))):
        marks = ", ".join("?" * len(texts))
        counts[code] = conn.execute(
            f"SELECT COUNT(*) FROM postings WHERE company_id = ? AND memo IN ({marks})",
            (company_id, *texts),
        ).fetchone()[0]
    if counts["az"] == counts["ru"]:
        return language()
    return max(counts, key=lambda code: counts[code])


def resolve(conn: Connection, company_id: int) -> str:
    return stored(conn, company_id) or guess(conn, company_id)


def open_in(conn: Connection, company_id: int, write: bool) -> str:
    """Make a company's language the one documents are written in; a file without the
    setting (`write`: not a snapshot for viewing) keeps what its texts tell, once."""
    code = resolve(conn, company_id)
    if write and stored(conn, company_id) is None:
        Ledger(conn).set_document_language(company_id, code)
    set_document_language(code)
    return code
