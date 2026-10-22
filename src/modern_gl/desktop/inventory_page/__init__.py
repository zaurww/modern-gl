"""«Склад»: balances by item and warehouse, the warehouse documents and compact dialogs."""

from __future__ import annotations

from modern_gl.desktop.inventory_page.dialogs import (
    InventorySettingsDialog,
    ItemDialog,
    open_item,
)
from modern_gl.desktop.inventory_page.page import InventoryPage
from modern_gl.desktop.inventory_page.stock import StockGroup

__all__ = ["InventoryPage", "InventorySettingsDialog", "ItemDialog", "StockGroup", "open_item"]
