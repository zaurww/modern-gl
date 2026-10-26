"""The warehouse's reports (D-new): the statement of a period, an item's card, the gross
profit by item — on the common report table, opened from «Все отчёты» and from «Склад»."""

from modern_gl.desktop.stock_reports.card import ItemCardPage
from modern_gl.desktop.stock_reports.profit import GrossProfitPage
from modern_gl.desktop.stock_reports.statement import StockStatementPage

__all__ = ["GrossProfitPage", "ItemCardPage", "StockStatementPage"]
