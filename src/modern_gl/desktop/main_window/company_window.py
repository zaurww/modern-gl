"""The window's side of the open company: the file's commands go to `CompanySession`;
what opens the company again (the user's name, language, look) is the window's."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QInputDialog, QMainWindow

from modern_gl.application.ledger import Ledger
from modern_gl.application.workspace import Workspace
from modern_gl.desktop import theme
from modern_gl.desktop.main_window.company_files import CompanySession
from modern_gl.desktop.page import PageWidget
from modern_gl.desktop.preferences import Preferences
from modern_gl.desktop.session import Session
from modern_gl.i18n import language, set_language, tr
from modern_gl.infrastructure.db import Connection


class CompanyFiles(QMainWindow):
    def __init__(self, workspace: Workspace, settings: QSettings | None = None) -> None:
        super().__init__()
        self.company = CompanySession(
            workspace, settings, self, self._confirm_close_all, self.notify
        )
        self.company.opened.connect(self._show_company)
        self.company.closing.connect(self._drop_pages)
        self.company.none_left.connect(self._show_no_company)

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

    def ask_view_company(self) -> None:
        self.company.ask_view_company()

    def view_company(self, path: Path) -> None:
        self.company.view_company(path)

    def reread(self) -> None:
        self.company.reread()

    def shutdown(self) -> None:
        self.company.shutdown()

    def add_company_file(self) -> None:
        self.company.add_company_file()

    def save_as(self) -> None:
        self.company.save_as()

    def save_as_to(self, target: Path, name: str) -> bool:
        return self.company.save_as_to(target, name)

    def save_copy(self) -> None:
        self.company.save_copy()

    def hand_over(self) -> None:
        self.company.hand_over()

    def restore_company(self) -> None:
        self.company.restore_company()

    def restore_from(self, source: Path, path: Path) -> bool:
        return self.company.restore_from(source, path)

    def show_company_file(self) -> None:
        self.company.show_company_file()

    def delete_company(self) -> None:
        self.company.delete_company()

    def user_name(self) -> str:
        return self.company.user_name()

    def set_document_language(self, code: str) -> None:
        self.company.set_document_language(code)

    def set_parallel_books(self, on: bool) -> None:
        self.company.set_parallel_books(on)

    def edit_tax_id(self) -> None:
        self.company.edit_tax_id()

    def set_stock_only(self, on: bool) -> None:
        self.company.set_stock_only(on)

    def _close_company(self) -> None:
        self.company.close()

    def _viewing(self) -> bool:
        return self.company.viewing()

    # ---- what opens the company again: the window's ------------------------------------

    def _reopen(self) -> None:
        """The same company again (another language, look or books), on the same place."""
        place = self._current_place()
        if self.company.reopen() and place is not None:
            self.show_place(place)

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
        if not self._confirm_close_all():
            return
        if self.prefs:
            self.prefs.set_user_name(name)
        self._reopen()
        self.notify(tr("Ваше имя: {name}", name=name))

    def set_ui_language(self, code: str) -> None:
        if code == language() or not self._confirm_close_all():
            return
        set_language(code)
        if self.prefs:
            self.prefs.set_language(code)
        self._reopen()

    def set_ui_theme(self, name: str) -> None:
        """Another look at once: the pages are built again in its colors."""
        if name == theme.current_theme() or not self._confirm_close_all():
            return
        theme.use_theme(name)
        if self.prefs:
            self.prefs.set_theme(name)
        self._repaint()

    def set_table_look(self, change: Callable[[bool], None], on: bool) -> None:
        """«Полосы в таблицах», «Сетка в отчётах» (D103, D127): the pages built again."""
        change(on)
        self._repaint(reopen=not self._dirty_pages())

    def follow_system_theme(self, _scheme: object = None) -> None:
        """The system turned light or dark: «as the system» follows it. Pages with
        unsaved changes are not built again — the new colors reach them on reopening."""
        if theme.current_theme() != theme.SYSTEM_THEME:
            return
        shown = theme.shown_theme()
        theme.use_theme(theme.SYSTEM_THEME)
        if theme.shown_theme() != shown:
            self._repaint(reopen=not self._dirty_pages())

    def _repaint(self, reopen: bool = True) -> None:
        app = QApplication.instance()
        if isinstance(app, QApplication):
            theme.apply(app)
        if reopen:
            self._reopen()

    def _dirty_pages(self) -> list[PageWidget]:
        raise NotImplementedError

    def _current_place(self) -> tuple | None:
        raise NotImplementedError

    def show_place(self, key) -> None:
        raise NotImplementedError

    def _show_company(self, name: str) -> None:
        raise NotImplementedError

    def _drop_pages(self) -> None:
        raise NotImplementedError

    def _show_no_company(self) -> None:
        raise NotImplementedError

    def _confirm_close_all(self) -> bool:
        raise NotImplementedError

    def notify(self, message: str, undo: Callable[[], None] | None = None) -> None:
        raise NotImplementedError
