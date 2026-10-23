"""Building the books again from the documents of the modules (D101).

A module that makes GL documents (`document_owners`, role 'made') can make them again
from its own documents from a day on: `rebuild_postings(company_id, since)` returns the
GL documents that changed. After a rule or a setting is fixed, the books follow the
documents; the closed period stays as it is. `tests/test_rebuild.py` holds every module
to it: a rebuild of what was just posted changes nothing."""

from __future__ import annotations

from datetime import date
from typing import Protocol

from modern_gl.application.inventory import Inventory
from modern_gl.application.ledger import Ledger
from modern_gl.infrastructure.db import transaction


class Rebuilder(Protocol):
    def rebuild_postings(self, company_id: int, since: date | str) -> list[int]: ...


def module_rebuilders(ledger: Ledger) -> dict[str, Rebuilder]:
    """Each module that makes GL documents, by its name in `document_owners`."""
    return {
        "bank": ledger.bank,
        "conversion": ledger.conversion,
        "inventory": Inventory(ledger.conn, ledger.actor),
    }


def rebuild_postings(ledger: Ledger, company_id: int, since: date | str) -> list[int]:
    """Every module's GL documents from `since` on, in one transaction; the ones that
    changed. An error names the document and leaves the books as they were."""
    changed: list[int] = []
    with transaction(ledger.conn):
        for module in module_rebuilders(ledger).values():
            changed += module.rebuild_postings(company_id, since)
    return changed
