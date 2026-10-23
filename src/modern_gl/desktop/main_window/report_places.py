"""How the reports open: the places that are reports (ОСВ, the statements, the chart of
accounts) and the reports opened as pages of their own (a card, «Сравнение книг»…)."""

from __future__ import annotations

from PySide6.QtWidgets import QWidget

from modern_gl.desktop.landed_cost_report_page import LandedCostReportPage
from modern_gl.desktop.main_window.open_pages import OpenPages
from modern_gl.desktop.reports_page import (
    REPORTS,
    BooksPage,
    ChartPage,
    OsvPage,
    ReportParams,
    StatementsPage,
)


class ReportPlaces(OpenPages):
    def _report_place(self, key) -> QWidget:
        """ОСВ, the statements or the chart of accounts: places that open reports."""
        s = self.open_session
        if key == ("osv",):
            osv = OsvPage(s)
            osv.compare_books.connect(self.open_books)
            self._wire_report(osv)
            return osv
        other = StatementsPage(s) if key == ("statements",) else ChartPage(s)
        self._wire_report(other)
        return other

    def open_books(self) -> None:
        """«Сравнение книг» (D98): an open page of its own, like an account's card."""
        key = BooksPage.key
        if key not in self.pages:
            page = BooksPage(self.open_session)
            self._wire_report(page)
            self._add_page(key, page, open_item=True)
        self._activate(key)

    def _wire_report(self, page) -> None:
        page.open_document.connect(self.open_document)
        page.open_report.connect(self.open_report)

    def open_landed_report(self) -> None:
        """«Əlavə xərclər» by declaration, from the warehouse."""
        key = LandedCostReportPage.key
        if key not in self.pages:
            page = LandedCostReportPage(self.open_session)
            page.open_inventory_document.connect(self.open_inventory_document)
            self._add_page(key, page, open_item=True)
        self._activate(key)

    def open_report(self, kind: str, account_id: int, params: ReportParams) -> None:
        page = REPORTS[kind](self.open_session, account_id, params)
        key = page.key  # a card of one counterparty is a page of its own
        if key in self.pages:
            self.close_page(key, ask=False)
        self._wire_report(page)
        self._add_page(key, page, open_item=True)
        self._activate(key)

    # ---- made by the window ----------------------------------------------------------

    def open_document(self, doc_id: int) -> None:
        raise NotImplementedError

    def open_inventory_document(self, document_id: int) -> None:
        raise NotImplementedError
