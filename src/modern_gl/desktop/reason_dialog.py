"""«Почему?» (D96): before what takes back posted books — unposting, deleting a posted
document, opening a closed period — the question and a field for the reason. The reason
is optional and goes to the audit trail with the change."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from modern_gl.desktop.theme import fonts
from modern_gl.desktop.widgets import button
from modern_gl.i18n import tr


class ReasonDialog(QDialog):
    def __init__(self, title: str, question: str, ok: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(460)
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 20)
        root.setSpacing(12)
        head = QLabel(question)
        head.setFont(fonts().heading)
        head.setWordWrap(True)
        root.addWidget(head)
        self.reason = QLineEdit()
        self.reason.setPlaceholderText(tr("Причина — для журнала действий (необязательно)"))
        root.addWidget(self.reason)
        row = QHBoxLayout()
        row.addStretch(1)
        cancel, self.ok = button(tr("Отмена")), button(ok, "primary")
        cancel.clicked.connect(self.reject)
        self.ok.clicked.connect(self.accept)
        row.addWidget(cancel)
        row.addWidget(self.ok)
        root.addLayout(row)
        self.reason.setFocus()


def ask_reason(parent: QWidget | None, title: str, question: str, ok: str) -> str | None:
    """The reason told (maybe ''), or None when the user changed their mind."""
    dialog = ReasonDialog(title, question, ok, parent)
    if not dialog.exec():
        return None
    return dialog.reason.text().strip()


def confirm_delete(parent: QWidget | None, number: int, posted: bool) -> str | None:
    """Delete document №number? A draft — yes or no; a posted one — with the reason.
    The reason ('' when none), or None: not deleted."""
    if not posted:
        answer = QMessageBox.question(parent, tr("Удалить"), tr("Удалить черновик №{n}?", n=number))
        return "" if answer == QMessageBox.StandardButton.Yes else None
    return ask_reason(
        parent,
        tr("Удалить"),
        tr(
            "Удалить проведённый документ №{n}? Его проводки исчезнут из отчётов, "
            "а полная копия останется в журнале действий.",
            n=number,
        ),
        tr("Удалить"),
    )
