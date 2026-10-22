"""Report pages: ОСВ, карточка счёта, ОСВ по субконто, анализ счёта, план счетов.

Every report = parameters bar + one calm table + footer. Drill-down by double click.
"""

from __future__ import annotations

from modern_gl.desktop.reports_page.account import REPORTS, CardPage, SubcontoPage
from modern_gl.desktop.reports_page.chart import ChartPage
from modern_gl.desktop.reports_page.osv import OsvPage
from modern_gl.desktop.reports_page.table import (
    SectionRow,
    figure,
)
from modern_gl.desktop.reports_page.view import (
    NAME_MAX,
    NAME_MIN,
    Column,
    MenuAction,
    ReportModel,
    ReportPage,
    ReportParams,
    month_of,
)

__all__ = [
    "NAME_MAX",
    "NAME_MIN",
    "REPORTS",
    "CardPage",
    "ChartPage",
    "Column",
    "MenuAction",
    "OsvPage",
    "ReportModel",
    "ReportPage",
    "ReportParams",
    "SectionRow",
    "SubcontoPage",
    "figure",
    "month_of",
]
