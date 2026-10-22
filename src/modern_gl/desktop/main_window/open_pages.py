"""The window's pages: one shown at a time beside the sidebar; places open once, documents
and reports as open items that close back to where they were opened from."""

from __future__ import annotations

from typing import cast

from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QPropertyAnimation,
    QSettings,
    Qt,
)
from PySide6.QtWidgets import (
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLayout,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QSizePolicy,
    QStackedWidget,
    QWidget,
)

from modern_gl.desktop.bank_page import BankPage
from modern_gl.desktop.directories_page import DirectoriesPage
from modern_gl.desktop.inventory_page import InventoryPage
from modern_gl.desktop.journal_page import JournalPage
from modern_gl.desktop.main_window.company_files import CompanyFiles
from modern_gl.desktop.main_window.sidebar import (
    ALL_OPEN,
    KEY_ROLE,
    FocusablePage,
    NavDelegate,
    PageT,
    Sidebar,
    TitledPage,
    open_icon,
    place_icon,
    sections,
    shown_places,
)
from modern_gl.desktop.opening_balances_page import OpeningBalancesPage
from modern_gl.desktop.widgets import EmptyState
from modern_gl.i18n import tr
from modern_gl.infrastructure.workspace import Workspace


class OpenPages(CompanyFiles):
    def __init__(self, workspace: Workspace, settings: QSettings | None = None) -> None:
        super().__init__(workspace, settings)
        self.pages: dict[object, QWidget] = {}
        self.came_from: dict[QWidget, object] = {}  # an open page → the page it was opened from
        self.recent: list = []  # open pages, the last shown first (the sidebar shows a few)
        self.resize(1360, 820)

        central = QWidget()
        lay = QHBoxLayout(central)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.sidebar = Sidebar()
        lay.addWidget(self.sidebar)
        self.stack = QStackedWidget()
        self.stack.currentChanged.connect(self._size_by_current_page)
        lay.addWidget(self.stack, 1)
        self.setCentralWidget(central)
        self.statusBar().setSizeGripEnabled(False)

        self.sidebar.nav.currentItemChanged.connect(self._on_nav)
        self.sidebar.nav.itemClicked.connect(self._on_nav_click)
        self.sidebar.nav.customContextMenuRequested.connect(self._nav_menu)
        self.sidebar.nav.viewport().installEventFilter(self)

    # ---- the company shown -----------------------------------------------------------

    def _show_company(self, name: str) -> None:
        read_only = self.open_session.read_only
        self.sidebar.company.setText(f"{name}   ▾")
        viewing = f" — {tr('только просмотр')}" if read_only else ""
        self.setWindowTitle(f"{name}{viewing} — Modern GL")
        stock_only = self.open_session.stock_only
        self.sidebar.retranslate(read_only, stock_only)
        for heading, places in sections(stock_only):
            if heading is not None:
                self.sidebar.add_section(tr(heading))
            for key, text in places:
                self.sidebar.add_item(key, tr(text), place_icon(key))
        self.sidebar.add_section(tr("Открытые"))
        self.show_place(("inventory",) if stock_only else ("journal",))

    def _drop_pages(self) -> None:
        # quietly: clearing moves the current item, and that would open a page again
        # with this company, whose file is closed right below
        self.sidebar.nav.blockSignals(True)
        self.sidebar.nav.clear()
        self.sidebar.nav.blockSignals(False)
        for page in list(self.pages.values()):
            self.stack.removeWidget(page)
            page.deleteLater()
        self.pages.clear()
        self.came_from.clear()
        self.recent.clear()

    def _add_page(self, key, page: QWidget, open_item: bool = False) -> None:
        self.pages[key] = page
        self.stack.addWidget(page)
        self._size_by_current_page()
        if open_item:
            # closing it returns to the page it was opened from (the list of purchases…)
            self.came_from[page] = self._key_of(self.stack.currentWidget())
            title = page.title() if isinstance(page, TitledPage) else ""
            self.sidebar.add_item(key, title, open_icon(key))
            self._touch(key)

    def _size_by_current_page(self, _index: int = 0) -> None:
        """Only the page shown sets how narrow the window may get: a stack takes the
        widest of all its pages, so the OSV with its options, once opened, kept every
        page wider than a laptop screen."""
        current = self.stack.currentWidget()
        for i in range(self.stack.count()):
            page = cast(QWidget, self.stack.widget(i))
            policy = QSizePolicy.Policy.Preferred if page is current else QSizePolicy.Policy.Ignored
            page.setSizePolicy(policy, policy)
        cast(QLayout, self.stack.layout()).invalidate()  # a hidden page does not report it
        self.stack.updateGeometry()

    def _touch(self, key) -> None:
        """An open page was shown: first among the recent ones, so the sidebar shows it."""
        if NavDelegate.closable(key):
            self.recent = [key] + [k for k in self.recent if k != key]
            self.sidebar.arrange_open(self.recent)

    def _all_open_menu(self) -> None:
        """«All (N)…»: every open page in a menu, the last shown first."""
        item = self.sidebar.item_for(ALL_OPEN)
        current = self.sidebar.item_for(self._key_of(self.stack.currentWidget()))
        if item is None or current is None:
            return
        self.sidebar.nav.blockSignals(True)  # the item is a button, not a place to stay on
        self.sidebar.nav.setCurrentItem(current)
        self.sidebar.nav.blockSignals(False)
        menu = QMenu(self)
        for key in self.recent:
            page = self.pages[key]
            title = page.title() if isinstance(page, TitledPage) else ""
            menu.addAction(open_icon(key), title).triggered.connect(
                lambda _=False, key=key: self._activate(key)
            )
        rect = self.sidebar.nav.visualItemRect(item)
        menu.exec(self.sidebar.nav.viewport().mapToGlobal(rect.bottomLeft()))

    def _activate(self, key) -> None:
        page = self.pages[key]
        self._touch(key)
        if self.stack.currentWidget() is not page:
            self.stack.setCurrentWidget(page)
            self._fade_in(page)
        item = self.sidebar.item_for(key)
        if item is not None and self.sidebar.nav.currentItem() is not item:
            self.sidebar.nav.blockSignals(True)
            self.sidebar.nav.setCurrentItem(item)
            self.sidebar.nav.blockSignals(False)
        if isinstance(page, JournalPage):
            page.refresh()
        if isinstance(page, InventoryPage):
            page.refresh()
        if isinstance(page, OpeningBalancesPage):
            page.refresh()
        if isinstance(page, BankPage):
            page.refresh()
        if isinstance(page, DirectoriesPage):  # elements added elsewhere (e-qaimə import…)
            page.refresh(keep_value=True)
        if isinstance(page, FocusablePage):
            page.focus_table()

    def _fade_in(self, page: QWidget) -> None:
        effect = QGraphicsOpacityEffect(page)
        page.setGraphicsEffect(effect)
        anim = QPropertyAnimation(effect, b"opacity", page)
        anim.setDuration(140)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        # None removes the effect; the PySide6 stubs do not allow it
        anim.finished.connect(lambda: page.setGraphicsEffect(None))  # pyright: ignore[reportArgumentType]
        anim.start()

    def _on_nav(self, current: QListWidgetItem | None, _previous) -> None:
        if current is None:
            return
        key = current.data(KEY_ROLE)
        if key is None:
            return
        if key == ALL_OPEN:  # a button, not a place: it answers a click (_on_nav_click)
            return
        if key in self.pages:
            self._activate(key)
        else:
            self.show_place(key)

    def _on_nav_click(self, item: QListWidgetItem) -> None:
        if item.data(KEY_ROLE) == ALL_OPEN:
            self._all_open_menu()

    def _nav_menu(self, pos) -> None:
        item = self.sidebar.nav.itemAt(pos)
        key = item.data(KEY_ROLE) if item else None
        if not NavDelegate.closable(key):
            return
        menu = QMenu(self)
        menu.addAction(tr("Закрыть")).triggered.connect(lambda: self.close_page(key))
        menu.exec(self.sidebar.nav.viewport().mapToGlobal(pos))

    def _retitle(self, page: QWidget) -> None:
        key = self._key_of(page)
        item = self.sidebar.item_for(key) if key is not None else None
        if item is not None and isinstance(page, TitledPage):
            item.setText(page.title())

    def _page(self, key, kind: type[PageT]) -> PageT | None:
        """The open page under `key` if it is of this kind."""
        page = self.pages.get(key)
        return page if isinstance(page, kind) else None

    def _key_of(self, page: QWidget | None):
        return next((k for k, p in self.pages.items() if p is page), None)

    def close_current(self) -> None:
        key = self._key_of(self.stack.currentWidget())
        if NavDelegate.closable(key):
            self.close_page(key)

    def close_page(self, key, ask: bool = True) -> None:
        page = self.pages.get(key)
        if page is None:
            return
        if ask and not self._confirm_close(page):
            return
        item = self.sidebar.item_for(key)
        if item is not None:
            self.sidebar.nav.takeItem(self.sidebar.nav.row(item))
        del self.pages[key]
        self.recent = [k for k in self.recent if k != key]
        self.sidebar.arrange_open(self.recent)
        self.stack.removeWidget(page)
        page.deleteLater()
        back = self.came_from.pop(page, None)
        self.show_place(back if back in self.pages else ("journal",))

    def _confirm_close(self, page) -> bool:
        if not getattr(page, "is_dirty", lambda: False)():  # e.g. the empty-state page
            return True
        answer = QMessageBox.question(
            self,
            tr("Несохранённые изменения"),
            tr("Сохранить «{title}»?", title=page.title().rstrip(" •")),
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Save,
        )
        if answer == QMessageBox.StandardButton.Save:
            return page.save(post=False)
        return answer == QMessageBox.StandardButton.Discard

    def _confirm_close_all(self) -> bool:
        return all(self._confirm_close(p) for p in list(self.pages.values()))

    def closeEvent(self, event) -> None:
        if self._confirm_close_all():
            event.accept()
        else:
            event.ignore()

    def keyPressEvent(self, event) -> None:
        # Esc nobody on the page wanted (an open cell or list takes it first): back
        if event.key() == Qt.Key.Key_Escape and not event.modifiers():
            self.close_current()
            return
        super().keyPressEvent(event)

    def eventFilter(self, obj, event) -> bool:
        """Click on the × of an open item in the sidebar closes it."""
        if obj is self.sidebar.nav.viewport() and event.type() in (
            QEvent.Type.MouseButtonPress,
            QEvent.Type.MouseButtonRelease,
        ):
            pos = event.position().toPoint()
            item = self.sidebar.nav.itemAt(pos)
            key = item.data(KEY_ROLE) if item else None
            if item is not None and NavDelegate.closable(key):
                rect = NavDelegate.close_rect(self.sidebar.nav.visualItemRect(item))
                if rect.adjusted(-4, -4, 4, 4).contains(pos):
                    if event.type() == QEvent.Type.MouseButtonRelease:
                        self.close_page(key)
                    return True
        return super().eventFilter(obj, event)

    def notify(self, message: str) -> None:
        self.statusBar().showMessage(message, 6000)

    def show_place(self, key) -> None:
        if self.session is not None and key not in shown_places(self.session.stock_only):
            return  # a page of the books, in a company kept as a warehouse only (D90)
        if key not in self.pages:
            self._add_page(key, self._make_place(key))
        self._activate(key)

    def _show_no_company(self) -> None:
        self.sidebar.company.setText(tr("Нет компании") + "   ▾")
        self.sidebar.retranslate()
        self.setWindowTitle("Modern GL")
        page = EmptyState("○", tr("Нет компании"), tr("Создайте компанию в меню слева вверху."))
        self.pages[("empty",)] = page
        self.stack.addWidget(page)
        self.stack.setCurrentWidget(page)

    def _rekey(self, page) -> None:
        """A new document got its number: its page is kept under the new key."""
        old_key = self._key_of(page)
        if old_key is not None and old_key != page.key and page.doc is not None:
            self.pages[page.key] = self.pages.pop(old_key)
            self.recent = [page.key if k == old_key else k for k in self.recent]
            item = self.sidebar.item_for(old_key)
            if item is not None:
                item.setData(KEY_ROLE, page.key)
                item.setIcon(open_icon(page.key))

    # ---- what the places are; made by the window -------------------------------------

    def _make_place(self, key) -> QWidget:
        raise NotImplementedError
