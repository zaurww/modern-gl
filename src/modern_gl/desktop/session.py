from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date

from modern_gl.application.catalog import Catalog
from modern_gl.application.ledger import Ledger
from modern_gl.application.queries import company_mode, list_layers, parallel_books
from modern_gl.domain.company import STOCK_ONLY
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
    # official rates of a day {code: (rate, nominal)}; tests put a stub here (no network)
    fetch_rates: Callable[[date], dict[str, tuple[int, int]]] = cbar.fetch

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
