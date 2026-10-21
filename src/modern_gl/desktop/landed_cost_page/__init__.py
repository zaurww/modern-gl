"""«Расходы по партии»: the expenses of a batch of receipts and how they are allocated.

A charge is typed in the document (the carrier's or customs' account, amount, VAT) or is
an existing GL posting (a broker's invoice already on 44…) whose debit moves to stock."""

from __future__ import annotations

from modern_gl.desktop.landed_cost_page.columns import (
    ACCOUNT,
    AMOUNT,
    CURRENCY_AMOUNT,
    RATE,
    SC1,
    SHARE,
    UNIT_COST,
    VAT,
    ChargeRow,
)
from modern_gl.desktop.landed_cost_page.page import LandedCostPage
from modern_gl.desktop.landed_cost_page.pickers import (
    BatchCostDialog,
    cost_source_picker,
    source_label,
)

__all__ = [
    "ACCOUNT",
    "AMOUNT",
    "CURRENCY_AMOUNT",
    "RATE",
    "SC1",
    "SHARE",
    "UNIT_COST",
    "VAT",
    "BatchCostDialog",
    "ChargeRow",
    "LandedCostPage",
    "cost_source_picker",
    "source_label",
]
