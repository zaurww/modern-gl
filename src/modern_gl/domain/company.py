"""How a company is kept (D90): the whole program, or only the warehouse."""

from __future__ import annotations

FULL = "full"
STOCK_ONLY = "stock"  # the warehouse, purchases and sales; the books are kept unseen
COMPANY_MODES = (FULL, STOCK_ONLY)
