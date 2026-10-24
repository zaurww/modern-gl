"""Read-side reports: ОСВ, ОСВ по субконто, карточка счёта, анализ счёта,
анализ и карточка субконто.

Aggregation happens in SQL; Python only folds the (small) account tree.
A book is a list of layer codes: ("common",), ("common", "ifrs_adj"), ("common", "tax_adj").
All amounts are int minor units.
"""

from modern_gl.application.books import COMMON, IFRS, TAX
from modern_gl.reporting.report_common import (
    AccountCard,
    CardLine,
    CorrRow,
    CurrencyRow,
    Osv,
    OsvRow,
    SubcontoAnalysisRow,
    SubcontoCard,
    SubcontoCardLine,
    SubcontoRow,
    Turnovers,
)
from modern_gl.reporting.reports.card import account_analysis, account_card
from modern_gl.reporting.reports.osv import trial_balance
from modern_gl.reporting.reports.subconto import subconto_balance
from modern_gl.reporting.reports.subconto_analysis import subconto_analysis
from modern_gl.reporting.reports.subconto_card import subconto_card

__all__ = [
    "COMMON",
    "IFRS",
    "TAX",
    "AccountCard",
    "CardLine",
    "CorrRow",
    "CurrencyRow",
    "Osv",
    "OsvRow",
    "SubcontoAnalysisRow",
    "SubcontoCard",
    "SubcontoCardLine",
    "SubcontoRow",
    "Turnovers",
    "account_analysis",
    "account_card",
    "subconto_analysis",
    "subconto_balance",
    "subconto_card",
    "trial_balance",
]
