from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject

from modern_gl.application.catalog import Catalog
from modern_gl.application.ledger import Ledger
from modern_gl.application.queries import company_mode, list_layers, parallel_books
from modern_gl.desktop.background import Background
from modern_gl.domain.company import STOCK_ONLY
from modern_gl.domain.errors import LedgerError
from modern_gl.infrastructure import cbar
from modern_gl.infrastructure.db import Connection


@dataclass
class Session:
    """Everything a page needs about the open company."""

    conn: Connection
    ledger: Ledger
    company_id: int
    company_name: str
    catalog: Catalog
    working_date: date = field(default_factory=date.today)  # 1C "рабочая дата"
    read_only: bool = False  # open for viewing (D80): a snapshot, nothing is written
    notify: Callable[[str], None] = print
    # the window's toast with «Undo»; without it the message alone is told (tests)
    notify_undo: Callable[[str, Callable[[], None]], None] | None = None
    # the company's file and its size: a large one is read in the background (debt 6)
    path: Path | None = None
    large: bool = False
    background: Background = field(default_factory=Background)
    # official rates of a day {code: (rate, nominal)}; tests put a stub here (no network)
    fetch_rates: Callable[[date], dict[str, tuple[int, int]]] = cbar.fetch

    def read(
        self,
        owner: QObject,
        job: Callable[[Connection], Any],
        done: Callable[[Any], None],
        failed: Callable[[LedgerError], None],
    ) -> bool:
        """Read `job` for `owner` — in the background for a large company's file (the
        result comes to `done` later, True is returned), at once otherwise."""
        path = None if self.read_only else self.path  # viewing: a snapshot in memory
        return self.background.run(owner, self.conn, path, self.large, job, done, failed)

    def notify_undoable(self, message: str, undo: Callable[[], None]) -> None:
        """What was just done, and how to take it back (a toast's «Undo», D86)."""
        if self.notify_undo is None:
            self.notify(message)
        else:
            self.notify_undo(message, undo)

    @property
    def layers(self) -> list[tuple[str, str]]:
        return list_layers(self.conn, self.company_id)

    @property
    def parallel_books(self) -> bool:
        return parallel_books(self.conn, self.company_id)

    @property
    def stock_only(self) -> bool:
        """Only the warehouse is kept here (D90): the books, their pages and accounts are
        not shown; the postings are made all the same."""
        return company_mode(self.conn, self.company_id) == STOCK_ONLY
