"""Main window: Things-like sidebar (company, places, open items) + one page at a time."""

from __future__ import annotations

import getpass
import sqlite3

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QSettings, QSize, Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from modern_gl.application.catalog import Catalog
from modern_gl.application.ledger import Ledger
from modern_gl.application.queries import list_companies, load_document
from modern_gl.desktop.document_page import DocumentPage
from modern_gl.desktop.journal_page import JournalPage
from modern_gl.desktop.reports_page import REPORTS, ChartPage, OsvPage, ReportParams
from modern_gl.desktop.session import Session
from modern_gl.desktop.theme import P, dot_icon, fonts
from modern_gl.infrastructure.chart_csv import apply_chart_template

KEY_ROLE = Qt.ItemDataRole.UserRole
PLACES = [
    (("journal",), "Журнал", P.accent, "Ж", "Ctrl+1"),
    (("osv",), "ОСВ", P.green, "О", "Ctrl+2"),
    (("chart",), "План счетов", P.violet, "П", "Ctrl+3"),
]


class Sidebar(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("sidebar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedWidth(250)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 12)
        lay.setSpacing(0)
        self.company = QPushButton()
        self.company.setObjectName("company")
        self.company.setFont(fonts().heading)
        self.company.setCursor(Qt.CursorShape.PointingHandCursor)
        lay.addWidget(self.company)
        self.nav = QListWidget()
        self.nav.setObjectName("nav")
        self.nav.setIconSize(QSize(18, 18))
        self.nav.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.nav.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        lay.addWidget(self.nav, 1)
        hint = QLabel("Ctrl+N  новый документ\nCtrl+W  закрыть")
        hint.setObjectName("tertiary")
        hint.setFont(fonts().small)
        hint.setContentsMargins(20, 0, 0, 0)
        lay.addWidget(hint)

    def add_section(self, title: str) -> None:
        item = QListWidgetItem(title.upper())
        item.setFlags(Qt.ItemFlag.NoItemFlags)
        item.setFont(fonts().caption)
        item.setForeground(Qt.GlobalColor.gray)
        item.setSizeHint(QSize(0, 34))
        item.setData(KEY_ROLE, None)
        self.nav.addItem(item)

    def add_item(self, key, text: str, color: str, glyph: str = "") -> QListWidgetItem:
        item = QListWidgetItem(dot_icon(color, 18, glyph), text)
        item.setData(KEY_ROLE, key)
        item.setSizeHint(QSize(0, 34))
        self.nav.addItem(item)
        return item

    def find(self, key) -> QListWidgetItem | None:
        for i in range(self.nav.count()):
            if self.nav.item(i).data(KEY_ROLE) == key:
                return self.nav.item(i)
        return None


class MainWindow(QMainWindow):
    def __init__(self, conn: sqlite3.Connection, settings: QSettings | None = None) -> None:
        super().__init__()
        self.conn = conn
        self.settings = settings
        self.ledger = Ledger(conn, actor=getpass.getuser())
        self.session: Session | None = None
        self.pages: dict[object, QWidget] = {}
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
        self.statusBar().setSizeGripEnabled(False)

        self.sidebar.nav.currentItemChanged.connect(self._on_nav)
        self.sidebar.nav.customContextMenuRequested.connect(self._nav_menu)
        self.sidebar.company.clicked.connect(self._company_menu)

        for keys, fn in (
            ("Ctrl+N", self.new_document),
            ("Ctrl+W", self.close_current),
            ("Ctrl+F4", self.close_current),
            ("Ctrl+1", lambda: self.show_place(("journal",))),
            ("Ctrl+2", lambda: self.show_place(("osv",))),
            ("Ctrl+3", lambda: self.show_place(("chart",))),
        ):
            QShortcut(QKeySequence(keys), self).activated.connect(fn)

    # ---- companies -------------------------------------------------------------------

    def start(self) -> bool:
        """Open the last used company, or ask to create the first one."""
        companies = list_companies(self.conn)
        if not companies:
            return self.create_company(first=True)
        last = int(self.settings.value("company", 0)) if self.settings else 0
        ids = [cid for cid, _ in companies]
        self.open_company(last if last in ids else ids[0])
        return True

    def create_company(self, first: bool = False) -> bool:
        prompt = (
            "Добро пожаловать! Как называется первая компания?"
            if first
            else "Название новой компании:"
        )
        name, ok = QInputDialog.getText(self, "Новая компания", prompt)
        if not ok or not name.strip():
            return False
        cid = self.ledger.create_company(name.strip())
        apply_chart_template(self.ledger, cid, "1c77")
        self.open_company(cid)
        return True

    def open_company(self, company_id: int) -> None:
        if not self._confirm_close_all():
            return
        name = dict(list_companies(self.conn))[company_id]
        old_date = self.session.working_date if self.session else None
        self.session = Session(
            self.conn,
            self.ledger,
            company_id,
            name,
            Catalog(self.conn, company_id),
            notify=self.notify,
        )
        if old_date:
            self.session.working_date = old_date
        if self.settings:
            self.settings.setValue("company", company_id)
        for page in list(self.pages.values()):
            self.stack.removeWidget(page)
            page.deleteLater()
        self.pages.clear()
        self.sidebar.nav.clear()
        self.sidebar.company.setText(f"{name}   ▾")
        self.setWindowTitle(f"{name} — Modern GL")
        for key, text, color, glyph, _ in PLACES:
            self.sidebar.add_item(key, text, color, glyph)
        self.sidebar.add_section("Открытые")
        self.show_place(("journal",))

    def _company_menu(self) -> None:
        menu = QMenu(self)
        for cid, name in list_companies(self.conn):
            act = menu.addAction(
                ("✓  " if self.session and cid == self.session.company_id else "    ") + name
            )
            act.triggered.connect(lambda _=False, c=cid: self.open_company(c))
        menu.addSeparator()
        menu.addAction("Новая компания…").triggered.connect(lambda: self.create_company())
        btn = self.sidebar.company
        menu.exec(btn.mapToGlobal(btn.rect().bottomLeft()))

    # ---- pages -----------------------------------------------------------------------

    def _make_place(self, key) -> QWidget:
        s = self.session
        if key == ("journal",):
            page = JournalPage(s)
            page.open_document.connect(self.open_document)
            page.new_document.connect(self.new_document)
            page.copy_document.connect(
                lambda doc_id: self.new_document(load_document(s.conn, s.company_id, doc_id))
            )
            return page
        if key == ("osv",):
            page = OsvPage(s)
        else:
            page = ChartPage(s)
        self._wire_report(page)
        return page

    def _wire_report(self, page) -> None:
        page.open_document.connect(self.open_document)
        page.open_report.connect(self.open_report)

    def show_place(self, key) -> None:
        if key not in self.pages:
            self._add_page(key, self._make_place(key))
        self._activate(key)

    def _add_page(self, key, page: QWidget, open_item: bool = False) -> None:
        self.pages[key] = page
        self.stack.addWidget(page)
        if open_item:
            color = {"doc": P.amber, "new": P.accent}.get(key[0], P.teal)
            glyph = {"doc": "Д", "new": "+"}.get(key[0], "О")
            self.sidebar.add_item(key, page.title(), color, glyph)

    def _activate(self, key) -> None:
        page = self.pages[key]
        if self.stack.currentWidget() is not page:
            self.stack.setCurrentWidget(page)
            self._fade_in(page)
        item = self.sidebar.find(key)
        if item is not None and self.sidebar.nav.currentItem() is not item:
            self.sidebar.nav.blockSignals(True)
            self.sidebar.nav.setCurrentItem(item)
            self.sidebar.nav.blockSignals(False)
        if isinstance(page, JournalPage):
            page.refresh()
        if hasattr(page, "focus_table"):
            page.focus_table()

    def _fade_in(self, page: QWidget) -> None:
        effect = QGraphicsOpacityEffect(page)
        page.setGraphicsEffect(effect)
        anim = QPropertyAnimation(effect, b"opacity", page)
        anim.setDuration(140)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.finished.connect(lambda: page.setGraphicsEffect(None))
        anim.start()

    def _on_nav(self, current: QListWidgetItem | None, _previous) -> None:
        if current is None:
            return
        key = current.data(KEY_ROLE)
        if key is None:
            return
        if key in self.pages:
            self._activate(key)
        else:
            self.show_place(key)

    def _nav_menu(self, pos) -> None:
        item = self.sidebar.nav.itemAt(pos)
        key = item.data(KEY_ROLE) if item else None
        if key is None or key in [p[0] for p in PLACES]:
            return
        menu = QMenu(self)
        menu.addAction("Закрыть").triggered.connect(lambda: self.close_page(key))
        menu.exec(self.sidebar.nav.viewport().mapToGlobal(pos))

    def open_document(self, doc_id: int) -> None:
        key = ("doc", doc_id)
        if key not in self.pages:
            page = DocumentPage(self.session, doc_id=doc_id)
            self._wire_document(page)
            self._add_page(key, page, open_item=True)
        self._activate(key)

    def new_document(self, template=None) -> None:
        page = DocumentPage(self.session, template=template)
        self._wire_document(page)
        self._add_page(page.key, page, open_item=True)
        self._activate(page.key)

    def _wire_document(self, page: DocumentPage) -> None:
        page.saved.connect(lambda _id, p=page: self._document_saved(p))
        page.open_document.connect(self.open_document)
        page.copy_requested.connect(self.new_document)
        page.close_requested.connect(lambda p=page: self.close_page(self._key_of(p)))
        page.title_changed.connect(lambda p=page: self._retitle(p))

    def _document_saved(self, page: DocumentPage) -> None:
        old_key = self._key_of(page)
        if old_key is not None and old_key != page.key and page.doc is not None:
            # A new document got its number: re-key it in place.
            self.pages[page.key] = self.pages.pop(old_key)
            item = self.sidebar.find(old_key)
            if item is not None:
                item.setData(KEY_ROLE, page.key)
                item.setIcon(dot_icon(P.amber, 18, "Д"))
        self._retitle(page)
        journal = self.pages.get(("journal",))
        if journal is not None:
            journal.refresh(select_id=page.doc_id)

    def _retitle(self, page: QWidget) -> None:
        key = self._key_of(page)
        item = self.sidebar.find(key) if key is not None else None
        if item is not None:
            item.setText(page.title())

    def _key_of(self, page: QWidget):
        return next((k for k, p in self.pages.items() if p is page), None)

    def open_report(self, kind: str, code: str, params: ReportParams) -> None:
        key = (kind, code)
        if key in self.pages:
            self.close_page(key, ask=False)
        page = REPORTS[kind](self.session, code, params)
        self._wire_report(page)
        self._add_page(key, page, open_item=True)
        self._activate(key)

    def close_current(self) -> None:
        key = self._key_of(self.stack.currentWidget())
        if key is not None and key not in [p[0] for p in PLACES]:
            self.close_page(key)

    def close_page(self, key, ask: bool = True) -> None:
        page = self.pages.get(key)
        if page is None:
            return
        if ask and not self._confirm_close(page):
            return
        item = self.sidebar.find(key)
        if item is not None:
            self.sidebar.nav.takeItem(self.sidebar.nav.row(item))
        del self.pages[key]
        self.stack.removeWidget(page)
        page.deleteLater()
        self.show_place(("journal",))

    def _confirm_close(self, page) -> bool:
        if not page.is_dirty():
            return True
        answer = QMessageBox.question(
            self,
            "Несохранённые изменения",
            f"Сохранить «{page.title().rstrip(' •')}»?",
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

    def notify(self, message: str) -> None:
        self.statusBar().showMessage(message, 6000)
