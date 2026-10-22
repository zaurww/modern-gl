"""«Склад»: what is in stock, by item and warehouse, and the warehouse documents."""

from __future__ import annotations

from modern_gl.desktop.inventory_page.documents import DocumentsPart
from modern_gl.desktop.inventory_page.stock import StockPart


class InventoryPage(DocumentsPart, StockPart):
    pass
