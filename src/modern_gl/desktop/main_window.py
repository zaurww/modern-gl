"""Main window: Things-like sidebar (company, places, open items) + one page at a time."""

from __future__ import annotations

import getpass
import sqlite3
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Protocol, TypeVar, runtime_checkable

from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QPropertyAnimation,
    QRect,
    QRectF,
    QSettings,
    QSize,
    Qt,
    QUrl,
)
from PySide6.QtGui import (
    QColor,
    QDesktopServices,
    QIcon,
    QKeySequence,
    QPainter,
    QPen,
    QShortcut,
)
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QStyle,
    QStyledItemDelegate,
    QVBoxLayout,
    QWidget,
)

from modern_gl.application.catalog import Catalog
from modern_gl.application.inventory import Inventory
from modern_gl.application.ledger import Ledger
from modern_gl.application.queries import company_name, load_document, load_template
from modern_gl.desktop import icons, theme
from modern_gl.desktop.currencies_page import CurrenciesPage
from modern_gl.desktop.directories_page import DirectoriesPage
from modern_gl.desktop.document_page import DocumentPage
from modern_gl.desktop.import_page import ImportPage
from modern_gl.desktop.inventory_document_page import InventoryDocumentPage
from modern_gl.desktop.inventory_page import InventoryPage
from modern_gl.desktop.journal_page import JournalPage
from modern_gl.desktop.landed_cost_page import LandedCostPage
from modern_gl.desktop.reports_page import REPORTS, ChartPage, OsvPage, ReportParams
from modern_gl.desktop.session import Session
from modern_gl.desktop.templates_page import TemplatePage, TemplatesPage
from modern_gl.desktop.theme import P, fonts
from modern_gl.desktop.widgets import EmptyState
from modern_gl.i18n import LANGUAGES, language, set_language, tr
from modern_gl.infrastructure import backup
from modern_gl.infrastructure.workspace import TRASH, Workspace
from modern_gl.reporting.inventory import inventory_document_of

KEY_ROLE = Qt.ItemDataRole.UserRole
PLACES = [  # key, title (translated on display), icon color
    (("journal",), "Журнал", P.accent),
    (("osv",), "ОСВ", P.green),
    (("chart",), "План счетов", P.violet),
    (("inventory",), "Склад", P.amber),
    (("directories",), "Справочники", P.teal),
    (("templates",), "Шаблоны", P.amber),
    (("currencies",), "Валюты", P.green),
]
PLACE_KEYS = [key for key, _, _ in PLACES]
# open pages: a quiet grey icon of what they are (a new document is the blue plus)
OPEN_ICONS = {"doc": "document", "new": "new", "template": "templates", "import": "import"}
OPEN_ICONS |= {"inventory_doc": "inventory", "new_inventory": "inventory"}


def open_icon(key) -> QIcon:
    name = OPEN_ICONS.get(key[0], "report")
    return icons.icon(name, P.accent if name == "new" else P.secondary)


PageT = TypeVar("PageT", bound=QWidget)


@runtime_checkable
class TitledPage(Protocol):
    """A page shown as an item in the sidebar's "Open" section."""

    def title(self) -> str: ...


@runtime_checkable
class FocusablePage(Protocol):
    def focus_table(self) -> None: ...


class NavDelegate(QStyledItemDelegate):
    """Draws a small × on open items (on hover or when selected), like a tab's close button."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)

    @staticmethod
    def closable(key) -> bool:
        return key is not None and key not in PLACE_KEYS

    @staticmethod
    def close_rect(rect: QRect) -> QRect:
        return QRect(rect.right() - 32, rect.center().y() - 8, 16, 16)

    def paint(self, painter, option, index) -> None:
        super().paint(painter, option, index)
        state = option.state
        hot = state & (QStyle.StateFlag.State_MouseOver | QStyle.StateFlag.State_Selected)
        if not hot or not self.closable(index.data(KEY_ROLE)):
            return
        r = QRectF(self.close_rect(option.rect)).adjusted(4.5, 4.5, -4.5, -4.5)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor(P.secondary), 1.5)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawLine(r.topLeft(), r.bottomRight())
        painter.drawLine(r.topRight(), r.bottomLeft())
        painter.restore()


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
        self.nav.setMouseTracking(True)
        self.nav.setItemDelegate(NavDelegate(self.nav))
        self.hint = QLabel()
        self.hint.setObjectName("tertiary")
        self.hint.setFont(fonts().small)
        self.hint.setContentsMargins(20, 0, 0, 0)
        lay.addWidget(self.hint)
        self.retranslate()

    def retranslate(self) -> None:
        self.hint.setText(tr("Ctrl+N  новый документ\nCtrl+W  закрыть"))

    def add_section(self, title: str) -> None:
        item = QListWidgetItem(title.upper())
        item.setFlags(Qt.ItemFlag.NoItemFlags)
        item.setFont(fonts().caption)
        item.setForeground(Qt.GlobalColor.gray)
        item.setSizeHint(QSize(0, 34))
        item.setData(KEY_ROLE, None)
        self.nav.addItem(item)

    def add_item(self, key, text: str, icon: QIcon) -> QListWidgetItem:
        item = QListWidgetItem(icon, text)
        item.setData(KEY_ROLE, key)
        item.setSizeHint(QSize(0, 34))
        self.nav.addItem(item)
        return item

    def item_for(self, key) -> QListWidgetItem | None:
        for i in range(self.nav.count()):
            if self.nav.item(i).data(KEY_ROLE) == key:
                return self.nav.item(i)
        return None


def confirm_delete(parent: QWidget, name: str) -> bool:
    """Deleting a company is confirmed by typing its name, like on GitHub."""
    dlg = QDialog(parent)
    dlg.setWindowTitle(tr("Удалить компанию"))
    lay = QVBoxLayout(dlg)
    lay.setContentsMargins(24, 22, 24, 18)
    lay.setSpacing(12)
    text = QLabel(
        tr(
            "Компания «{name}» исчезнет из списка. Её файл будет перемещён в папку «{trash}», "
            "откуда его можно вернуть.\n\nЧтобы подтвердить, введите название компании:",
            name=name,
            trash=TRASH,
        )
    )
    text.setWordWrap(True)
    lay.addWidget(text)
    edit = QLineEdit()
    edit.setPlaceholderText(name)
    lay.addWidget(edit)
    buttons = QHBoxLayout()
    buttons.addStretch(1)
    cancel = QPushButton(tr("Отмена"))
    delete = QPushButton(tr("Удалить компанию"))
    delete.setObjectName("dangerSolid")
    delete.setEnabled(False)
    edit.textChanged.connect(lambda s: delete.setEnabled(s.strip() == name))
    cancel.clicked.connect(dlg.reject)
    delete.clicked.connect(dlg.accept)
    buttons.addWidget(cancel)
    buttons.addWidget(delete)
    lay.addLayout(buttons)
    return dlg.exec() == QDialog.DialogCode.Accepted


class MainWindow(QMainWindow):
    def __init__(self, workspace: Workspace, settings: QSettings | None = None) -> None:
        super().__init__()
        self.workspace = workspace
        self.settings = settings
        self.conn: sqlite3.Connection | None = None
        self.ledger: Ledger | None = None
        self.company_path: Path | None = None
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
        self.sidebar.nav.viewport().installEventFilter(self)

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
            ("Ctrl+L", self.quick_entry),
        ):
            QShortcut(QKeySequence(keys), self).activated.connect(fn)

    @property
    def open_session(self) -> Session:
        """The open company. Pages exist only while one is open."""
        if self.session is None:
            raise RuntimeError("no company is open")
        return self.session

    # ---- companies: one file each ----------------------------------------------------

    def start(self) -> bool:
        """Open the last used company, or ask to create the first one."""
        companies = self.workspace.companies()
        if not companies:
            return self.create_company(first=True)
        last = str(self.settings.value("company_file", "")) if self.settings else ""
        paths = [c.path for c in companies]
        self.open_company(next((p for p in paths if str(p) == last), paths[0]))
        return True

    def create_company(self, first: bool = False) -> bool:
        prompt = (
            tr("Добро пожаловать! Как называется первая компания?")
            if first
            else tr("Название новой компании:")
        )
        name, ok = QInputDialog.getText(self, tr("Новая компания"), prompt)
        if not ok or not name.strip():
            return False
        if not self._confirm_close_all():
            return False
        self.open_company(self.workspace.create(name.strip()))
        return True

    def open_company(self, path: Path) -> None:
        if not self._confirm_close_all():
            return
        try:
            conn, company_id = self.workspace.open(path)
        except backup.BackupError as e:
            self._offer_restore(Path(path), str(e))
            return
        old_date = self.session.working_date if self.session else None
        self._close_company()
        self.conn, self.company_path = conn, Path(path)
        self.ledger = Ledger(conn, actor=getpass.getuser())
        name = company_name(conn, company_id)
        self.session = Session(
            conn, self.ledger, company_id, name, Catalog(conn, company_id), notify=self.notify
        )
        if old_date:
            self.session.working_date = old_date
        if self.settings:
            self.settings.setValue("company_file", str(path))
        self.sidebar.company.setText(f"{name}   ▾")
        self.setWindowTitle(f"{name} — Modern GL")
        self.sidebar.retranslate()
        for key, text, color in PLACES:
            self.sidebar.add_item(key, tr(text), icons.icon(key[0], color))
        self.sidebar.add_section(tr("Открытые"))
        self.show_place(("journal",))

    def _close_company(self) -> None:
        """Drop all pages of the current company and close its file."""
        # quietly: clearing moves the current item, and that would open a page again
        # with this company, whose file is closed right below
        self.sidebar.nav.blockSignals(True)
        self.sidebar.nav.clear()
        self.sidebar.nav.blockSignals(False)
        for page in list(self.pages.values()):
            self.stack.removeWidget(page)
            page.deleteLater()
        self.pages.clear()
        if self.conn is not None:
            try:
                if self.company_path is not None:
                    self.workspace.auto_backup(self.conn, self.company_path)
            except (backup.BackupError, OSError, sqlite3.Error) as e:
                QMessageBox.warning(
                    self, tr("Резервная копия"), tr("Копия не сохранена: {error}", error=e)
                )
            self.conn.close()
        self.conn = self.ledger = self.session = self.company_path = None

    def shutdown(self) -> None:
        self._close_company()

    def _company_menu(self) -> None:
        menu = QMenu(self)
        for company in self.workspace.companies():
            current = company.path == self.company_path
            act = menu.addAction(("✓  " if current else "    ") + company.name)
            act.triggered.connect(lambda _=False, p=company.path: self.open_company(p))
        menu.addSeparator()
        menu.addAction(tr("Новая компания…")).triggered.connect(lambda: self.create_company())
        menu.addAction(tr("Добавить из файла…")).triggered.connect(self.add_company_file)
        if self.session is not None:
            menu.addSeparator()
            menu.addAction(tr("Показать файл компании")).triggered.connect(self.show_company_file)
            menu.addAction(tr("Сохранить копию…")).triggered.connect(self.save_copy)
            menu.addAction(tr("Восстановить из копии…")).triggered.connect(self.restore_company)
            menu.addAction(tr("Удалить компанию…")).triggered.connect(self.delete_company)
        menu.addSeparator()
        languages = menu.addMenu(tr("Язык интерфейса"))
        for code, title in LANGUAGES.items():
            act = languages.addAction(("✓  " if code == language() else "    ") + title)
            act.triggered.connect(lambda _=False, c=code: self.set_ui_language(c))
        looks = menu.addMenu(tr("Оформление"))
        for name, (title, _) in theme.THEMES.items():
            act = looks.addAction(("✓  " if name == theme.current_theme() else "    ") + tr(title))
            act.triggered.connect(lambda _=False, n=name: self.set_ui_theme(n))
        btn = self.sidebar.company
        menu.exec(btn.mapToGlobal(btn.rect().bottomLeft()))

    def add_company_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            tr("Добавить компанию из файла"),
            "",
            tr("Файлы компаний (*.gl *.db);;Все файлы (*)"),
        )
        if not path:
            return
        try:
            added = self.workspace.add_file(Path(path))
        except sqlite3.DatabaseError:
            QMessageBox.warning(
                self,
                tr("Добавить из файла"),
                tr("Это не файл компании: {file}", file=Path(path).name),
            )
            return
        if added:
            self.open_company(added[0])
            self.notify(tr("Добавлено компаний: {n}", n=len(added)))

    # ---- backups ---------------------------------------------------------------------

    def save_copy(self) -> None:
        """A copy of the company to hand over or keep elsewhere (a flash drive…)."""
        if self.conn is None or self.company_path is None:
            return
        suggested = Path.home() / f"{self.company_path.stem} {datetime.now():%Y-%m-%d}.gl"
        target, _ = QFileDialog.getSaveFileName(
            self, tr("Сохранить копию компании"), str(suggested), tr("Файлы компаний (*.gl)")
        )
        if not target:
            return
        try:
            backup.copy_to(self.conn, Path(target))
        except (backup.BackupError, OSError, sqlite3.Error) as e:
            QMessageBox.warning(self, tr("Сохранить копию"), str(e))
            return
        self.notify(tr("Копия сохранена: {file}", file=target))

    def restore_company(self) -> None:
        if self.company_path is not None:
            self._offer_restore(self.company_path)

    def _offer_restore(self, path: Path, problem: str = "") -> None:
        """Choose one of the company's backups (or another file) and put it in place."""
        backups = self.workspace.backups(path)
        other = tr("Другой файл…")
        labels = [
            f"{b.made_at:%d.%m.%Y  %H:%M:%S}   ·   {b.size // 1024} KB"
            + (f"   ·   {b.path.stem.rsplit('(', 1)[1].rstrip(')')}" if "(" in b.path.stem else "")
            for b in backups
        ]
        prompt = (problem + "\n\n" if problem else "") + tr(
            "Из какой копии восстановить «{name}»? Текущий файл тоже сохранится копией.",
            name=path.stem,
        )
        choice, ok = QInputDialog.getItem(
            self, tr("Восстановить из копии"), prompt, [*labels, other], 0, False
        )
        if not ok:
            return
        if choice == other:
            chosen, _ = QFileDialog.getOpenFileName(
                self, tr("Восстановить из копии"), "", tr("Файлы компаний (*.gl *.db)")
            )
            if not chosen:
                return
            source = Path(chosen)
        else:
            source = backups[labels.index(choice)].path
        self.restore_from(source, path)

    def restore_from(self, source: Path, path: Path) -> bool:
        if not self._confirm_close_all():
            return False
        if self.company_path == path:
            self._close_company()
        try:
            self.workspace.restore(source, path)
        except (backup.BackupError, OSError, sqlite3.Error) as e:
            QMessageBox.warning(self, tr("Восстановить из копии"), str(e))
            return False
        self.open_company(path)
        self.notify(tr("Компания восстановлена из копии {file}", file=source.name))
        return True

    def show_company_file(self) -> None:
        if self.company_path is None:
            return
        if sys.platform == "win32":
            subprocess.Popen(["explorer", "/select,", str(self.company_path)])
        else:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.company_path.parent)))

    def delete_company(self) -> None:
        if self.session is None or not confirm_delete(self, self.session.company_name):
            return
        if not self._confirm_close_all():
            return
        name, path = self.session.company_name, self.company_path
        if path is None:
            return
        self._close_company()
        self.workspace.delete(path)
        remaining = self.workspace.companies()
        if remaining:
            self.open_company(remaining[0].path)
        elif not self.create_company(first=True):
            self._show_no_company()
        self.notify(
            tr("Компания «{name}» удалена (файл в папке «{trash}»)", name=name, trash=TRASH)
        )

    def _show_no_company(self) -> None:
        self.sidebar.company.setText(tr("Нет компании") + "   ▾")
        self.setWindowTitle("Modern GL")
        page = EmptyState("○", tr("Нет компании"), tr("Создайте компанию в меню слева вверху."))
        self.pages[("empty",)] = page
        self.stack.addWidget(page)
        self.stack.setCurrentWidget(page)

    # ---- pages -----------------------------------------------------------------------

    def _make_place(self, key) -> QWidget:
        s = self.open_session
        if key == ("journal",):
            page = JournalPage(s)
            page.open_document.connect(self.open_document)
            page.new_document.connect(self.new_document)
            page.deleted.connect(lambda doc_id: self.close_page(("doc", doc_id), ask=False))
            page.copy_document.connect(
                lambda doc_id: self.new_document(load_document(s.conn, s.company_id, doc_id))
            )
            page.prefill_document.connect(self.new_document)
            page.import_requested.connect(self.show_import)
            return page
        if key == ("directories",):
            return DirectoriesPage(s)
        if key == ("currencies",):
            page = CurrenciesPage(s)
            page.open_document.connect(self.open_document)
            return page
        if key == ("inventory",):
            page = InventoryPage(s)
            page.open_inventory_document.connect(self.open_inventory_document)
            page.new_inventory_document.connect(self.new_inventory_document)
            return page
        if key == ("templates",):
            page = TemplatesPage(s)
            page.use_template.connect(
                lambda tid: self.new_document(entry=load_template(s.conn, s.company_id, tid))
            )
            page.edit_template.connect(self.open_template)
            return page
        page = OsvPage(s) if key == ("osv",) else ChartPage(s)
        self._wire_report(page)
        return page

    def show_import(self) -> None:
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
        if self.session is None:
            return
        self.show_place(("journal",))
        journal = self._page(("journal",), JournalPage)
        if journal is not None:
            journal.focus_quick_entry()

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
            title = page.title() if isinstance(page, TitledPage) else ""
            self.sidebar.add_item(key, title, open_icon(key))

    def _activate(self, key) -> None:
        page = self.pages[key]
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
        if key in self.pages:
            self._activate(key)
        else:
            self.show_place(key)

    def _nav_menu(self, pos) -> None:
        item = self.sidebar.nav.itemAt(pos)
        key = item.data(KEY_ROLE) if item else None
        if not NavDelegate.closable(key):
            return
        menu = QMenu(self)
        menu.addAction(tr("Закрыть")).triggered.connect(lambda: self.close_page(key))
        menu.exec(self.sidebar.nav.viewport().mapToGlobal(pos))

    def open_document(self, doc_id: int) -> None:
        """From the journal or a report: the primary document, as in 1C. Postings made by
        a warehouse document open that document, where they are corrected."""
        s = self.open_session
        source = inventory_document_of(s.conn, s.company_id, doc_id)
        if source is not None:
            self.open_inventory_document(source)
            return
        self.show_document(doc_id)

    def show_document(self, doc_id: int) -> None:
        """The GL document itself, even when a warehouse document made it."""
        key = ("doc", doc_id)
        if key not in self.pages:
            page = DocumentPage(self.open_session, doc_id=doc_id)
            self._wire_document(page)
            self._add_page(key, page, open_item=True)
        self._activate(key)

    def new_document(self, template=None, entry=None) -> None:
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
        page: InventoryDocumentPage | LandedCostPage = (
            LandedCostPage(self.open_session)
            if doc_type == "landed_cost"
            else InventoryDocumentPage(self.open_session, doc_type=doc_type)
        )
        self._wire_inventory_document(page)
        self._add_page(page.key, page, open_item=True)
        self._activate(page.key)

    def _wire_inventory_document(self, page: InventoryDocumentPage | LandedCostPage) -> None:
        page.saved.connect(lambda _id, p=page: self._inventory_document_saved(p))
        page.open_gl_document.connect(self.show_document)
        page.close_requested.connect(lambda p=page: self.close_page(self._key_of(p), ask=False))
        page.title_changed.connect(lambda p=page: self._retitle(p))

    def _inventory_document_saved(self, page: InventoryDocumentPage | LandedCostPage) -> None:
        old_key = self._key_of(page)
        if old_key is not None and old_key != page.key and page.doc is not None:
            self.pages[page.key] = self.pages.pop(old_key)
            item = self.sidebar.item_for(old_key)
            if item is not None:
                item.setData(KEY_ROLE, page.key)
                item.setIcon(open_icon(page.key))
        self._retitle(page)
        inventory = self._page(("inventory",), InventoryPage)
        if inventory is not None:
            inventory.refresh()

    def open_template(self, template_id: int | None) -> None:
        """The template editor; a saved (or deleted) template returns to the list."""
        key = ("template", template_id)
        if template_id is not None and key in self.pages:
            self._activate(key)
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
        old_key = self._key_of(page)
        if old_key is not None and old_key != page.key and page.doc is not None:
            # A new document got its number: re-key it in place.
            self.pages[page.key] = self.pages.pop(old_key)
            item = self.sidebar.item_for(old_key)
            if item is not None:
                item.setData(KEY_ROLE, page.key)
                item.setIcon(open_icon(page.key))
        self._retitle(page)
        journal = self._page(("journal",), JournalPage)
        if journal is not None:
            journal.refresh(select_id=page.doc_id)

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

    def open_report(self, kind: str, account_id: int, params: ReportParams) -> None:
        key = (kind, account_id)
        if key in self.pages:
            self.close_page(key, ask=False)
        page = REPORTS[kind](self.open_session, account_id, params)
        self._wire_report(page)
        self._add_page(key, page, open_item=True)
        self._activate(key)

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
        self.stack.removeWidget(page)
        page.deleteLater()
        self.show_place(("journal",))

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

    def set_ui_language(self, code: str) -> None:
        if code == language() or not self._confirm_close_all():
            return
        set_language(code)
        if self.settings:
            self.settings.setValue("language", code)
        if self.company_path is not None:
            self.open_company(self.company_path)

    def set_ui_theme(self, name: str) -> None:
        """Another look at once: the pages are built again in its colors."""
        if name == theme.current_theme() or not self._confirm_close_all():
            return
        theme.set_theme(name)
        if self.settings:
            self.settings.setValue("theme", name)
        app = QApplication.instance()
        if isinstance(app, QApplication):
            theme.apply(app)
        if self.company_path is not None:
            self.open_company(self.company_path)

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
