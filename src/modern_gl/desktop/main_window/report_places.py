"""How the reports open: the places that are reports (ОСВ, the statements, the chart of
accounts), the reports opened as pages of their own (a card, «Сравнение книг»…) and
«Все отчёты» (D114) — the catalog of all of them, with the pinned ones in the sidebar."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QListWidgetItem, QMenu, QWidget

from modern_gl.desktop import icons
from modern_gl.desktop.eqaime_reconciliation_page import EqaimeReconciliationDialog
from modern_gl.desktop.landed_cost_report_page import LandedCostReportPage
from modern_gl.desktop.main_window.open_pages import OpenPages
from modern_gl.desktop.main_window.sidebar import KEY_ROLE
from modern_gl.desktop.reports_hub import (
    BY_ID,
    HUB,
    PIN_KEYS,
    Report,
    ReportsPage,
    ask_account,
    pin_key,
    pinned,
    remember,
    set_pinned,
    shown,
)
from modern_gl.desktop.reports_page import (
    REPORTS,
    BooksPage,
    ChartPage,
    OsvPage,
    ReportParams,
    StatementsPage,
    SubcontoAnalysisPage,
    VatCreditPage,
    VatRegisterPage,
    month_of,
)
from modern_gl.desktop.reports_page.statements import VIEW_SETTING
from modern_gl.desktop.theme import P
from modern_gl.i18n import tr
from modern_gl.reporting.trade import PURCHASE, SALE

ACCOUNT_REPORTS = ("subconto", "card", "analysis")  # they ask the account first


class ReportPlaces(OpenPages):
    def _report_place(self, key) -> QWidget:
        """ОСВ, the statements, the chart of accounts or «Все отчёты»."""
        s = self.open_session
        if key == HUB:
            hub = ReportsPage(s)
            hub.open_report.connect(self.open_catalog_report)
            hub.pins_changed.connect(self.show_pins)
            return hub
        if key == ("osv",):
            osv = OsvPage(s)
            osv.compare_books.connect(self.open_books)
            self._wire_report(osv)
            return osv
        if key == ("statements",):
            statements = StatementsPage(s)
            statements.view_changed.connect(lambda p=statements: self._select_nav(key, p))
            self._wire_report(statements)
            return statements
        chart = ChartPage(s)
        self._wire_report(chart)
        return chart

    # ---- «Все отчёты» and the pinned reports (D114) ------------------------------------

    def shown_reports(self) -> list[Report]:
        s = self.open_session
        return shown(s.stock_only, s.read_only, s.parallel_books)

    def _show_company(self, name: str) -> None:
        super()._show_company(name)
        self.show_pins()

    def show_pins(self) -> None:
        """The sidebar's pinned reports as they are chosen now; the page shown keeps its
        item chosen."""
        offered = {r.id: r for r in self.shown_reports()}
        self.sidebar.set_pins(
            [
                (pin_key(i), tr(offered[i].title), self._pin_icon(offered[i]))
                for i in pinned()
                if i in offered
            ]
        )
        current = self.stack.currentWidget()
        if current is not None:
            self._select_nav(self._key_of(current), current)
        hub = self.pages.get(HUB)
        if isinstance(hub, ReportsPage):
            hub.show_pins()

    @staticmethod
    def _pin_icon(report: Report):
        return icons.icon(report.icon, P.secondary, selected=P.accent)

    def open_catalog_report(self, report_id: str) -> None:
        """A report of the catalog, from «Все отчёты», the sidebar or Ctrl+K."""
        report = BY_ID.get(report_id)
        if report is None or report not in self.shown_reports():
            return
        if report_id in ACCOUNT_REPORTS:
            self._ask_account_report(report)
            return
        self._remember(report_id)
        self._openers()[report_id]()

    def _openers(self) -> dict[str, Callable[[], object]]:
        return {
            "osv": lambda: self.show_place(("osv",)),
            "balance": lambda: self.open_statements("balance"),
            "profit": lambda: self.open_statements("profit"),
            "cash": lambda: self.open_statements("cash"),
            "books": self.open_books,
            "subconto_analysis": self.open_subconto_analysis,
            "handover": self.hand_over,
            "invoices": lambda: self.show_place(("invoices",)),
            "vat_credit": self.open_vat_credit,
            "vat_register": self.open_vat_register,
            "reconcile_purchases": lambda: self.open_reconciliation(PURCHASE),
            "reconcile_sales": lambda: self.open_reconciliation(SALE),
            "landed": self.open_landed_report,
            "stock": lambda: self.show_place(("inventory",)),
            "bank": lambda: self.show_place(("bank",)),
        }

    def _remember(self, report_id: str) -> None:
        remember(report_id)
        hub = self.pages.get(HUB)
        if isinstance(hub, ReportsPage):
            hub.refresh()

    def _ask_account_report(self, report: Report) -> None:
        s = self.open_session
        account_id = ask_account(s.catalog, report.id, tr(report.title), self)
        if account_id is not None:
            self._remember(report.id)
            self.open_report(report.id, account_id, month_of(s.working_date))

    def open_statements(self, view: str) -> None:
        """«Финансовая отчётность» on the view asked: one page for the three (D99)."""
        page = self.pages.get(("statements",))
        if isinstance(page, StatementsPage):
            page.show_view(view)
        else:  # the page opens on it at once, without reading another view first
            QSettings().setValue(VIEW_SETTING, view)
        self.show_place(("statements",))

    def open_reconciliation(self, direction: str) -> None:
        """«Сверка с порталом» of purchases or sales, as from their pages."""
        dialog = EqaimeReconciliationDialog(self.open_session, self, direction=direction)
        dialog.exec()
        self._refresh_trade()  # drafts may have been made from it
        if dialog.chosen_document is not None:
            self.open_document(dialog.chosen_document)

    def _on_nav(self, current: QListWidgetItem | None, previous) -> None:
        """A pinned report opens as from «Все отчёты» (a card asks the account first), and
        the sidebar keeps the item of the page shown."""
        key = current.data(KEY_ROLE) if current is not None else None
        if key not in PIN_KEYS:
            super()._on_nav(current, previous)
            return
        self.open_catalog_report(PIN_KEYS[key])
        page = self.stack.currentWidget()
        if page is not None:
            self._select_nav(self._key_of(page), page)

    def _nav_menu(self, pos) -> None:
        item = self.sidebar.nav.itemAt(pos)
        key = item.data(KEY_ROLE) if item else None
        if key not in PIN_KEYS:
            super()._nav_menu(pos)
            return
        menu = QMenu(self)
        menu.addAction(tr("Убрать из боковой панели")).triggered.connect(
            lambda: self.unpin(PIN_KEYS[key])
        )
        menu.exec(self.sidebar.nav.viewport().mapToGlobal(pos))

    def unpin(self, report_id: str) -> None:
        set_pinned(report_id, False)
        self.show_pins()

    # ---- reports as pages of their own -------------------------------------------------

    def open_books(self) -> None:
        """«Сравнение книг» (D98): an open page of its own, like an account's card."""
        key = BooksPage.key
        if key not in self.pages:
            page = BooksPage(self.open_session)
            self._wire_report(page)
            self._add_page(key, page, open_item=True)
        self._activate(key)

    def open_vat_credit(self) -> None:
        """«ƏDV к зачёту»: one page, the period on it."""
        key = VatCreditPage.key
        if key not in self.pages:
            page = VatCreditPage(self.open_session)
            self._wire_report(page)
            self._add_page(key, page, open_item=True)
        self._activate(key)

    def open_vat_register(self) -> None:
        """«Реестр e-qaimə»: one page, the period on it."""
        key = VatRegisterPage.key
        if key not in self.pages:
            page = VatRegisterPage(self.open_session)
            self._wire_report(page)
            self._add_page(key, page, open_item=True)
        self._activate(key)

    def open_subconto_analysis(self) -> None:
        """«Анализ субконто» (D125): one page, the directory is chosen on it."""
        key = SubcontoAnalysisPage.key
        if key not in self.pages:
            page = SubcontoAnalysisPage(self.open_session)
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

    def _refresh_trade(self) -> None:
        raise NotImplementedError
