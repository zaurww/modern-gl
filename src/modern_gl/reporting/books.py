"""Сравнение книг (D98): each account's balance on a day in the common, IFRS and tax books
and the differences between them. A book is the common layer plus its adjustments (D7),
so a difference is the adjustment layer itself — nothing is matched or guessed.

Balances are net (debit − credit, minor units); groups sum their children."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date

from modern_gl.domain.dates import iso_date
from modern_gl.infrastructure.db import Connection, Row
from modern_gl.reporting.report_common import _accounts, docs_cte

ADJUSTMENTS = ("ifrs_adj", "tax_adj")


@dataclass
class BookRow:
    account_id: int = 0
    code: str = ""
    name: str = ""
    depth: int = 0
    is_group: bool = False
    common: int = 0  # the common book's balance
    ifrs_adj: int = 0  # what IFRS adjusts: the IFRS book = common + this
    tax_adj: int = 0

    @property
    def ifrs(self) -> int:
        return self.common + self.ifrs_adj

    @property
    def tax(self) -> int:
        return self.common + self.tax_adj

    @property
    def differs(self) -> bool:
        return bool(self.ifrs_adj or self.tax_adj)

    def add(self, other: BookRow) -> None:
        self.common += other.common
        self.ifrs_adj += other.ifrs_adj
        self.tax_adj += other.tax_adj


def compare_books(
    conn: Connection, company_id: int, day: date | str, only_differences: bool = False
) -> list[BookRow]:
    """Every account with a balance in some book on the day, in the order of the chart;
    `only_differences` — those where IFRS or tax differ from the common book."""
    balances = _balances(conn, company_id, iso_date(day))
    accounts = _accounts(conn, company_id)
    children: dict[int | None, list[int]] = defaultdict(list)
    for a in accounts.values():  # already ordered by code
        children[a["parent_id"]].append(a["id"])
    rows: list[BookRow] = []

    def visit(account_id: int, depth: int) -> BookRow:
        acc: Row = accounts[account_id]
        row = BookRow(account_id, acc["code"] or "", acc["name"], depth, bool(acc["is_group"]))
        position = len(rows)
        rows.append(row)
        own = balances.get(account_id)
        if own is not None:
            row.add(own)
        for child in children[account_id]:
            row.add(visit(child, depth + 1))
        silent = not (row.common or row.differs)
        if silent or (only_differences and not row.differs):
            del rows[position:]
        return row

    for top in children[None]:
        visit(top, 0)
    return rows


def _balances(conn: Connection, company_id: int, day: str) -> dict[int, BookRow]:
    """Each account's own balance (not its children's) per layer, posted up to the day."""
    found: dict[int, BookRow] = {}
    for r in conn.execute(
        f"""
        WITH {docs_cte("d.id, l.code AS layer", every_layer=True)},
        moves AS (
            SELECT p.debit_account_id AS account_id, docs.layer, p.amount AS net
            FROM postings p JOIN docs ON docs.id = p.document_id
            WHERE p.company_id = :company_id
            UNION ALL
            SELECT p.credit_account_id, docs.layer, -p.amount
            FROM postings p JOIN docs ON docs.id = p.document_id
            WHERE p.company_id = :company_id
        )
        SELECT account_id, layer, SUM(net) AS net FROM moves GROUP BY account_id, layer
        """,
        {"company_id": company_id, "date_to": day},
    ):
        row = found.setdefault(r["account_id"], BookRow(r["account_id"]))
        layer = r["layer"]
        if layer in ADJUSTMENTS:
            setattr(row, layer, getattr(row, layer) + r["net"])
        elif layer == "common":
            row.common += r["net"]
    return found
