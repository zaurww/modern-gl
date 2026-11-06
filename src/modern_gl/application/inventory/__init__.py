"""Quantitative/value inventory use cases and landed-cost allocation.

Quantities live in a separate immutable movement register. Every posted inventory
document creates an ordinary GL document in the same SQLite transaction.
"""

from __future__ import annotations

from modern_gl.application.inventory.amounts import (
    allocate_charges,
    allocate_minor,
    format_quantity,
    line_amount,
    split_charges,
    to_quantity,
    unit_price,
    vat_of,
)
from modern_gl.application.inventory.awaiting import AwaitingCommands
from modern_gl.application.inventory.defaults import default_vat_rate, line_vat
from modern_gl.application.inventory.model import (
    ACCRUED_CODE,
    ALLOCATION_METHODS,
    INCOMING_REASONS,
    INCOMING_TYPES,
    PURCHASE_RETURN,
    QUANTITY_FACTOR,
    QUANTITY_SCALE,
    RETURN_TYPES,
    SALE_RETURN,
    SALE_ROLE_NAMES,
    STANDARD_VAT_RATE,
    USUAL_UNITS,
    VAT_DOCUMENTS,
    VAT_RATE_SCALE,
    AccrualData,
    InventoryDocumentData,
    InventoryLineData,
    IssueLine,
    LandedCostCharge,
    LandedCostChargeData,
    LandedCostTarget,
    NewItem,
    ReceiptHeader,
    ReceiptLine,
    ReturnLine,
    SaleLine,
    TransferLine,
    UsualUnit,
)
from modern_gl.application.inventory.rebuild import RebuildCommands
from modern_gl.application.inventory.stock import StockShortageError
from modern_gl.application.inventory.stock_count import (
    CountedLine,
    StockCountCommands,
    StockCountResult,
)

__all__ = [
    "ACCRUED_CODE",
    "ALLOCATION_METHODS",
    "INCOMING_REASONS",
    "INCOMING_TYPES",
    "PURCHASE_RETURN",
    "QUANTITY_FACTOR",
    "QUANTITY_SCALE",
    "RETURN_TYPES",
    "SALE_RETURN",
    "SALE_ROLE_NAMES",
    "STANDARD_VAT_RATE",
    "USUAL_UNITS",
    "VAT_DOCUMENTS",
    "VAT_RATE_SCALE",
    "AccrualData",
    "CountedLine",
    "Inventory",
    "InventoryDocumentData",
    "InventoryLineData",
    "IssueLine",
    "LandedCostCharge",
    "LandedCostChargeData",
    "LandedCostTarget",
    "NewItem",
    "ReceiptHeader",
    "ReceiptLine",
    "ReturnLine",
    "SaleLine",
    "StockCountResult",
    "StockShortageError",
    "TransferLine",
    "UsualUnit",
    "allocate_charges",
    "allocate_minor",
    "default_vat_rate",
    "format_quantity",
    "line_amount",
    "line_vat",
    "split_charges",
    "to_quantity",
    "unit_price",
    "vat_of",
]


class Inventory(StockCountCommands, AwaitingCommands, RebuildCommands):
    """Write-side API for inventory catalogs, movements and landed cost; each group
    lives in its own module."""
