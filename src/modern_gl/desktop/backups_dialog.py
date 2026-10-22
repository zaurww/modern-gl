"""«Резервные копии» (D97): when and where the company was last copied, a copy now, and a
second folder every copy also goes to — a flash drive or a synced cloud folder, so a lost
disk does not take the copies with it. The second folder is this computer's setting."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QDialog, QFileDialog, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from modern_gl.desktop.theme import fonts
from modern_gl.desktop.widgets import button
from modern_gl.i18n import tr
from modern_gl.infrastructure import backup
from modern_gl.infrastructure.db import Connection, Error
from modern_gl.infrastructure.workspace import Workspace

MIRROR_SETTING = "backup_mirror"


class BackupsDialog(QDialog):
    def __init__(
        self,
        workspace: Workspace,
        conn: Connection,
        company_file: Path,
        settings: QSettings | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.workspace, self.conn, self.company_file = workspace, conn, company_file
        self.settings = settings
        self.setWindowTitle(tr("Резервные копии"))
        self.setMinimumWidth(520)
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 20)
        root.setSpacing(8)
        self.last = QLabel()
        self.last.setFont(fonts().heading)
        root.addWidget(self.last)
        self.where = self._note(root)
        root.addLayout(self._row(tr("Показать папку"), self.show_folder))
        root.addSpacing(14)
        second = QLabel(tr("Вторая папка — флешка или облако"))
        second.setFont(fonts().bold)
        root.addWidget(second)
        self.mirror = self._note(root)
        root.addLayout(self._mirror_row())
        self.message = QLabel()
        self.message.setObjectName("warning")
        self.message.setWordWrap(True)
        self.message.hide()
        root.addWidget(self.message)
        root.addStretch(1)
        root.addLayout(self._buttons())
        self.update_texts()

    def _note(self, root: QVBoxLayout) -> QLabel:
        label = QLabel()
        label.setObjectName("secondary")
        label.setWordWrap(True)
        root.addWidget(label)
        return label

    def _row(self, text: str, slot) -> QHBoxLayout:
        row = QHBoxLayout()
        b = button(text, "flat")
        b.clicked.connect(lambda _=False: slot())
        row.addWidget(b)
        row.addStretch(1)
        return row

    def _mirror_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        choose = button(tr("Выбрать папку…"), "flat")
        choose.clicked.connect(lambda _=False: self.choose_mirror())
        self.off = button(tr("Не копировать"), "flat")
        self.off.clicked.connect(lambda _=False: self.set_mirror(None))
        row.addWidget(choose)
        row.addWidget(self.off)
        row.addStretch(1)
        return row

    def _buttons(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.addStretch(1)
        close, now = button(tr("Закрыть")), button(tr("Сделать копию сейчас"), "primary")
        close.clicked.connect(self.accept)
        now.clicked.connect(lambda _=False: self.backup_now())
        row.addWidget(close)
        row.addWidget(now)
        return row

    def update_texts(self) -> None:
        made = self.workspace.backups(self.company_file)
        if made:
            self.last.setText(
                tr("Последняя копия: {when}", when=made[0].made_at.strftime("%d.%m.%Y %H:%M"))
            )
        else:
            self.last.setText(tr("Копий ещё нет"))
        self.where.setText(
            tr(
                "Копия делается при закрытии компании, если что-то изменилось; хранятся "
                "последние {n}. Папка: {folder}",
                n=backup.KEEP,
                folder=self.workspace.backup_folder(self.company_file),
            )
        )
        mirror = self.workspace.mirror
        self.mirror.setText(
            tr("Каждая копия ещё и в: {folder}", folder=mirror)
            if mirror
            else tr("Не выбрана: копии лежат только на этом диске.")
        )
        self.off.setVisible(mirror is not None)

    def show_folder(self) -> None:
        folder = self.workspace.backup_folder(self.company_file)
        folder.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def choose_mirror(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, tr("Вторая папка для копий"))
        if folder:
            self.set_mirror(Path(folder))

    def set_mirror(self, folder: Path | None) -> None:
        self.workspace.mirror = folder
        if self.settings is not None:
            self.settings.setValue(MIRROR_SETTING, str(folder) if folder else "")
        self.update_texts()

    def backup_now(self) -> None:
        try:
            made = self.workspace.backup_now(self.conn, self.company_file)
        except (backup.BackupError, OSError, Error) as e:
            self._say(tr("Копия не сохранена полностью: {error}", error=e))
            self.update_texts()
            return
        self._say(tr("Копия сохранена: {file}", file=made.name), warn=False)
        self.update_texts()

    def _say(self, text: str, warn: bool = True) -> None:
        self.message.setObjectName("warning" if warn else "secondary")
        self.message.setStyleSheet("")  # the object name changed: the style is read again
        self.message.setText(text)
        self.message.show()
