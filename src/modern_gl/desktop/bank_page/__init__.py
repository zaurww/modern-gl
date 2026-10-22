"""«Банк / Bank» (D47, D78): the company's bank accounts, the statements of one, one
statement with its lines; money in or out and a currency conversion start here."""

from __future__ import annotations

from modern_gl.desktop.bank_page.page import BankPage
from modern_gl.desktop.bank_page.settings import BankSettingsDialog

__all__ = ["BankPage", "BankSettingsDialog"]
