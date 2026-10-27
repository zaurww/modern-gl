"""The open company and its file (one file each): created, opened, saved as, copied,
restored from a backup, deleted; what is kept in it (VÖEN, books, the documents' language)."""

from __future__ import annotations

import getpass
import shutil
import sys
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Protocol

from PySide6.QtCore import QObject, QProcess, QSettings, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from modern_gl.application.catalog import Catalog
from modern_gl.application.ledger import Ledger
from modern_gl.application.queries import company_name, company_tax_id, posting_count
from modern_gl.application.workspace import SUFFIX, TRASH, Workspace
from modern_gl.desktop.background import LARGE
from modern_gl.desktop.portal_company import ask_tax_id
from modern_gl.desktop.preferences import Preferences
from modern_gl.desktop.session import Session
from modern_gl.domain.company import FULL, STOCK_ONLY
from modern_gl.domain.errors import LedgerError
from modern_gl.i18n import LANGUAGES, set_document_language, tr
from modern_gl.infrastructure import backup
from modern_gl.infrastructure.db import Connection, DatabaseError, Error, close
from modern_gl.reporting.handover import handover_files, write_handover


class Notify(Protocol):
    """A message on the window, with «Undo» when `undo` is given."""

    def __call__(self, message: str, undo: Callable[[], None] | None = None) -> None: ...


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


class CompanySession(QObject):
    """The open company and its file: opened, created, viewed, saved as, copied, restored,
    deleted; the window hears `opened` (show it), `closing` (drop its pages) and
    `none_left` (the last one deleted). What it asks of the pages comes in: `confirm_close`
    — may they close (unsaved ones ask), `notify` — a message on the window."""

    opened = Signal(str)  # the company's name
    closing = Signal()  # the file is closed right after: its pages go first
    none_left = Signal()  # no company to open, none created

    def __init__(
        self,
        workspace: Workspace,
        settings: QSettings | None,
        owner: QWidget,
        confirm_close: Callable[[], bool],
        notify: Notify,
    ) -> None:
        super().__init__(owner)
        self.owner = owner  # the window: dialogs are shown over it
        self.confirm_close = confirm_close
        self.notify = notify
        self.workspace = workspace
        self.settings = settings  # None: nothing is remembered (tests)
        self.prefs = Preferences(settings) if settings is not None else None
        self.conn: Connection | None = None
        self.ledger: Ledger | None = None
        self.company_path: Path | None = None
        self.session: Session | None = None

    @property
    def open_session(self) -> Session:
        """The open company. Pages exist only while one is open."""
        if self.session is None:
            raise RuntimeError("no company is open")
        return self.session

    def start(self) -> bool:
        """Open the last used company, or ask to create the first one."""
        companies = self.workspace.companies()
        if not companies:
            return self.create_company(first=True)
        last = self.prefs.company_file() if self.prefs else ""
        paths = [c.path for c in companies]
        self.open_company(next((p for p in paths if str(p) == last), paths[0]))
        return True

    def create_company(self, first: bool = False) -> bool:
        prompt = (
            tr("Добро пожаловать! Как называется первая компания?")
            if first
            else tr("Название новой компании:")
        )
        name, ok = QInputDialog.getText(self.owner, tr("Новая компания"), prompt)
        if not ok or not name.strip():
            return False
        kinds = [tr("Полный учёт"), tr("Только склад (без бухгалтерии)")]
        kind, ok = QInputDialog.getItem(
            self.owner, tr("Новая компания"), tr("Что будете вести?"), kinds, 0, False
        )
        if not ok:
            return False
        mode = STOCK_ONLY if kind == kinds[1] else FULL
        tax_id = ask_tax_id(self.owner)  # checked against the portal (D113)
        if tax_id is None:
            return False
        target = self._ask_file(tr("Где сохранить файл компании"), name.strip())
        if target is None:
            return False
        if self.company_path is not None and target.resolve() == self.company_path.resolve():
            QMessageBox.warning(
                self.owner, tr("Новая компания"), tr("Выберите другой файл: этот уже открыт")
            )
            return False
        if not self.confirm_close():
            return False
        try:
            path = self.workspace.create(name.strip(), path=target, mode=mode, tax_id=tax_id)
        except (LedgerError, OSError, Error) as e:
            QMessageBox.warning(self.owner, tr("Новая компания"), str(e))
            return False
        self._store_files()
        self.open_company(path)
        return True

    def _ask_file(self, title: str, name: str, folder: Path | None = None) -> Path | None:
        """The standard «Save as» window, offering «<name>.gl» (in the data folder unless
        another is given); None if cancelled."""
        suggested = self.workspace.new_path(name, folder)
        target, _ = QFileDialog.getSaveFileName(
            self.owner, title, str(suggested), tr("Файлы компаний (*.gl)")
        )
        if not target:
            return None
        path = Path(target)
        return path if path.suffix.lower() == SUFFIX else path.with_name(path.name + SUFFIX)

    def open_company(self, path: Path) -> None:
        if not self.confirm_close():
            return
        try:
            conn, company_id = self.workspace.open(path)
        except backup.BackupError as e:
            self._offer_restore(Path(path), str(e))
            return
        except LedgerError as e:  # a newer program's file, a failed update: as it was
            QMessageBox.warning(self.owner, tr("Открыть компанию"), str(e))
            return
        self._use_company(conn, company_id, Path(path), read_only=False)
        if self.prefs:
            self.prefs.set_company_file(str(path))

    def ask_view_company(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self.owner,
            tr("Открыть для просмотра"),
            str(self.workspace.folder),
            tr("Файлы компаний (*.gl *.db);;Все файлы (*)"),
        )
        if path:
            self.view_company(Path(path))

    def view_company(self, path: Path) -> None:
        """A company file for viewing only (D80): a snapshot of it; the file is not changed,
        not listed and not backed up, so it may be a colleague's file in use."""
        if not self.confirm_close():
            return
        try:
            conn, company_id = self.workspace.view(path)
        except (LedgerError, OSError, Error) as e:
            QMessageBox.warning(self.owner, tr("Открыть для просмотра"), str(e))
            return
        self._use_company(conn, company_id, Path(path), read_only=True)

    def reread(self) -> None:
        """Viewing: a new snapshot of the file, with what was saved in it since."""
        if self.session is not None and self.company_path is not None:
            self.view_company(self.company_path)
            self.notify(tr("Файл перечитан"))

    def reopen(self) -> bool:
        """The same company again (another language, look or books); False — none open."""
        if self.session is None or self.company_path is None:
            return False
        if self.session.read_only:
            self.view_company(self.company_path)
        else:
            self.open_company(self.company_path)
        return True

    def _use_company(self, conn: Connection, company_id: int, path: Path, read_only: bool) -> None:
        old_date = self.session.working_date if self.session else None
        self.close()
        self.conn, self.company_path = conn, path
        self.ledger = Ledger(conn, actor=self.user_name())
        name = company_name(conn, company_id)
        self.session = Session(
            conn,
            self.ledger,
            company_id,
            name,
            Catalog(conn, company_id),
            notify=self.notify,
            notify_undo=self.notify,
        )
        self.session.read_only = read_only
        self.session.path = path
        self.session.large = posting_count(conn, company_id) >= LARGE
        self.session.last_backup = lambda: self._last_backup(path)
        if old_date:
            self.session.working_date = old_date
        self.opened.emit(name)

    def _last_backup(self, path: Path) -> datetime | None:
        made = self.workspace.backups(path)
        return made[0].made_at if made else None

    def close(self) -> None:
        """Drop all pages of the current company and close its file."""
        if self.session is not None:
            self.session.background.wait()  # a worker's read of this file ends first
            # its result may still wait in the event loop: not shown on a closed company
            self.session.closed = True
        self.closing.emit()  # the pages go before the file
        if self.conn is not None:
            try:
                viewed = self.session is not None and self.session.read_only
                if self.company_path is not None and not viewed:
                    self.workspace.auto_backup(self.conn, self.company_path)
            except (backup.BackupError, OSError, Error) as e:
                QMessageBox.warning(
                    self.owner, tr("Резервная копия"), tr("Копия не сохранена: {error}", error=e)
                )
            close(self.conn)
        self.conn = self.ledger = self.session = self.company_path = None

    def shutdown(self) -> None:
        self.close()

    def add_company_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self.owner,
            tr("Добавить компанию из файла"),
            "",
            tr("Файлы компаний (*.gl *.db);;Все файлы (*)"),
        )
        if not path:
            return
        try:
            added = self.workspace.add_file(Path(path))
        except DatabaseError:
            QMessageBox.warning(
                self.owner,
                tr("Добавить из файла"),
                tr("Это не файл компании: {file}", file=Path(path).name),
            )
            return
        self._store_files()
        if added:
            self.open_company(added[0])
            self.notify(tr("Добавлено компаний: {n}", n=len(added)))

    def save_as(self) -> None:
        """Go on with the company in another file (and under another name if wanted);
        the current file stays as it was."""
        if self.session is None or self.company_path is None:
            return
        name, ok = QInputDialog.getText(
            self.owner,
            tr("Сохранить как"),
            tr("Название компании:"),
            text=self.session.company_name,
        )
        if not ok or not name.strip():
            return
        target = self._ask_file(
            tr("Сохранить компанию как"), name.strip(), self.company_path.parent
        )
        if target is not None:
            self.save_as_to(target, name.strip())

    def save_as_to(self, target: Path, name: str) -> bool:
        if self.conn is None or self.company_path is None or not self.confirm_close():
            return False
        if target.suffix.lower() != SUFFIX:
            target = target.with_name(target.name + SUFFIX)
        try:
            self.workspace.save_as(self.conn, self.company_path, target, name)
        except (LedgerError, OSError, Error) as e:
            QMessageBox.warning(self.owner, tr("Сохранить как"), str(e))
            return False
        self._store_files()
        self.open_company(target)
        self.notify(tr("Компания сохранена в файл {file}", file=target))
        return True

    def _store_files(self) -> None:
        """Company files outside the folder are remembered between runs."""
        if self.prefs:
            self.prefs.set_company_files([str(f) for f in self.workspace.files])

    def save_copy(self) -> None:
        """A copy of the company to hand over or keep elsewhere (a flash drive…)."""
        if self.conn is None or self.company_path is None:
            return
        suggested = Path.home() / f"{self.company_path.stem} {datetime.now():%Y-%m-%d}.gl"
        target, _ = QFileDialog.getSaveFileName(
            self.owner, tr("Сохранить копию компании"), str(suggested), tr("Файлы компаний (*.gl)")
        )
        if not target:
            return
        try:
            backup.copy_to(self.conn, Path(target))
        except (backup.BackupError, OSError, Error) as e:
            QMessageBox.warning(self.owner, tr("Сохранить копию"), str(e))
            return
        self.notify(tr("Копия сохранена: {file}", file=target))

    def hand_over(self) -> None:
        """Everything as plain text in a zip, for the accountant who takes the company (D81)."""
        if self.conn is None or self.company_path is None or self.session is None:
            return
        today = datetime.now().date()
        name = f"{self.company_path.stem} — {tr('передача дел')} {today}.zip"
        target, _ = QFileDialog.getSaveFileName(
            self.owner, tr("Передача дел"), str(Path.home() / name), tr("Архив zip (*.zip)")
        )
        if not target:
            return
        try:
            write_handover(Path(target), handover_files(self.conn, self.session.company_id, today))
        except (OSError, Error) as e:
            QMessageBox.warning(self.owner, tr("Передача дел"), str(e))
            return
        self.notify(tr("Пакет передачи сохранён: {file}", file=target))

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
            self.owner, tr("Восстановить из копии"), prompt, [*labels, other], 0, False
        )
        if not ok:
            return
        if choice == other:
            chosen, _ = QFileDialog.getOpenFileName(
                self.owner, tr("Восстановить из копии"), "", tr("Файлы компаний (*.gl *.db)")
            )
            if not chosen:
                return
            source = Path(chosen)
        else:
            source = backups[labels.index(choice)].path
        self.restore_from(source, path)

    def restore_from(self, source: Path, path: Path) -> bool:
        if not self.confirm_close():
            return False
        if self.company_path == path:
            self.close()
        try:
            self.workspace.restore(source, path)
        except (backup.BackupError, OSError, Error) as e:
            QMessageBox.warning(self.owner, tr("Восстановить из копии"), str(e))
            return False
        self.open_company(path)
        self.notify(tr("Компания восстановлена из копии {file}", file=source.name))
        return True

    def show_company_file(self) -> None:
        if self.company_path is None:
            return
        explorer = shutil.which("explorer") if sys.platform == "win32" else None
        if explorer is not None:  # the file chosen in its folder; no shell, a full path
            QProcess.startDetached(explorer, ["/select,", str(self.company_path)])
        else:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.company_path.parent)))

    def delete_company(self) -> None:
        if self.session is None or not confirm_delete(self.owner, self.session.company_name):
            return
        if not self.confirm_close():
            return
        name, path = self.session.company_name, self.company_path
        if path is None:
            return
        self.close()
        self.workspace.delete(path)
        self._store_files()
        remaining = self.workspace.companies()
        if remaining:
            self.open_company(remaining[0].path)
        elif not self.create_company(first=True):
            self.none_left.emit()
        self.notify(
            tr("Компания «{name}» удалена (файл в папке «{trash}»)", name=name, trash=TRASH)
        )

    def user_name(self) -> str:
        """Who is working (D82): the name set in the program, else the Windows user."""
        name = self.prefs.user_name() if self.prefs else ""
        return name.strip() or getpass.getuser()

    def set_document_language(self, code: str) -> None:
        """The language the program writes its texts into this company's documents in
        (D152): the next documents; what is written stays."""
        if self.session is None:
            return
        self.session.ledger.set_document_language(self.session.company_id, code)
        set_document_language(code)
        self.notify(tr("Новые документы — на языке: {name}", name=LANGUAGES[code]))

    def set_parallel_books(self, on: bool) -> None:
        """Books on or off (D63): the pages are built again with or without the field."""
        if self.session is None or self.company_path is None or not self.confirm_close():
            return
        try:
            self.session.ledger.set_parallel_books(self.session.company_id, on)
        except LedgerError as e:
            QMessageBox.warning(self.owner, tr("Параллельные книги (МСФО, налог)"), str(e))
            return
        self.open_company(self.company_path)

    def edit_tax_id(self) -> None:
        """The company's VÖEN (D113): what the tax portal is checked against."""
        if self.session is None:
            return
        current = company_tax_id(self.session.conn, self.session.company_id) or ""
        typed = ask_tax_id(self.owner, current)
        if typed is None:
            return
        try:
            self.session.ledger.set_company_tax_id(self.session.company_id, typed or None)
        except LedgerError as e:
            QMessageBox.warning(self.owner, tr("VÖEN компании"), str(e))

    def set_stock_only(self, on: bool) -> None:
        """Only the warehouse, or the whole program (D90): the sidebar is built again."""
        if self.session is None or self.company_path is None or not self.confirm_close():
            return
        try:
            self.session.ledger.set_company_mode(
                self.session.company_id, STOCK_ONLY if on else FULL
            )
        except LedgerError as e:
            QMessageBox.warning(self.owner, tr("Только склад (без бухгалтерии)"), str(e))
            return
        self.open_company(self.company_path)

    def viewing(self) -> bool:
        """Viewing only (D80): nothing new is started; the status bar says why."""
        if self.session is None or not self.session.read_only:
            return False
        self.notify(tr("Компания открыта только для просмотра"))
        return True
