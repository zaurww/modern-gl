"""The other side of a bank statement's line, as the bank names it: its VÖEN and its name.

The bank's spelling is a hint, not a name: a file never adds a counterparty to the
directory — the official name comes from the tax portal with an e-qaimə, a person adds
one knowingly. The sender is found by its VÖEN in the directory, a sender without one by
exactly its name; else as last time — the counterparty a person gave a line of the same
sender. Not found, the line waits as a draft that keeps the VÖEN and the name."""

from __future__ import annotations

from modern_gl.application.counterparties import known_counterparty
from modern_gl.i18n import fold, tr
from modern_gl.infrastructure.db import Connection


def unknown_party_text(tin: str, name: str) -> str:
    """Why a line waits: whom the bank names, for a person to add or to find."""
    if tin:
        return tr("контрагента нет в справочнике: {name}, VÖEN {tin}", name=name, tin=tin)
    if name:
        return tr("контрагента нет в справочнике: {name}", name=name)
    return tr("контрагент в выписке не назван")


def statement_party(conn: Connection, company_id: int, tin: str, name: str) -> int | None:
    """The counterparty of a statement's sender: of the directory, else as last time."""
    found = known_counterparty(conn, company_id, tin, name)
    return found if found is not None else _as_last_time(conn, company_id, tin, name)


def _as_last_time(conn: Connection, company_id: int, tin: str, name: str) -> int | None:
    """The counterparty of the latest operation of the same sender: by the VÖEN, a
    sender without one by its name (case, spaces and İ/ı apart)."""
    latest = (
        "SELECT o.counterparty_id, o.party_name FROM bank_operations o "
        "JOIN documents d ON d.company_id = o.company_id AND d.id = o.document_id "
        "WHERE o.company_id = ? AND o.counterparty_id IS NOT NULL AND {same} "
        "ORDER BY d.doc_date DESC, d.number DESC"
    )
    if tin:
        row = conn.execute(
            latest.format(same="o.party_tin = ?") + " LIMIT 1", (company_id, tin)
        ).fetchone()
        return row["counterparty_id"] if row else None
    wanted = _plain(name)
    if not wanted:
        return None
    rows = conn.execute(
        latest.format(same="o.party_tin = '' AND o.party_name <> ''"), (company_id,)
    )
    return next((r["counterparty_id"] for r in rows if _plain(r["party_name"]) == wanted), None)


def _plain(name: str) -> str:
    return fold(" ".join(name.split()))
