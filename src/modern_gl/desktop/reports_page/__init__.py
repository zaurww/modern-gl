"""Report pages: ОСВ, карточка счёта, ОСВ по субконто, анализ счёта, анализ и
карточка субконто, план счетов.

Every report = parameters bar + one calm table + footer. Drill-down by double click.
"""

from __future__ import annotations

from modern_gl.desktop.reports_page.account import REPORTS, CardPage, SubcontoPage
from modern_gl.desktop.reports_page.books import BooksPage
from modern_gl.desktop.reports_page.chart import ChartPage
from modern_gl.desktop.reports_page.osv import OsvPage
from modern_gl.desktop.reports_page.report_table import NAME_MIN, ReportTable
from modern_gl.desktop.reports_page.statements import StatementsPage
from modern_gl.desktop.reports_page.subconto_analysis import SubcontoAnalysisPage
from modern_gl.desktop.reports_page.subconto_card import SubcontoCardPage
from modern_gl.desktop.reports_page.table import (
    NAME_MAX,
    SectionRow,
    figure,
)
from modern_gl.desktop.reports_page.vat_credit import VatCreditPage
from modern_gl.desktop.reports_page.vat_liability import VatLiabilityPage
from modern_gl.desktop.reports_page.vat_register import VatRegisterPage
from modern_gl.desktop.reports_page.view import (
    Column,
    MenuAction,
    ReportModel,
    ReportPage,
    ReportParams,
    month_of,
)

REPORTS["subconto_card"] = SubcontoCardPage  # from «Анализ субконто» (D126)

__all__ = [
    "NAME_MAX",
    "NAME_MIN",
    "REPORTS",
    "BooksPage",
    "CardPage",
    "ChartPage",
    "Column",
    "MenuAction",
    "OsvPage",
    "ReportModel",
    "ReportPage",
    "ReportParams",
    "ReportTable",
    "SectionRow",
    "StatementsPage",
    "SubcontoAnalysisPage",
    "SubcontoCardPage",
    "SubcontoPage",
    "VatCreditPage",
    "VatLiabilityPage",
    "VatRegisterPage",
    "figure",
    "month_of",
]
