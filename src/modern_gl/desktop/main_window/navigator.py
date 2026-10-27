"""What opens where: the places of the sidebar (a key → its page), the documents of the
journal and of the modules (bank, conversion, warehouse), templates — each page made,
wired to what it asks for and put on the `PageStack`. The reports — `ReportPlaces`."""

from __future__ import annotations

from PySide6.QtCore import QObject
from PySide6.QtWidgets import QWidget

from modern_gl.application.bank import load_bank_operation
from modern_gl.application.conversion import load_conversion
from modern_gl.application.inventory import Inventory
from modern_gl.application.queries import (
    document_owner,
    is_opening_document,
    load_document,
    load_template,
)
from modern_gl.desktop.backups_dialog import BackupsDialog
from modern_gl.desktop.bank_operation_page import BankOperationPage
from modern_gl.desktop.bank_page import BankPage
from modern_gl.desktop.conversion_page import ConversionPage
from modern_gl.desktop.currencies_page import CurrenciesPage
from modern_gl.desktop.directories_page import DirectoriesPage
from modern_gl.desktop.document_page import DocumentPage
from modern_gl.desktop.home_page import HomePage
from modern_gl.desktop.import_page import ImportPage
from modern_gl.desktop.inventory_document_page import InventoryDocumentPage
from modern_gl.desktop.inventory_page import InventoryPage
from modern_gl.desktop.invoices_page import InvoicesPage
from modern_gl.desktop.journal_page import JournalPage
from modern_gl.desktop.landed_cost_page import LandedCostPage
from modern_gl.desktop.landed_cost_report_page import LandedCostReportPage
from modern_gl.desktop.main_window.company_files import CompanySession
from modern_gl.desktop.main_window.page_stack import PageStack
from modern_gl.desktop.main_window.report_places import ReportPlaces
from modern_gl.desktop.main_window.sidebar import shown_places
from modern_gl.desktop.opening_balances_page import OpeningBalancesPage
from modern_gl.desktop.page import EmptyPage, PageWidget
from modern_gl.desktop.reports_hub import PIN_KEYS
from modern_gl.desktop.reports_page import ReportPage
from modern_gl.desktop.stock_count_page import StockCountPage
from modern_gl.desktop.templates_page import TemplatePage, TemplatesPage
from modern_gl.desktop.trade_page import TradePage
from modern_gl.desktop.vat_payer import VAT_REPORTS, edit_vat_payer
from modern_gl.domain.errors import NotFoundError
from modern_gl.i18n import tr
from modern_gl.reporting.trade import PURCHASE, SALE


class Navigator(QObject):
    """Opens the pages of the open company (`CompanySession`) on the `PageStack`."""

    def __init__(self, company: CompanySession, page_stack: PageStack, owner: QWidget) -> None:
        super().__init__(owner)
        self.owner = owner  # the window: dialogs are shown over it
        self.company = company
        self.page_stack = page_stack
        self.reports = ReportPlaces(self)

    def show_place(self, key) -> None:
        session = self.company.session
        if session is not None and key not in shown_places(session.stock_only):
            return  # a page of the books, in a company kept as a warehouse only (D90)
        if key not in self.page_stack.pages:
            self.page_stack.add(key, self._make_place(key))
        self.page_stack.activate(key)

    def go(self, key) -> None:
        """A key of the sidebar with no page open (or the page to return to). A pinned
        report opens as from «Все отчёты» (a card asks the account first), and the
        sidebar keeps the item of the page shown."""
        if key not in PIN_KEYS:
            self.show_place(key)
            return
        self.reports.open_catalog_report(PIN_KEYS[key])
        self.page_stack.select_current()

    def _make_place(self, key) -> PageWidget:
        s = self.company.open_session
        if key == ("home",):
            page = HomePage(s, shown_places(s.stock_only))
            page.open_place.connect(self.show_place)
            page.open_backups.connect(self.show_backups)
            return page
        if key == ("journal",):
            page = JournalPage(s)
            page.open_document.connect(self.open_document)
            page.new_document.connect(self.new_document)
            page.deleted.connect(
                lambda doc_id: self.page_stack.close_page(("doc", doc_id), ask=False)
            )
            page.copy_document.connect(self.copy_document)
            page.prefill_document.connect(self.new_document)
            page.import_requested.connect(self.show_import)
            return page
        if key == ("bank",):
            page = BankPage(s)
            page.open_document.connect(self.open_document)
            page.new_bank_operation.connect(self.new_bank_operation)
            page.new_conversion.connect(self.new_conversion)
            return page
        if key == ("directories",):
            return DirectoriesPage(s)
        if key == ("opening",):
            try:
                page = OpeningBalancesPage(s)
            except NotFoundError as e:  # viewing a company that has none (D80)
                return EmptyPage(key, tr("Начальные остатки"), str(e))
            page.saved.connect(self.page_stack.postings_changed)
            return page
        if key == ("currencies",):
            page = CurrenciesPage(s)
            page.open_document.connect(self.open_document)
            return page
        if key == ("inventory",):
            page = InventoryPage(s)
            page.open_inventory_document.connect(self.open_inventory_document)
            page.new_inventory_document.connect(self.new_inventory_document)
            page.open_landed_report.connect(self.reports.open_landed_report)
            page.open_report.connect(self.reports.open_catalog_report)
            return page
        if key in (("purchases",), ("sales",)):
            page = TradePage(s, PURCHASE if key == ("purchases",) else SALE)
            page.open_inventory_document.connect(self.open_inventory_document)
            page.new_inventory_document.connect(self.new_inventory_document)
            page.imported.connect(self.refresh_trade)
            return page
        if key == ("templates",):
            page = TemplatesPage(s)
            page.use_template.connect(
                lambda tid: self.new_document(entry=load_template(s.conn, s.company_id, tid))
            )
            page.edit_template.connect(self.open_template)
            return page
        if key == ("invoices",):
            page = InvoicesPage(s)
            page.open_document.connect(self.open_document)
            return page
        return self.reports.place(key)

    def show_import(self) -> None:
        if self.company.viewing():
            return
        key = ImportPage.key
        if key not in self.page_stack.pages:
            page = ImportPage(self.company.open_session)
            page.imported.connect(self._imported)
            self.page_stack.add(key, page, open_item=True)
        self.page_stack.activate(key)

    def _imported(self, ids: list) -> None:
        self.show_place(("journal",))
        journal = self.page_stack.page(("journal",), JournalPage)
        if journal is not None:
            journal.refresh(select_id=ids[-1])

    def quick_entry(self) -> None:
        """Ctrl+L anywhere: the journal with the cursor in the quick entry line."""
        if (
            self.company.session is None
            or self.company.viewing()
            or self.company.session.stock_only
        ):
            return
        self.show_place(("journal",))
        journal = self.page_stack.page(("journal",), JournalPage)
        if journal is not None:
            journal.focus_quick_entry()

    def open_document(self, doc_id: int) -> None:
        """From the journal or a report: the primary document, as in 1C. Postings a module
        made (document_owners) open its document, where they are corrected."""
        s = self.company.open_session
        owner = document_owner(s.conn, s.company_id, doc_id)
        opens = {
            "inventory": self.open_inventory_document,
            "conversion": self.open_conversion,
            "bank": self.open_bank_operation,
        }
        if owner is not None and owner.module in opens:
            opens[owner.module](owner.id)
            return
        if is_opening_document(s.conn, s.company_id, doc_id):
            self.show_place(("opening",))
            return
        self.show_document(doc_id)

    def copy_document(self, doc_id: int) -> None:
        """Opening balances are a singleton, so F9 opens them instead of cloning them."""
        s = self.company.open_session
        if is_opening_document(s.conn, s.company_id, doc_id):
            self.show_place(("opening",))
            self.company.notify(tr("Начальные остатки вводятся один раз"))
            return
        owner = document_owner(s.conn, s.company_id, doc_id)
        if owner is not None and owner.module == "conversion":
            data = load_conversion(s.conn, s.company_id, owner.id)
            self.new_conversion(ConversionPage.copy_of(data))
            return
        if owner is not None and owner.module == "bank":
            operation = load_bank_operation(s.conn, s.company_id, owner.id)
            self.new_bank_operation(BankOperationPage.copy_of(operation))
            return
        self.new_document(load_document(s.conn, s.company_id, doc_id))

    def show_document(self, doc_id: int) -> None:
        """The GL document itself, even when a warehouse document made it."""
        key = ("doc", doc_id)
        if key not in self.page_stack.pages:
            page = DocumentPage(self.company.open_session, doc_id=doc_id)
            self._wire_document(page)
            self.page_stack.add(key, page, open_item=True)
        self.page_stack.activate(key)

    def new_document(self, template=None, entry=None) -> None:
        if self.company.viewing() or (
            self.company.session is not None and self.company.session.stock_only
        ):
            return  # a journal document: not in a company kept as a warehouse only (D90)
        page = DocumentPage(self.company.open_session, template=template, entry=entry)
        self._wire_document(page)
        self.page_stack.add(page.key, page, open_item=True)
        self.page_stack.activate(page.key)

    def _wire_document(self, page: DocumentPage) -> None:
        page.saved.connect(lambda _id, p=page: self._document_saved(p))
        page.open_document.connect(self.open_document)
        page.copy_requested.connect(self.new_document)
        page.open_inventory_document.connect(self.open_inventory_document)
        page.new_requested.connect(self.new_document)
        page.template_saved.connect(self.open_template)
        page.close_requested.connect(
            lambda p=page: self.page_stack.close_page(self.page_stack.key_of(p))
        )
        page.title_changed.connect(lambda p=page: self.page_stack.retitle(p))

    def open_conversion(self, conversion_id: int) -> None:
        key = ("conversion", conversion_id)
        if key not in self.page_stack.pages:
            page = ConversionPage(self.company.open_session, conversion_id)
            self._wire_conversion(page)
            self.page_stack.add(key, page, open_item=True)
        self.page_stack.activate(key)

    def new_conversion(self, prefill=None) -> None:
        if self.company.viewing():
            return
        page = ConversionPage(self.company.open_session, prefill=prefill)
        self._wire_conversion(page)
        self.page_stack.add(page.key, page, open_item=True)
        self.page_stack.activate(page.key)

    def _wire_conversion(self, page: ConversionPage) -> None:
        page.saved.connect(lambda doc_id, p=page: self._conversion_saved(p, doc_id))
        page.open_gl_document.connect(self.show_document)
        page.copy_requested.connect(self.new_conversion)
        page.close_requested.connect(
            lambda p=page: self.page_stack.close_page(self.page_stack.key_of(p), ask=False)
        )
        page.title_changed.connect(lambda p=page: self.page_stack.retitle(p))

    def _conversion_saved(self, page: ConversionPage | BankOperationPage, doc_id: int) -> None:
        self.page_stack.rekey(page)
        self.page_stack.retitle(page)
        self.page_stack.postings_changed(doc_id)

    def open_bank_operation(self, operation_id: int) -> None:
        key = ("bank_op", operation_id)
        if key not in self.page_stack.pages:
            page = BankOperationPage(self.company.open_session, operation_id)
            self._wire_bank_operation(page)
            self.page_stack.add(key, page, open_item=True)
        self.page_stack.activate(key)

    def new_bank_operation(self, prefill=None) -> None:
        if self.company.viewing():
            return
        page = BankOperationPage(self.company.open_session, prefill=prefill)
        self._wire_bank_operation(page)
        self.page_stack.add(page.key, page, open_item=True)
        self.page_stack.activate(page.key)

    def _wire_bank_operation(self, page: BankOperationPage) -> None:
        page.saved.connect(lambda doc_id, p=page: self._conversion_saved(p, doc_id))
        page.open_gl_document.connect(self.show_document)
        page.copy_requested.connect(self.new_bank_operation)
        page.next_requested.connect(lambda data, p=page: self._next_bank_operation(p, data))
        page.close_requested.connect(
            lambda p=page: self.page_stack.close_page(self.page_stack.key_of(p), ask=False)
        )
        page.title_changed.connect(lambda p=page: self.page_stack.retitle(p))

    def _next_bank_operation(self, page: BankOperationPage, data) -> None:
        """A new operation posted: it is in the statement; the next one opens in its place."""
        self.page_stack.close_page(self.page_stack.key_of(page), ask=False)
        self.new_bank_operation(data)

    def open_inventory_document(self, document_id: int) -> None:
        key = ("inventory_doc", document_id)
        if key not in self.page_stack.pages:
            session = self.company.open_session
            doc = Inventory(session.conn).load_document(session.company_id, document_id)
            page: InventoryDocumentPage | LandedCostPage = (
                LandedCostPage(session, document_id)
                if doc.doc_type == "landed_cost"
                else InventoryDocumentPage(session, document_id=document_id)
            )
            self._wire_inventory_document(page)
            self.page_stack.add(key, page, open_item=True)
        self.page_stack.activate(key)

    def new_inventory_document(self, doc_type: str) -> None:
        if self.company.viewing():
            return
        if doc_type == "count":  # a count makes its documents itself
            self.open_stock_count()
            return
        page: InventoryDocumentPage | LandedCostPage = (
            LandedCostPage(self.company.open_session)
            if doc_type == "landed_cost"
            else InventoryDocumentPage(self.company.open_session, doc_type=doc_type)
        )
        self._wire_inventory_document(page)
        self.page_stack.add(page.key, page, open_item=True)
        self.page_stack.activate(page.key)

    def open_stock_count(self) -> None:
        """«Инвентаризация»: one page; what it posts refreshes «Склад»."""
        if StockCountPage.key not in self.page_stack.pages:
            page = StockCountPage(self.company.open_session)
            page.posted.connect(self._stock_counted)
            page.open_inventory_document.connect(self.open_inventory_document)
            self.page_stack.add(StockCountPage.key, page, open_item=True)
        self.page_stack.activate(StockCountPage.key)

    def _stock_counted(self) -> None:
        inventory = self.page_stack.page(("inventory",), InventoryPage)
        if inventory is not None:
            inventory.refresh()

    def _wire_inventory_document(self, page: InventoryDocumentPage | LandedCostPage) -> None:
        page.saved.connect(lambda _id, p=page: self._inventory_document_saved(p))
        page.open_gl_document.connect(self.show_document)
        page.close_requested.connect(
            lambda p=page: self.page_stack.close_page(self.page_stack.key_of(p), ask=False)
        )
        page.title_changed.connect(lambda p=page: self.page_stack.retitle(p))

    def _inventory_document_saved(self, page: InventoryDocumentPage | LandedCostPage) -> None:
        self.page_stack.rekey(page)
        self.page_stack.retitle(page)
        inventory = self.page_stack.page(("inventory",), InventoryPage)
        if inventory is not None:
            inventory.refresh()
        report = self.page_stack.page(LandedCostReportPage.key, LandedCostReportPage)
        if report is not None:
            report.refresh()
        self.refresh_trade()

    def refresh_trade(self) -> None:
        for key in (("purchases",), ("sales",)):
            trade = self.page_stack.page(key, TradePage)
            if trade is not None:
                trade.refresh()

    def open_template(self, template_id: int | None) -> None:
        """The template editor; a saved (or deleted) template returns to the list."""
        key = ("template", template_id)
        if template_id is not None and key in self.page_stack.pages:
            self.page_stack.activate(key)
            return
        if template_id is None and self.company.viewing():
            return
        page = TemplatePage(self.company.open_session, template_id)
        key = page.key
        page.saved.connect(lambda tid, p=page: self._template_saved(p, tid))
        page.close_requested.connect(
            lambda p=page: self.page_stack.close_page(self.page_stack.key_of(p), ask=False)
        )
        page.title_changed.connect(lambda p=page: self.page_stack.retitle(p))
        self.page_stack.add(key, page, open_item=True)
        self.page_stack.activate(key)

    def _template_saved(self, page: TemplatePage, template_id: int) -> None:
        templates = self.page_stack.page(("templates",), TemplatesPage)
        if templates is not None:
            templates.refresh(select_id=template_id)
        self.page_stack.close_page(self.page_stack.key_of(page), ask=False)
        self.show_place(("templates",))

    def _document_saved(self, page: DocumentPage) -> None:
        self.page_stack.rekey(page)
        self.page_stack.retitle(page)
        journal = self.page_stack.page(("journal",), JournalPage)
        if journal is not None:
            journal.refresh(select_id=page.doc_id)

    def show_backups(self) -> None:
        """«Резервные копии» (D97): when and where, a copy now, the second folder."""
        if self.company.viewing() or self.company.conn is None or self.company.company_path is None:
            return
        BackupsDialog(
            self.company.workspace,
            self.company.conn,
            self.company.company_path,
            self.company.settings,
            self.owner,
        ).exec()
        home = self.page_stack.pages.get(("home",))
        if isinstance(home, HomePage):
            home.refresh()

    def edit_vat_payer(self) -> None:
        """«Плательщик ƏDV с…» (D145): the ƏDV reports open are counted again."""
        if self.company.session is None or not edit_vat_payer(self.owner, self.company.session):
            return
        for key in VAT_REPORTS:
            page = self.page_stack.pages.get((key,))
            if isinstance(page, ReportPage):
                page.refresh()
