"""«История изменений» (D96): a document's story from the audit trail — when, who, what,
and why, one quiet line each."""

from __future__ import annotations

from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from modern_gl.application.authorship import local_time
from modern_gl.application.history import HistoryEvent
from modern_gl.desktop.theme import fonts
from modern_gl.desktop.widgets import button
from modern_gl.i18n import tr


def event_line(e: HistoryEvent) -> str:
    line = f"{local_time(e.at)}   {tr(e.action)} · {e.actor}"
    return line + (f"\n{tr('Причина: {reason}', reason=e.reason)}" if e.reason else "")


class HistoryDialog(QDialog):
    def __init__(self, title: str, events: list[HistoryEvent], parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle(tr("История изменений"))
        self.setMinimumWidth(480)
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 20)
        root.setSpacing(10)
        head = QLabel(title)
        head.setFont(fonts().heading)
        root.addWidget(head)
        self.lines: list[QLabel] = []
        for e in events or []:
            label = QLabel(event_line(e))
            label.setWordWrap(True)
            self.lines.append(label)
            root.addWidget(label)
        if not events:
            empty = QLabel(tr("В журнале действий о документе ничего нет."))
            empty.setObjectName("secondary")
            root.addWidget(empty)
        root.addStretch(1)
        row = QHBoxLayout()
        row.addStretch(1)
        close = button(tr("Закрыть"), "primary")
        close.clicked.connect(self.accept)
        row.addWidget(close)
        root.addLayout(row)
