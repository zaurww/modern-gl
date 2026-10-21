"""Editable multi-line warehouse document and its posted document card."""

from __future__ import annotations

from modern_gl.desktop.inventory_document_page.columns import (
    ACCOUNT,
    AMOUNT,
    CURRENCY_AMOUNT,
    ESC1,
    EXPENSE,
    ITEM,
    ITEM_MIN,
    MEMO,
    PRICE,
    QUANTITY,
    SALE1,
    SALE2,
    SC1,
    SC2,
    VAT,
    WAREHOUSE,
    InventoryGridRow,
)
from modern_gl.desktop.inventory_document_page.lines_table import NewNamesDialog
from modern_gl.desktop.inventory_document_page.page import InventoryDocumentPage

__all__ = [
    "ACCOUNT",
    "AMOUNT",
    "CURRENCY_AMOUNT",
    "ESC1",
    "EXPENSE",
    "ITEM",
    "ITEM_MIN",
    "MEMO",
    "PRICE",
    "QUANTITY",
    "SALE1",
    "SALE2",
    "SC1",
    "SC2",
    "VAT",
    "WAREHOUSE",
    "InventoryDocumentPage",
    "InventoryGridRow",
    "NewNamesDialog",
]
