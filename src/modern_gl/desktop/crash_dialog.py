"""What happens when the program itself fails (D158): an exception nobody caught — in a
slot, in a worker thread — goes to the log (`infrastructure.logs`) and to one window,
«Ошибка», with the traceback the user can copy and send. The window stays open, the
books are untouched: every write is one transaction, which the failure rolled back.

`install()` hooks `sys.excepthook` and Qt's own messages (qWarning …) once at start;
without a QApplication (a tool in a console) the traceback goes to stderr as before."""

from __future__ import annotations

import logging
import sys
import traceback
from types import TracebackType

from PySide6.QtCore import QtMsgType, qInstallMessageHandler
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from modern_gl.desktop.theme import fonts
from modern_gl.desktop.widgets import button
from modern_gl.i18n import tr

logger = logging.getLogger("modern_gl")
_QT_LEVELS = {
    QtMsgType.QtDebugMsg: logging.DEBUG,
    QtMsgType.QtInfoMsg: logging.INFO,
    QtMsgType.QtWarningMsg: logging.WARNING,
    QtMsgType.QtCriticalMsg: logging.ERROR,
    QtMsgType.QtFatalMsg: logging.CRITICAL,
}


class CrashDialog(QDialog):
    """«Ошибка»: what happened, the traceback, «Копировать» and «Закрыть»."""

    def __init__(self, details: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("Ошибка"))
        self.setMinimumSize(560, 400)
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 20)
        root.setSpacing(12)
        head = QLabel(tr("В программе произошла ошибка"))
        head.setFont(fonts().heading)
        root.addWidget(head)
        note = QLabel(
            tr(
                "Данные не пострадали: незавершённая запись отменена. Скопируйте текст "
                "ниже и отправьте разработчику — он записан и в журнал программы."
            )
        )
        note.setWordWrap(True)
        root.addWidget(note)
        self.details = QPlainTextEdit(details)
        self.details.setReadOnly(True)
        self.details.setFont(fonts().table)
        root.addWidget(self.details, 1)
        row = QHBoxLayout()
        row.addStretch(1)
        self.copy = button(tr("Копировать"))
        self.copy.clicked.connect(self._copy)
        close = button(tr("Закрыть"), "primary")
        close.clicked.connect(self.accept)
        row.addWidget(self.copy)
        row.addWidget(close)
        root.addLayout(row)
        close.setFocus()

    def _copy(self) -> None:
        QApplication.clipboard().setText(self.details.toPlainText())
        self.copy.setText(tr("Скопировано"))


def show_crash(details: str) -> None:
    """The window with the traceback; without a QApplication — stderr (a console tool)."""
    if QApplication.instance() is None:
        sys.stderr.write(details)
        return
    CrashDialog(details, QApplication.activeWindow()).exec()


def report_crash(
    kind: type[BaseException], error: BaseException, trace: TracebackType | None
) -> None:
    """`sys.excepthook`: the traceback to the log and to the user."""
    details = "".join(traceback.format_exception(kind, error, trace))
    logger.error("unhandled exception\n%s", details)
    show_crash(details)


def _qt_message(kind: QtMsgType, _context, message: str) -> None:
    logger.log(_QT_LEVELS.get(kind, logging.WARNING), "Qt: %s", message)


def install() -> None:
    """Once at start: unhandled exceptions and Qt's messages go to the log."""
    sys.excepthook = report_crash
    qInstallMessageHandler(_qt_message)
