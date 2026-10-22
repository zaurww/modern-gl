"""Quantitative/value inventory use cases and landed-cost allocation.

Quantities live in a separate immutable movement register. Every posted inventory
document creates an ordinary GL document in the same SQLite transaction.
"""

from __future__ import annotations

from modern_gl.application.inventory.amounts import (
    allocate_minor,
    format_quantity,
    split_charges,
    to_quantity,
    vat_of,
)
from modern_gl.application.inventory.catalog import CatalogCommands
from modern_gl.application.inventory.model import (
    ACCRUED_CODE,
    ALLOCATION_METHODS,
    INCOMING_REASONS,
    INCOMING_TYPES,
    QUANTITY_FACTOR,
    QUANTITY_SCALE,
    SALE_ROLE_NAMES,
    STANDARD_VAT_RATE,
    VAT_RATE_SCALE,
    InventoryDocumentData,
    InventoryLineData,
    IssueLine,
    LandedCostCharge,
    LandedCostChargeData,
    LandedCostTarget,
    ReceiptLine,
    SaleLine,
    TransferLine,
)
from modern_gl.application.inventory.posting import PostingCommands

__all__ = [
    "ACCRUED_CODE",
    "ALLOCATION_METHODS",
    "INCOMING_REASONS",
    "INCOMING_TYPES",
    "QUANTITY_FACTOR",
    "QUANTITY_SCALE",
    "SALE_ROLE_NAMES",
    "STANDARD_VAT_RATE",
    "VAT_RATE_SCALE",
    "Inventory",
    "InventoryDocumentData",
    "InventoryLineData",
    "IssueLine",
    "LandedCostCharge",
    "LandedCostChargeData",
    "LandedCostTarget",
    "ReceiptLine",
    "SaleLine",
    "TransferLine",
    "allocate_minor",
    "format_quantity",
    "split_charges",
    "to_quantity",
    "vat_of",
]


class Inventory(CatalogCommands, PostingCommands):
    """Write-side API for inventory catalogs, movements and landed cost; each group
    lives in its own module."""
