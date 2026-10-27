"""The main window: the sidebar beside the pages, made of its parts — the open company
(`CompanySession`), the open pages (`PageStack`), what opens where (`Navigator`, its
reports — `ReportPlaces`) — wired by signals; the window itself keeps what opens the
company again (the user's name, language, look). Its methods others call (tests, Ctrl+K)
hand the call to the part that does it."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QInputDialog,
    QMainWindow,
    QStackedWidget,
    QWidget,
)

from modern_gl.application.ledger import Ledger
from modern_gl.application.workspace import Workspace
from modern_gl.desktop import theme
from modern_gl.desktop.command_palette import CommandPalette
from modern_gl.desktop.main_window.commands import palette_entries
from modern_gl.desktop.main_window.company_files import CompanySession
from modern_gl.desktop.main_window.menus import company_menu
from modern_gl.desktop.main_window.navigator import Navigator
from modern_gl.desktop.main_window.page_stack import PageStack
from modern_gl.desktop.main_window.sidebar import Sidebar, place_icon, sections
from modern_gl.desktop.page import EmptyPage, PageWidget
from modern_gl.desktop.period_dialog import PeriodDialog
from modern_gl.desktop.preferences import Preferences
from modern_gl.desktop.reports_page import ReportParams
from modern_gl.desktop.session import Session
from modern_gl.desktop.shortcuts import PLACES_BY_KEY, bind
from modern_gl.desktop.toast import Toast
from modern_gl.desktop.verification_dialog import VerificationDialog
from modern_gl.domain.errors import LedgerError
from modern_gl.i18n import language, set_language, tr
from modern_gl.infrastructure.db import Connection


class MainWindow(QMainWindow):
    """The parts are fields (`company`, `page_stack`, `nav`, `reports`), wired in `_connect`."""

    def __init__(self, workspace: Workspace, settings: QSettings | None = None) -> None:
        super().__init__()
        self.resize(1360, 820)
        central = QWidget()
        lay = QHBoxLayout(central)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.sidebar = Sidebar()
        lay.addWidget(self.sidebar)
        self.stack = QStackedWidget()
        lay.addWidget(self.stack, 1)
        self.setCentralWidget(central)
        self.toast = Toast(self)
        self.page_stack = PageStack(self.sidebar, self.stack, self)
        self.company = CompanySession(
            workspace, settings, self, self.page_stack.confirm_close_all, self.notify
        )
        self.nav = Navigator(self.company, self.page_stack, self)
        self.reports = self.nav.reports
        self._connect()

    def _connect(self) -> None:
        """The parts hear each other; the keys of the whole window."""
        self.company.opened.connect(self._show_company)
        self.company.closing.connect(self.page_stack.drop)
        self.company.none_left.connect(self._show_no_company)
        self.page_stack.place_wanted.connect(self.nav.go)
        self.page_stack.unpin_wanted.connect(self.reports.unpin)
        self.sidebar.company.clicked.connect(self._company_menu)
        bind(self, "new_document", self.nav.new_document)
        bind(self, "close_page", self.page_stack.close_current)
        bind(self, "quick_entry", self.nav.quick_entry)
        bind(self, "palette", self.command_palette)
        for place in PLACES_BY_KEY:  # Ctrl+1… — the places of the sidebar
            bind(self, f"go_{place}", lambda p=place: self.nav.show_place((p,)))
        hints = QGuiApplication.styleHints()
        if hints is not None:  # a method, not a lambda: the application keeps no closure
            hints.colorSchemeChanged.connect(self.follow_system_theme)

    # ---- the open company: `CompanySession` -------------------------------------------

    @property
    def workspace(self) -> Workspace:
        return self.company.workspace

    @property
    def settings(self) -> QSettings | None:
        return self.company.settings

    @property
    def prefs(self) -> Preferences | None:
        return self.company.prefs

    @property
    def conn(self) -> Connection | None:
        return self.company.conn

    @property
    def ledger(self) -> Ledger | None:
        return self.company.ledger

    @property
    def session(self) -> Session | None:
        return self.company.session

    @property
    def company_path(self) -> Path | None:
        return self.company.company_path

    @property
    def open_session(self) -> Session:
        return self.company.open_session

    def start(self) -> bool:
        return self.company.start()

    def create_company(self, first: bool = False) -> bool:
        return self.company.create_company(first)

    def new_company(self) -> None:
        """«Новая компания…» of the company menu (not the first one)."""
        self.company.create_company()

    def open_company(self, path: Path) -> None:
        self.company.open_company(path)

    def view_company(self, path: Path) -> None:
        self.company.view_company(path)

    def reread(self) -> None:
        self.company.reread()

    def shutdown(self) -> None:
        self.company.shutdown()

    def save_as_to(self, target: Path, name: str) -> bool:
        return self.company.save_as_to(target, name)

    def hand_over(self) -> None:
        self.company.hand_over()

    def restore_from(self, source: Path, path: Path) -> bool:
        return self.company.restore_from(source, path)

    def delete_company(self) -> None:
        self.company.delete_company()

    def user_name(self) -> str:
        return self.company.user_name()

    def set_document_language(self, code: str) -> None:
        self.company.set_document_language(code)

    def set_stock_only(self, on: bool) -> None:
        self.company.set_stock_only(on)

    # ---- the window's own ---------------------------------------------------------------

    def command_palette(self) -> CommandPalette | None:
        """Ctrl+K: find and do anything (D86)."""
        if self.session is None:
            return None
        palette = CommandPalette(self, lambda query: palette_entries(self, query))
        palette.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        palette.open()
        return palette

    def _company_menu(self) -> None:
        company_menu(self)

    def close_period(self) -> None:
        """«Закрытие периода» (D95): the pages are built again — what is closed now opens
        read-only, what is opened again can be changed."""
        if self.company.viewing() or not self.page_stack.confirm_close_all():
            return
        if PeriodDialog(self.open_session, self).exec():
            self._reopen()

    def verify_books(self) -> None:
        """«Проверка книги» (D-new): what does not agree, each finding opens its document;
        after a rebuild the open pages show the new postings."""
        dialog = VerificationDialog(self.open_session, self.open_document, self)
        dialog.exec()
        for doc_id in dialog.changed:
            self.page_stack.postings_changed(doc_id)

    def _reopen(self) -> None:
        """The same company again (another language, look or books), on the same place."""
        place = self.page_stack.current_place()
        if self.company.reopen() and place is not None:
            self.nav.show_place(place)

    def ask_user_name(self) -> None:
        name, ok = QInputDialog.getText(
            self,
            tr("Ваше имя"),
            tr("Имя в журнале действий и в документах («Провёл …»):"),
            text=self.user_name(),
        )
        if ok and name.strip() and name.strip() != self.user_name():
            self.set_user_name(name.strip())

    def set_user_name(self, name: str) -> None:
        """The pages are built again: each module took the name when it opened."""
        if not self.page_stack.confirm_close_all():
            return
        if self.prefs:
            self.prefs.set_user_name(name)
        self._reopen()
        self.notify(tr("Ваше имя: {name}", name=name))

    def set_ui_language(self, code: str) -> None:
        if code == language() or not self.page_stack.confirm_close_all():
            return
        set_language(code)
        if self.prefs:
            self.prefs.set_language(code)
        self._reopen()

    def set_ui_theme(self, name: str) -> None:
        """Another look at once: the pages are built again in its colors."""
        if name == theme.current_theme() or not self.page_stack.confirm_close_all():
            return
        theme.use_theme(name)
        if self.prefs:
            self.prefs.set_theme(name)
        self._repaint()

    def set_table_look(self, change: Callable[[bool], None], on: bool) -> None:
        """«Полосы в таблицах», «Сетка в отчётах» (D103, D127): the pages built again."""
        change(on)
        self._repaint(reopen=not self.page_stack.dirty_pages())

    def follow_system_theme(self, _scheme: object = None) -> None:
        """The system turned light or dark: «as the system» follows it. Pages with
        unsaved changes are not built again — the new colors reach them on reopening."""
        if theme.current_theme() != theme.SYSTEM_THEME:
            return
        shown = theme.shown_theme()
        theme.use_theme(theme.SYSTEM_THEME)
        if theme.shown_theme() != shown:
            self._repaint(reopen=not self.page_stack.dirty_pages())

    def _repaint(self, reopen: bool = True) -> None:
        app = QApplication.instance()
        if isinstance(app, QApplication):
            theme.apply(app)
        if reopen:
            self._reopen()

    # ---- the pages: `PageStack` ---------------------------------------------------------

    @property
    def pages(self) -> dict[object, PageWidget]:
        return self.page_stack.pages

    @property
    def came_from(self) -> dict[PageWidget, object]:
        return self.page_stack.came_from

    @property
    def recent(self) -> list:
        return self.page_stack.recent

    def current_page(self) -> PageWidget | None:
        return self.page_stack.current_page()

    def close_current(self) -> None:
        self.page_stack.close_current()

    def close_page(self, key, ask: bool = True) -> None:
        self.page_stack.close_page(key, ask)

    def _show_company(self, name: str) -> None:
        read_only = self.open_session.read_only
        self.sidebar.company.setText(name)
        viewing = f" — {tr('только просмотр')}" if read_only else ""
        self.setWindowTitle(f"{name}{viewing} — Modern GL")
        stock_only = self.open_session.stock_only
        self.sidebar.retranslate(read_only, stock_only)
        for heading, places in sections(stock_only):
            if heading is not None:
                self.sidebar.add_section(tr(heading))
            for key, text in places:
                self.sidebar.add_item(key, tr(text), place_icon(key))
        self.sidebar.add_section(tr("Открытые")).setHidden(True)  # arrange_open shows it
        self.nav.show_place(("home",))
        self.reports.show_pins()

    def _show_no_company(self) -> None:
        self.sidebar.company.setText(tr("Нет компании"))
        self.sidebar.retranslate()
        self.setWindowTitle("Modern GL")
        self.page_stack.show_alone(
            EmptyPage(("empty",), tr("Нет компании"), tr("Создайте компанию в меню слева вверху."))
        )

    def notify(self, message: str, undo: Callable[[], None] | None = None) -> None:
        self.toast.show_message(message, None if undo is None else lambda: self._undo(undo))

    def _undo(self, undo: Callable[[], None]) -> None:
        """«Undo» on the toast: done, then the page shown reads it again."""
        try:
            undo()
        except LedgerError as e:
            self.toast.show_message(str(e))
            return
        key = self.page_stack.current_key()
        if key is not None:
            self.page_stack.activate(key)

    def closeEvent(self, event) -> None:
        if self.page_stack.confirm_close_all():
            event.accept()
        else:
            event.ignore()

    def keyPressEvent(self, event) -> None:
        # Esc nobody on the page wanted (an open cell or list takes it first): back
        if event.key() == Qt.Key.Key_Escape and not event.modifiers():
            self.close_current()
            return
        super().keyPressEvent(event)

    # ---- what opens where: `Navigator`, `ReportPlaces` --------------------------------

    def show_place(self, key) -> None:
        self.nav.show_place(key)

    def new_document(self, template=None, entry=None) -> None:
        self.nav.new_document(template, entry)

    def open_document(self, doc_id: int) -> None:
        self.nav.open_document(doc_id)

    def show_document(self, doc_id: int) -> None:
        self.nav.show_document(doc_id)

    def copy_document(self, doc_id: int) -> None:
        self.nav.copy_document(doc_id)

    def show_import(self) -> None:
        self.nav.show_import()

    def open_template(self, template_id: int | None) -> None:
        self.nav.open_template(template_id)

    def new_conversion(self, prefill=None) -> None:
        self.nav.new_conversion(prefill)

    def new_bank_operation(self, prefill=None) -> None:
        self.nav.new_bank_operation(prefill)

    def open_inventory_document(self, document_id: int) -> None:
        self.nav.open_inventory_document(document_id)

    def new_inventory_document(self, doc_type: str) -> None:
        self.nav.new_inventory_document(doc_type)

    def open_stock_count(self) -> None:
        self.nav.open_stock_count()

    def open_catalog_report(self, report_id: str) -> None:
        self.reports.open_catalog_report(report_id)

    def open_report(self, kind: str, account_id: int, params: ReportParams) -> None:
        self.reports.open_report(kind, account_id, params)

    def open_books(self) -> None:
        self.reports.open_books()

    def open_single(self, page_class) -> None:
        self.reports.open_single(page_class)

    def open_vat_register(self) -> None:
        self.reports.open_vat_register()

    def open_subconto_analysis(self) -> None:
        self.reports.open_subconto_analysis()

    def open_landed_report(self) -> None:
        self.reports.open_landed_report()

    def unpin(self, report_id: str) -> None:
        self.reports.unpin(report_id)
