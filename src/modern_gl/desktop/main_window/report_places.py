"""How the reports open: the places that are reports (ОСВ, the statements, the chart of
accounts), the reports opened as pages of their own (a card, «Сравнение книг»…) and
«Все отчёты» (D114) — the catalog of all of them, with the pinned ones in the sidebar."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject

from modern_gl.desktop import icons
from modern_gl.desktop.eqaime_reconciliation_page import EqaimeReconciliationDialog
from modern_gl.desktop.landed_cost_report_page import LandedCostReportPage
from modern_gl.desktop.page import PageWidget
from modern_gl.desktop.preferences import STATEMENTS_VIEW, prefs
from modern_gl.desktop.reports_hub import (
    BY_ID,
    HUB,
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
    ActionLogPage,
    BooksPage,
    ChartPage,
    OsvPage,
    ReconciliationActPage,
    ReportParams,
    StatementsPage,
    SubcontoAnalysisPage,
    VatCreditPage,
    VatLiabilityPage,
    VatPaymentsPage,
    VatReceiptsPage,
    VatRegisterPage,
    month_of,
)
from modern_gl.desktop.stock_reports import GrossProfitPage, ItemCardPage, StockStatementPage
from modern_gl.desktop.theme import P
from modern_gl.i18n import tr
from modern_gl.reporting.trade import PURCHASE, SALE

if TYPE_CHECKING:
    from modern_gl.desktop.main_window.navigator import Navigator

ACCOUNT_REPORTS = ("subconto", "card", "analysis")  # they ask the account first


class ReportPlaces(QObject):
    """The reports of the `Navigator`: it opens the places that are reports through
    `place`, the rest — the catalog's reports and the pinned ones — open here."""

    def __init__(self, nav: Navigator) -> None:
        super().__init__(nav)
        self.nav = nav  # documents, places and the warehouse the reports lead to
        self.company = nav.company
        self.page_stack = nav.page_stack

    def place(self, key) -> PageWidget:
        """ОСВ, the statements, the chart of accounts or «Все отчёты»."""
        s = self.company.open_session
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
            statements.view_changed.connect(lambda p=statements: self.page_stack.select_nav(key, p))
            self._wire_report(statements)
            return statements
        chart = ChartPage(s)
        self._wire_report(chart)
        return chart

    # ---- «Все отчёты» and the pinned reports (D114) ------------------------------------

    def shown_reports(self) -> list[Report]:
        s = self.company.open_session
        return shown(s.stock_only, s.read_only, s.parallel_books)

    def show_pins(self) -> None:
        """The sidebar's pinned reports as they are chosen now; the page shown keeps its
        item chosen."""
        offered = {r.id: r for r in self.shown_reports()}
        self.page_stack.sidebar.set_pins(
            [
                (pin_key(i), tr(offered[i].title), self._pin_icon(offered[i]))
                for i in pinned()
                if i in offered
            ]
        )
        self.page_stack.select_current()
        hub = self.page_stack.pages.get(HUB)
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
            "osv": lambda: self.nav.show_place(("osv",)),
            "balance": lambda: self.open_statements("balance"),
            "profit": lambda: self.open_statements("profit"),
            "cash": lambda: self.open_statements("cash"),
            "books": self.open_books,
            "subconto_analysis": self.open_subconto_analysis,
            "reconciliation_act": lambda: self.open_single(ReconciliationActPage),
            "handover": self.company.hand_over,
            "action_log": lambda: self.open_single(ActionLogPage),
            "invoices": lambda: self.nav.show_place(("invoices",)),
            "vat_credit": self.open_vat_credit,
            "vat_liability": lambda: self.open_single(VatLiabilityPage),
            "vat_receipts": lambda: self.open_single(VatReceiptsPage),
            "vat_payments": lambda: self.open_single(VatPaymentsPage),
            "vat_register": self.open_vat_register,
            "reconcile_purchases": lambda: self.open_reconciliation(PURCHASE),
            "reconcile_sales": lambda: self.open_reconciliation(SALE),
            "landed": self.open_landed_report,
            "stock_statement": lambda: self.open_stock_report(StockStatementPage),
            "gross_profit": lambda: self.open_stock_report(GrossProfitPage),
            "stock": lambda: self.nav.show_place(("inventory",)),
            "bank": lambda: self.nav.show_place(("bank",)),
        }

    def _remember(self, report_id: str) -> None:
        remember(report_id)
        hub = self.page_stack.pages.get(HUB)
        if isinstance(hub, ReportsPage):
            hub.refresh()

    def _ask_account_report(self, report: Report) -> None:
        s = self.company.open_session
        account_id = ask_account(s.catalog, report.id, tr(report.title), self.nav.owner)
        if account_id is not None:
            self._remember(report.id)
            self.open_report(report.id, account_id, month_of(s.working_date))

    def open_statements(self, view: str) -> None:
        """«Финансовая отчётность» on the view asked: one page for the three (D99)."""
        page = self.page_stack.pages.get(("statements",))
        if isinstance(page, StatementsPage):
            page.show_view(view)
        else:  # the page opens on it at once, without reading another view first
            prefs().set_view(STATEMENTS_VIEW, view)
        self.nav.show_place(("statements",))

    def open_reconciliation(self, direction: str) -> None:
        """«Сверка с порталом» of purchases or sales, as from their pages."""
        dialog = EqaimeReconciliationDialog(
            self.company.open_session, self.nav.owner, direction=direction
        )
        dialog.exec()
        self.nav.refresh_trade()  # drafts may have been made from it
        if dialog.chosen_document is not None:
            self.nav.open_document(dialog.chosen_document)

    def unpin(self, report_id: str) -> None:
        set_pinned(report_id, False)
        self.show_pins()

    # ---- reports as pages of their own -------------------------------------------------

    def open_books(self) -> None:
        """«Сравнение книг» (D98): an open page of its own, like an account's card."""
        key = BooksPage.key
        if key not in self.page_stack.pages:
            page = BooksPage(self.company.open_session)
            self._wire_report(page)
            self.page_stack.add(key, page, open_item=True)
        self.page_stack.activate(key)

    def open_vat_credit(self) -> None:
        """«ƏDV к зачёту»: one page, the period on it."""
        key = VatCreditPage.key
        if key not in self.page_stack.pages:
            page = VatCreditPage(self.company.open_session)
            self._wire_report(page)
            self.page_stack.add(key, page, open_item=True)
        self.page_stack.activate(key)

    def open_vat_register(self) -> None:
        """«Реестр e-qaimə»: one page, the period on it."""
        key = VatRegisterPage.key
        if key not in self.page_stack.pages:
            page = VatRegisterPage(self.company.open_session)
            self._wire_report(page)
            self.page_stack.add(key, page, open_item=True)
        self.page_stack.activate(key)

    def open_single(self, page_class) -> None:
        """A report of one page, the period on it («ƏDV продаж к уплате»)."""
        key = page_class.key
        if key not in self.page_stack.pages:
            page = page_class(self.company.open_session)
            self._wire_report(page)
            self.page_stack.add(key, page, open_item=True)
        self.page_stack.activate(key)

    def open_subconto_analysis(self) -> None:
        """«Анализ субконто» (D125): one page, the directory is chosen on it."""
        key = SubcontoAnalysisPage.key
        if key not in self.page_stack.pages:
            page = SubcontoAnalysisPage(self.company.open_session)
            self._wire_report(page)
            self.page_stack.add(key, page, open_item=True)
        self.page_stack.activate(key)

    def _wire_report(self, page) -> None:
        page.open_document.connect(self.nav.open_document)
        page.open_report.connect(self.open_report)
        page.title_changed.connect(lambda p=page: self.page_stack.retitle(p))

    def open_landed_report(self) -> None:
        """«Əlavə xərclər» by declaration, from the warehouse."""
        key = LandedCostReportPage.key
        if key not in self.page_stack.pages:
            page = LandedCostReportPage(self.company.open_session)
            page.open_inventory_document.connect(self.nav.open_inventory_document)
            self.page_stack.add(key, page, open_item=True)
        self.page_stack.activate(key)

    def open_stock_report(self, page_class) -> None:
        """«Ведомость по складу», «Валовая прибыль»: one page, the period on it."""
        key = page_class.key
        if key not in self.page_stack.pages:
            page = page_class(self.company.open_session)
            page.open_stock_card.connect(self.open_stock_card)
            self.page_stack.add(key, page, open_item=True)
        self.page_stack.activate(key)

    def open_stock_card(self, item_id: int, warehouse_id: int, params: ReportParams) -> None:
        """An item's card on a warehouse (0 — on all) for the period it was asked from."""
        page = ItemCardPage(self.company.open_session, item_id, warehouse_id or None, params)
        if page.key in self.page_stack.pages:
            self.page_stack.close_page(page.key, ask=False)
        page.open_inventory_document.connect(self.nav.open_inventory_document)
        self.page_stack.add(page.key, page, open_item=True)
        self.page_stack.activate(page.key)

    def open_report(self, kind: str, account_id: int, params: ReportParams) -> None:
        page = REPORTS[kind](self.company.open_session, account_id, params)
        key = page.key  # a card of one counterparty is a page of its own
        if key in self.page_stack.pages:
            self.page_stack.close_page(key, ask=False)
        self._wire_report(page)
        self.page_stack.add(key, page, open_item=True)
        self.page_stack.activate(key)
