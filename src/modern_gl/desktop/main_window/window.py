"""The main window: what the places are and how documents, reports and modules open."""

from __future__ import annotations

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import (
    QGuiApplication,
    QKeySequence,
    QShortcut,
)
from PySide6.QtWidgets import QMenu

from modern_gl.application.bank import load_bank_operation
from modern_gl.application.conversion import load_conversion
from modern_gl.application.inventory import Inventory
from modern_gl.application.queries import (
    document_owner,
    is_opening_document,
    load_document,
    load_template,
)
from modern_gl.application.workspace import Workspace
from modern_gl.desktop import theme
from modern_gl.desktop.backups_dialog import BackupsDialog
from modern_gl.desktop.bank_operation_page import BankOperationPage
from modern_gl.desktop.bank_page import BankPage
from modern_gl.desktop.command_palette import CommandPalette
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
from modern_gl.desktop.main_window.commands import palette_entries
from modern_gl.desktop.main_window.report_places import ReportPlaces
from modern_gl.desktop.main_window.sidebar import shown_places
from modern_gl.desktop.opening_balances_page import OpeningBalancesPage
from modern_gl.desktop.page import EmptyPage, PageWidget
from modern_gl.desktop.period_dialog import PeriodDialog
from modern_gl.desktop.reports_page import ReportPage
from modern_gl.desktop.reports_page.table import grid, set_grid, set_zebra, zebra
from modern_gl.desktop.stock_count_page import StockCountPage
from modern_gl.desktop.templates_page import TemplatePage, TemplatesPage
from modern_gl.desktop.trade_page import TradePage
from modern_gl.desktop.vat_payer import VAT_REPORTS, edit_vat_payer
from modern_gl.domain.errors import NotFoundError
from modern_gl.i18n import LANGUAGES, document_language, language, tr
from modern_gl.reporting.trade import PURCHASE, SALE


class MainWindow(ReportPlaces):
    def __init__(self, workspace: Workspace, settings: QSettings | None = None) -> None:
        super().__init__(workspace, settings)
        self.sidebar.company.clicked.connect(self._company_menu)
        for keys, fn in (
            ("Ctrl+N", self.new_document),
            ("Ctrl+W", self.close_current),
            ("Ctrl+F4", self.close_current),
            ("Ctrl+1", lambda: self.show_place(("journal",))),
            ("Ctrl+2", lambda: self.show_place(("osv",))),
            ("Ctrl+3", lambda: self.show_place(("chart",))),
            ("Ctrl+4", lambda: self.show_place(("directories",))),
            ("Ctrl+5", lambda: self.show_place(("templates",))),
            ("Ctrl+6", lambda: self.show_place(("inventory",))),
            ("Ctrl+7", lambda: self.show_place(("currencies",))),
            ("Ctrl+8", lambda: self.show_place(("invoices",))),
            ("Ctrl+9", lambda: self.show_place(("opening",))),
            ("Ctrl+0", lambda: self.show_place(("purchases",))),
            ("Ctrl+-", lambda: self.show_place(("sales",))),
            ("Ctrl+B", lambda: self.show_place(("bank",))),
            ("Ctrl+L", self.quick_entry),
            ("Ctrl+K", self.command_palette),
        ):
            QShortcut(QKeySequence(keys), self).activated.connect(fn)
        hints = QGuiApplication.styleHints()
        if hints is not None:
            hints.colorSchemeChanged.connect(lambda _scheme: self.follow_system_theme())

    def command_palette(self) -> CommandPalette | None:
        """Ctrl+K: find and do anything (D86)."""
        if self.session is None:
            return None
        palette = CommandPalette(self, lambda query: palette_entries(self, query))
        palette.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        palette.open()
        return palette

    def _company_menu(self) -> None:
        menu = QMenu(self)
        viewing = self.session is not None and self.session.read_only
        for company in self.workspace.companies():
            current = company.path == self.company_path and not viewing
            act = menu.addAction(("✓  " if current else "    ") + company.name)
            act.triggered.connect(lambda _=False, p=company.path: self.open_company(p))
        menu.addSeparator()
        menu.addAction(tr("Новая компания…")).triggered.connect(lambda: self.create_company())
        menu.addAction(tr("Добавить из файла…")).triggered.connect(self.add_company_file)
        menu.addAction(tr("Открыть для просмотра…")).triggered.connect(self.ask_view_company)
        if self.session is not None:
            menu.addSeparator()
            if viewing:
                menu.addAction(tr("Перечитать файл")).triggered.connect(self.reread)
            menu.addAction(tr("Показать файл компании")).triggered.connect(self.show_company_file)
            menu.addAction(tr("Передача дел…")).triggered.connect(self.hand_over)
            if not viewing and not self.session.stock_only:
                menu.addAction(tr("Закрытие периода…")).triggered.connect(self.close_period)
            if not viewing:
                self._file_actions(menu)
        menu.addSeparator()
        menu.addAction(tr("Ваше имя: {name}…", name=self.user_name())).triggered.connect(
            self.ask_user_name
        )
        languages = menu.addMenu(tr("Язык интерфейса"))
        for code, title in LANGUAGES.items():
            act = languages.addAction(("✓  " if code == language() else "    ") + title)
            act.triggered.connect(lambda _=False, c=code: self.set_ui_language(c))
        looks = menu.addMenu(tr("Оформление"))
        system = theme.SYSTEM_THEME
        mark = "✓  " if theme.current_theme() == system else "    "
        looks.addAction(mark + tr(theme.SYSTEM_TITLE)).triggered.connect(
            lambda: self.set_ui_theme(system)
        )
        looks.addSeparator()
        for name, (title, _) in theme.THEMES.items():
            act = looks.addAction(("✓  " if name == theme.current_theme() else "    ") + tr(title))
            act.triggered.connect(lambda _=False, n=name: self.set_ui_theme(n))
        looks.addSeparator()
        stripes = looks.addAction(("✓  " if zebra() else "    ") + tr("Полосы в таблицах"))
        stripes.triggered.connect(lambda: self.set_table_look(set_zebra, not zebra()))
        lines = looks.addAction(("✓  " if grid() else "    ") + tr("Сетка в отчётах"))
        lines.triggered.connect(lambda: self.set_table_look(set_grid, not grid()))
        btn = self.sidebar.company
        menu.exec(btn.mapToGlobal(btn.rect().bottomLeft()))

    def close_period(self) -> None:
        """«Закрытие периода» (D95): the pages are built again — what is closed now opens
        read-only, what is opened again can be changed."""
        if self._viewing() or not self._confirm_close_all():
            return
        if PeriodDialog(self.open_session, self).exec():
            self._reopen()

    def show_backups(self) -> None:
        """«Резервные копии» (D97): when and where, a copy now, the second folder."""
        if self._viewing() or self.conn is None or self.company_path is None:
            return
        BackupsDialog(self.workspace, self.conn, self.company_path, self.settings, self).exec()
        home = self.pages.get(("home",))
        if isinstance(home, HomePage):
            home.refresh()

    def _file_actions(self, menu: QMenu) -> None:
        """What changes the open company's file (not shown while viewing)."""
        s = self.open_session
        menu.addAction(tr("Сохранить как…")).triggered.connect(self.save_as)
        menu.addAction(tr("Сохранить копию…")).triggered.connect(self.save_copy)
        menu.addAction(tr("Резервные копии…")).triggered.connect(self.show_backups)
        menu.addAction(tr("Восстановить из копии…")).triggered.connect(self.restore_company)
        menu.addAction(tr("Удалить компанию…")).triggered.connect(self.delete_company)
        menu.addSeparator()
        menu.addAction(tr("VÖEN компании…")).triggered.connect(self.edit_tax_id)
        menu.addAction(tr("Плательщик ƏDV с…")).triggered.connect(self.edit_vat_payer)
        written = menu.addMenu(tr("Язык документов"))  # D152: the texts the program writes
        for code, title in LANGUAGES.items():
            act = written.addAction(("✓  " if code == document_language() else "    ") + title)
            act.triggered.connect(lambda _=False, c=code: self.set_document_language(c))
        stock_only = menu.addAction(tr("Только склад (без бухгалтерии)"))
        stock_only.setCheckable(True)
        stock_only.setChecked(s.stock_only)
        stock_only.toggled.connect(self.set_stock_only)
        if not s.stock_only:
            books = menu.addAction(tr("Параллельные книги (МСФО, налог)"))
            books.setCheckable(True)
            books.setChecked(s.parallel_books)
            books.toggled.connect(self.set_parallel_books)

    def _viewing(self) -> bool:
        """Viewing only (D80): nothing new is started; the status bar says why."""
        if self.session is None or not self.session.read_only:
            return False
        self.notify(tr("Компания открыта только для просмотра"))
        return True

    def _make_place(self, key) -> PageWidget:
        s = self.open_session
        if key == ("home",):
            page = HomePage(s, shown_places(s.stock_only))
            page.open_place.connect(self.show_place)
            page.open_backups.connect(self.show_backups)
            return page
        if key == ("journal",):
            page = JournalPage(s)
            page.open_document.connect(self.open_document)
            page.new_document.connect(self.new_document)
            page.deleted.connect(lambda doc_id: self.close_page(("doc", doc_id), ask=False))
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
            page.saved.connect(self._postings_changed)
            return page
        if key == ("currencies",):
            page = CurrenciesPage(s)
            page.open_document.connect(self.open_document)
            return page
        if key == ("inventory",):
            page = InventoryPage(s)
            page.open_inventory_document.connect(self.open_inventory_document)
            page.new_inventory_document.connect(self.new_inventory_document)
            page.open_landed_report.connect(self.open_landed_report)
            page.open_report.connect(self.open_catalog_report)
            return page
        if key in (("purchases",), ("sales",)):
            page = TradePage(s, PURCHASE if key == ("purchases",) else SALE)
            page.open_inventory_document.connect(self.open_inventory_document)
            page.new_inventory_document.connect(self.new_inventory_document)
            page.imported.connect(self._refresh_trade)
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
        return self._report_place(key)

    def show_import(self) -> None:
        if self._viewing():
            return
        key = ImportPage.key
        if key not in self.pages:
            page = ImportPage(self.open_session)
            page.imported.connect(self._imported)
            self._add_page(key, page, open_item=True)
        self._activate(key)

    def _imported(self, ids: list) -> None:
        self.show_place(("journal",))
        journal = self._page(("journal",), JournalPage)
        if journal is not None:
            journal.refresh(select_id=ids[-1])

    def quick_entry(self) -> None:
        """Ctrl+L anywhere: the journal with the cursor in the quick entry line."""
        if self.session is None or self._viewing() or self.session.stock_only:
            return
        self.show_place(("journal",))
        journal = self._page(("journal",), JournalPage)
        if journal is not None:
            journal.focus_quick_entry()

    def open_document(self, doc_id: int) -> None:
        """From the journal or a report: the primary document, as in 1C. Postings a module
        made (document_owners) open its document, where they are corrected."""
        s = self.open_session
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
        s = self.open_session
        if is_opening_document(s.conn, s.company_id, doc_id):
            self.show_place(("opening",))
            self.notify(tr("Начальные остатки вводятся один раз"))
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
        if key not in self.pages:
            page = DocumentPage(self.open_session, doc_id=doc_id)
            self._wire_document(page)
            self._add_page(key, page, open_item=True)
        self._activate(key)

    def new_document(self, template=None, entry=None) -> None:
        if self._viewing() or (self.session is not None and self.session.stock_only):
            return  # a journal document: not in a company kept as a warehouse only (D90)
        page = DocumentPage(self.open_session, template=template, entry=entry)
        self._wire_document(page)
        self._add_page(page.key, page, open_item=True)
        self._activate(page.key)

    def _wire_document(self, page: DocumentPage) -> None:
        page.saved.connect(lambda _id, p=page: self._document_saved(p))
        page.open_document.connect(self.open_document)
        page.copy_requested.connect(self.new_document)
        page.open_inventory_document.connect(self.open_inventory_document)
        page.new_requested.connect(lambda: self.new_document())
        page.template_saved.connect(self.open_template)
        page.close_requested.connect(lambda p=page: self.close_page(self._key_of(p)))
        page.title_changed.connect(lambda p=page: self._retitle(p))

    def open_conversion(self, conversion_id: int) -> None:
        key = ("conversion", conversion_id)
        if key not in self.pages:
            page = ConversionPage(self.open_session, conversion_id)
            self._wire_conversion(page)
            self._add_page(key, page, open_item=True)
        self._activate(key)

    def new_conversion(self, prefill=None) -> None:
        if self._viewing():
            return
        page = ConversionPage(self.open_session, prefill=prefill)
        self._wire_conversion(page)
        self._add_page(page.key, page, open_item=True)
        self._activate(page.key)

    def _wire_conversion(self, page: ConversionPage) -> None:
        page.saved.connect(lambda doc_id, p=page: self._conversion_saved(p, doc_id))
        page.open_gl_document.connect(self.show_document)
        page.copy_requested.connect(self.new_conversion)
        page.close_requested.connect(lambda p=page: self.close_page(self._key_of(p), ask=False))
        page.title_changed.connect(lambda p=page: self._retitle(p))

    def _conversion_saved(self, page: ConversionPage | BankOperationPage, doc_id: int) -> None:
        self._rekey(page)
        self._retitle(page)
        self._postings_changed(doc_id)

    def open_bank_operation(self, operation_id: int) -> None:
        key = ("bank_op", operation_id)
        if key not in self.pages:
            page = BankOperationPage(self.open_session, operation_id)
            self._wire_bank_operation(page)
            self._add_page(key, page, open_item=True)
        self._activate(key)

    def new_bank_operation(self, prefill=None) -> None:
        if self._viewing():
            return
        page = BankOperationPage(self.open_session, prefill=prefill)
        self._wire_bank_operation(page)
        self._add_page(page.key, page, open_item=True)
        self._activate(page.key)

    def _wire_bank_operation(self, page: BankOperationPage) -> None:
        page.saved.connect(lambda doc_id, p=page: self._conversion_saved(p, doc_id))
        page.open_gl_document.connect(self.show_document)
        page.copy_requested.connect(self.new_bank_operation)
        page.next_requested.connect(lambda data, p=page: self._next_bank_operation(p, data))
        page.close_requested.connect(lambda p=page: self.close_page(self._key_of(p), ask=False))
        page.title_changed.connect(lambda p=page: self._retitle(p))

    def _next_bank_operation(self, page: BankOperationPage, data) -> None:
        """A new operation posted: it is in the statement; the next one opens in its place."""
        self.close_page(self._key_of(page), ask=False)
        self.new_bank_operation(data)

    def open_inventory_document(self, document_id: int) -> None:
        key = ("inventory_doc", document_id)
        if key not in self.pages:
            session = self.open_session
            doc = Inventory(session.conn).load_document(session.company_id, document_id)
            page: InventoryDocumentPage | LandedCostPage = (
                LandedCostPage(session, document_id)
                if doc.doc_type == "landed_cost"
                else InventoryDocumentPage(session, document_id=document_id)
            )
            self._wire_inventory_document(page)
            self._add_page(key, page, open_item=True)
        self._activate(key)

    def new_inventory_document(self, doc_type: str) -> None:
        if self._viewing():
            return
        if doc_type == "count":  # a count makes its documents itself
            self.open_stock_count()
            return
        page: InventoryDocumentPage | LandedCostPage = (
            LandedCostPage(self.open_session)
            if doc_type == "landed_cost"
            else InventoryDocumentPage(self.open_session, doc_type=doc_type)
        )
        self._wire_inventory_document(page)
        self._add_page(page.key, page, open_item=True)
        self._activate(page.key)

    def open_stock_count(self) -> None:
        """«Инвентаризация»: one page; what it posts refreshes «Склад»."""
        if StockCountPage.key not in self.pages:
            page = StockCountPage(self.open_session)
            page.posted.connect(self._stock_counted)
            page.open_inventory_document.connect(self.open_inventory_document)
            self._add_page(StockCountPage.key, page, open_item=True)
        self._activate(StockCountPage.key)

    def _stock_counted(self) -> None:
        inventory = self._page(("inventory",), InventoryPage)
        if inventory is not None:
            inventory.refresh()

    def _wire_inventory_document(self, page: InventoryDocumentPage | LandedCostPage) -> None:
        page.saved.connect(lambda _id, p=page: self._inventory_document_saved(p))
        page.open_gl_document.connect(self.show_document)
        page.close_requested.connect(lambda p=page: self.close_page(self._key_of(p), ask=False))
        page.title_changed.connect(lambda p=page: self._retitle(p))

    def _inventory_document_saved(self, page: InventoryDocumentPage | LandedCostPage) -> None:
        self._rekey(page)
        self._retitle(page)
        inventory = self._page(("inventory",), InventoryPage)
        if inventory is not None:
            inventory.refresh()
        report = self._page(LandedCostReportPage.key, LandedCostReportPage)
        if report is not None:
            report.refresh()
        self._refresh_trade()

    def edit_vat_payer(self) -> None:
        """«Плательщик ƏDV с…» (D145): the ƏDV reports open are counted again."""
        if self.session is None or not edit_vat_payer(self, self.session):
            return
        for key in VAT_REPORTS:
            page = self.pages.get((key,))
            if isinstance(page, ReportPage):
                page.refresh()

    def _refresh_trade(self) -> None:
        for key in (("purchases",), ("sales",)):
            trade = self._page(key, TradePage)
            if trade is not None:
                trade.refresh()

    def open_template(self, template_id: int | None) -> None:
        """The template editor; a saved (or deleted) template returns to the list."""
        key = ("template", template_id)
        if template_id is not None and key in self.pages:
            self._activate(key)
            return
        if template_id is None and self._viewing():
            return
        page = TemplatePage(self.open_session, template_id)
        key = page.key
        page.saved.connect(lambda tid, p=page: self._template_saved(p, tid))
        page.close_requested.connect(lambda p=page: self.close_page(self._key_of(p), ask=False))
        page.title_changed.connect(lambda p=page: self._retitle(p))
        self._add_page(key, page, open_item=True)
        self._activate(key)

    def _template_saved(self, page: TemplatePage, template_id: int) -> None:
        templates = self._page(("templates",), TemplatesPage)
        if templates is not None:
            templates.refresh(select_id=template_id)
        self.close_page(self._key_of(page), ask=False)
        self.show_place(("templates",))

    def _document_saved(self, page: DocumentPage) -> None:
        self._rekey(page)
        self._retitle(page)
        journal = self._page(("journal",), JournalPage)
        if journal is not None:
            journal.refresh(select_id=page.doc_id)
