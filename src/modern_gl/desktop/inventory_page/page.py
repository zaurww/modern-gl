"""«Склад»: what is in stock, by item and warehouse; the chosen item's movements and all
the warehouse documents under it."""

from __future__ import annotations

from modern_gl.desktop.inventory_page.documents import DocumentsPart
from modern_gl.desktop.inventory_page.movements import MovementsPart
from modern_gl.desktop.inventory_page.stock import StockPart


class InventoryPage(MovementsPart, DocumentsPart, StockPart):
    pass
