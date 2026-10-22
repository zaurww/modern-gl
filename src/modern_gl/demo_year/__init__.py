"""A demo company with a whole year of work (2026): documents on every day, in every
module — opening balances, the bank with the ƏDV deposit account, currency and its
revaluation, conversion, stock with an import and landed cost, sales, salaries, the
e-qaimə portal, parallel books, a storno, drafts and a closed half-year.

The names and texts are Azerbaijani, as the company would keep them. The same seed makes
the same year every time."""

from __future__ import annotations

from modern_gl.application.ledger import Ledger
from modern_gl.demo_year.year import Year

NAME = "Xəzər Ofis MMC (demo 2026)"


def create_year_demo(ledger: Ledger, name: str = NAME) -> int:
    year = Year(ledger, name)
    year.run()
    return year.cid
