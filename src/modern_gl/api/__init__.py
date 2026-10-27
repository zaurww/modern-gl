"""Modern GL for developers (D130, docs/API.md): the small surface a script or another
program uses. What is here changes only with API_VERSION; everything outside
`modern_gl.api` is the program's own and may change in any release.

    from modern_gl.api import open_company

    with open_company("Xəzər Ofis MMC.gl") as company:
        osv = company.trial_balance("2026-01-01", "2026-03-31")

    with open_company("Xəzər Ofis MMC.gl", write=True, actor="etax-ext") as company:
        result = company.import_documents(json.load(open("march.json")))

Answers are plain data (dict, list, str), ready for JSON: amounts are strings in manat
with two decimals ("1234.50"), dates ISO. A company is read from a snapshot unless
`write=True`; everything written goes through the program's own rules (the same checks,
the audit trail with `actor` as the author, D82) — there is no other way in.
"""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

from modern_gl.api.company import Company
from modern_gl.application.exchange import FormatError
from modern_gl.application.workspace import Workspace
from modern_gl.domain.errors import LedgerError, ReadOnlyError

API_VERSION = 1

__all__ = [
    "API_VERSION",
    "Company",
    "FormatError",
    "LedgerError",
    "ReadOnlyError",
    "open_company",
]


@contextmanager
def open_company(path: str | Path, *, write: bool = False, actor: str = "") -> Generator[Company]:
    """A company file. Without `write` — a snapshot: the file is not changed and may be
    open in the program at the same time. With `write` the file itself: a file of an
    older schema is backed up and updated first, as the program does."""
    path = Path(path)
    workspace = Workspace(path.parent)
    conn, company_id = workspace.open(path, lock=False) if write else workspace.view(path)
    try:
        yield Company(conn, company_id, actor, read_only=not write)
    finally:
        conn.close()
