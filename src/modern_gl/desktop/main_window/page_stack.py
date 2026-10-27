"""The window's pages: one shown at a time beside the sidebar; places open once, documents
and reports as open items that close back to where they were opened from."""

from __future__ import annotations

from typing import cast

from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QObject,
    QPropertyAnimation,
    Signal,
)
from PySide6.QtWidgets import (
    QGraphicsOpacityEffect,
    QLayout,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QSizePolicy,
    QStackedWidget,
    QWidget,
)

from modern_gl.desktop.main_window.sidebar import (
    ALL_OPEN,
    KEY_ROLE,
    PLACE_KEYS,
    REPORT_PAGES,
    NavDelegate,
    NavKeyed,
    PageT,
    Sidebar,
    open_icon,
)
from modern_gl.desktop.page import PageWidget
from modern_gl.desktop.reports_hub import HUB, PIN_KEYS
from modern_gl.i18n import tr


class PageStack(QObject):
    """The open pages by key, the one shown, the sidebar's items of them and where each
    was opened from. What is not open yet it does not make: it asks for it with
    `place_wanted` (a place of the sidebar, a pinned report), and `unpin_wanted` takes a
    pinned report off the sidebar."""

    place_wanted = Signal(object)  # a key of the sidebar with no page open for it
    unpin_wanted = Signal(str)  # a pinned report's id: off the sidebar

    def __init__(self, sidebar: Sidebar, stack: QStackedWidget, owner: QWidget) -> None:
        super().__init__(owner)
        self.owner = owner  # the window: menus and questions are shown over it
        self.sidebar = sidebar
        self.stack = stack
        self.pages: dict[object, PageWidget] = {}
        self.came_from: dict[PageWidget, object] = {}  # an open page → the page it was opened from
        self.recent: list = []  # open pages, the last shown first (the sidebar shows a few)
        self.stack.currentChanged.connect(self._size_by_current_page)
        self.sidebar.nav.currentItemChanged.connect(self._on_nav)
        self.sidebar.nav.itemClicked.connect(self._on_nav_click)
        self.sidebar.nav.customContextMenuRequested.connect(self._nav_menu)
        # kept: while the window is destroyed the sidebar is gone before this filter
        self._viewport = self.sidebar.nav.viewport()
        self._viewport.installEventFilter(self)

    def drop(self) -> None:
        """Every page goes (the company is closed), and the sidebar's items with them."""
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

    def add(self, key, page: PageWidget, open_item: bool = False) -> None:
        self.pages[key] = page
        self.stack.addWidget(page)
        self._size_by_current_page()
        if open_item:
            # closing it returns to the page it was opened from (the list of purchases…)
            self.came_from[page] = self.key_of(self.stack.currentWidget())
            self.sidebar.add_item(key, page.title(), open_icon(key))
            self._touch(key)

    def show_alone(self, page: PageWidget) -> None:
        """A page with no item in the sidebar («Нет компании»)."""
        self.pages[page.key] = page
        self.stack.addWidget(page)
        self.stack.setCurrentWidget(page)

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
        current = self.sidebar.item_for(self.key_of(self.stack.currentWidget()))
        if item is None or current is None:
            return
        self.sidebar.nav.blockSignals(True)  # the item is a button, not a place to stay on
        self.sidebar.nav.setCurrentItem(current)
        self.sidebar.nav.blockSignals(False)
        menu = QMenu(self.owner)
        for key in self.recent:
            menu.addAction(open_icon(key), self.pages[key].title()).triggered.connect(
                lambda _=False, key=key: self.activate(key)
            )
        rect = self.sidebar.nav.visualItemRect(item)
        menu.exec(self.sidebar.nav.viewport().mapToGlobal(rect.bottomLeft()))

    def activate(self, key) -> None:
        page = self.pages[key]
        self._touch(key)
        if self.stack.currentWidget() is not page:
            self.stack.setCurrentWidget(page)
            self._fade_in(page)
        self.select_nav(key, page)
        page.activated()

    def select_nav(self, key, page: PageWidget) -> None:
        """The sidebar's item of the page shown: its own, a pinned view of it, or — a
        report not pinned — «Все отчёты», where it was opened from (D114)."""
        nav = self.sidebar
        item = nav.item_for(key)
        if item is None and isinstance(page, NavKeyed):
            item = nav.item_for(page.nav_key())
        if item is None and key in REPORT_PAGES:
            item = nav.item_for(HUB)
        if item is not None and nav.nav.currentItem() is not item:
            nav.nav.blockSignals(True)
            nav.nav.setCurrentItem(item)
            nav.nav.blockSignals(False)

    def select_current(self) -> None:
        """The sidebar keeps the item of the page shown (a pinned report opened from it)."""
        page = self.current_page()
        if page is not None:
            self.select_nav(self.key_of(page), page)

    def _fade_in(self, page: PageWidget) -> None:
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
            self.activate(key)
        else:
            self.place_wanted.emit(key)

    def _on_nav_click(self, item: QListWidgetItem) -> None:
        if item.data(KEY_ROLE) == ALL_OPEN:
            self._all_open_menu()

    def _nav_menu(self, pos) -> None:
        item = self.sidebar.nav.itemAt(pos)
        key = item.data(KEY_ROLE) if item else None
        menu = QMenu(self.owner)
        if key in PIN_KEYS:
            menu.addAction(tr("Убрать из боковой панели")).triggered.connect(
                lambda: self.unpin_wanted.emit(PIN_KEYS[key])
            )
        elif NavDelegate.closable(key):
            menu.addAction(tr("Закрыть")).triggered.connect(lambda: self.close_page(key))
        else:
            return
        menu.exec(self.sidebar.nav.viewport().mapToGlobal(pos))

    def retitle(self, page: PageWidget) -> None:
        key = self.key_of(page)
        item = self.sidebar.item_for(key) if key is not None else None
        if item is not None:
            item.setText(page.title())

    def page(self, key, kind: type[PageT]) -> PageT | None:
        """The open page under `key` if it is of this kind."""
        page = self.pages.get(key)
        return page if isinstance(page, kind) else None

    def key_of(self, page: QWidget | None):
        return next((k for k, p in self.pages.items() if p is page), None)

    def current_page(self) -> PageWidget | None:
        """The page shown (None — no company)."""
        page = self.stack.currentWidget()
        return page if isinstance(page, PageWidget) else None

    def current_key(self):
        return self.key_of(self.stack.currentWidget())

    def close_current(self) -> None:
        key = self.current_key()
        if NavDelegate.closable(key):
            self.close_page(key)

    def close_page(self, key, ask: bool = True) -> None:
        page = self.pages.get(key)
        if page is None:
            return
        if ask and not self._confirm_close(page):
            return
        item = self.sidebar.item_for(key)
        # the sidebar moves its current item to a neighbour: not a place to open (Esc
        # would build and read the warehouse on its way back)
        self.sidebar.nav.blockSignals(True)
        if item is not None:
            self.sidebar.nav.takeItem(self.sidebar.nav.row(item))
        del self.pages[key]
        self.recent = [k for k in self.recent if k != key]
        self.sidebar.arrange_open(self.recent)
        self.sidebar.nav.blockSignals(False)
        self.stack.removeWidget(page)
        page.deleteLater()
        back = self.came_from.pop(page, None)
        self.place_wanted.emit(back if back in self.pages else ("journal",))

    def _confirm_close(self, page: PageWidget) -> bool:
        if not page.is_dirty():
            return True
        answer = QMessageBox.question(
            self.owner,
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

    def current_place(self) -> tuple | None:
        """The sidebar place shown (not an open document): kept when the window is rebuilt."""
        key = self.current_key()
        return key if isinstance(key, tuple) and key in PLACE_KEYS else None

    def dirty_pages(self) -> list[PageWidget]:
        return [p for p in self.pages.values() if p.is_dirty()]

    def postings_changed(self, doc_id: int) -> None:
        """Postings written (a document posted, balances saved): every open page hears it."""
        for page in list(self.pages.values()):
            page.on_postings_changed(doc_id)

    def confirm_close_all(self) -> bool:
        return all(self._confirm_close(p) for p in list(self.pages.values()))

    def eventFilter(self, watched, event) -> bool:
        """Click on the × of an open item in the sidebar closes it."""
        if (
            event.type()
            in (
                QEvent.Type.MouseButtonPress,
                QEvent.Type.MouseButtonRelease,
            )
            and watched is self._viewport
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
        return super().eventFilter(watched, event)

    def rekey(self, page: PageWidget) -> None:
        """A new document got its number: its page is kept under the new key."""
        old_key = self.key_of(page)
        if old_key is not None and old_key != page.key:
            self.pages[page.key] = self.pages.pop(old_key)
            self.recent = [page.key if k == old_key else k for k in self.recent]
            item = self.sidebar.item_for(old_key)
            if item is not None:
                item.setData(KEY_ROLE, page.key)
                item.setIcon(open_icon(page.key))
