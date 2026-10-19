from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date

from modern_gl.application.catalog import Catalog
from modern_gl.application.ledger import Ledger
from modern_gl.application.queries import list_layers


@dataclass
class Session:
    """Everything a page needs about the open company."""

    conn: sqlite3.Connection
    ledger: Ledger
    company_id: int
    company_name: str
    catalog: Catalog
    working_date: date = field(default_factory=date.today)  # 1C "рабочая дата"
    notify: Callable[[str], None] = print

    @property
    def layers(self) -> list[tuple[str, str]]:
        return list_layers(self.conn, self.company_id)
