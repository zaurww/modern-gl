"""Items nothing refers to, deleted together: a trial paste should not cost seventy
deletions one by one (D209)."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from modern_gl.application.inventory import Inventory
from modern_gl.desktop.session import Session
from modern_gl.domain.errors import LedgerError
from modern_gl.i18n import tr


class UnusedItemsDialog(QDialog):
    def __init__(self, items: list[tuple[int, str]], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("Неиспользованные товары"))
        self.setMinimumSize(440, 420)
        root = QVBoxLayout(self)
        text = QLabel(tr("Этих товаров нет ни в документах, ни в черновиках. Отмеченные удалить?"))
        text.setWordWrap(True)
        root.addWidget(text)
        self.list = QListWidget()
        for value_id, name in items:
            row = QListWidgetItem(name)
            row.setData(Qt.ItemDataRole.UserRole, value_id)
            row.setFlags(row.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            row.setCheckState(Qt.CheckState.Checked)
            self.list.addItem(row)
        root.addWidget(self.list)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Yes | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Yes).setText(tr("Удалить"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def chosen(self) -> list[int]:
        rows = (self.list.item(n) for n in range(self.list.count()))
        return [
            row.data(Qt.ItemDataRole.UserRole)
            for row in rows
            if row.checkState() == Qt.CheckState.Checked
        ]


def delete_unused_items(session: Session, parent: QWidget) -> bool:
    """The window and the deletion; True if something was deleted."""
    inventory = Inventory(session.conn, actor=session.ledger.actor)
    items = inventory.unused_items(session.company_id)
    if not items:
        session.notify(tr("Неиспользованных товаров нет"))
        return False
    dialog = UnusedItemsDialog(items, parent)
    if dialog.exec() != QDialog.DialogCode.Accepted or not dialog.chosen():
        return False
    chosen = dialog.chosen()
    try:
        inventory.delete_values(session.company_id, chosen)
    except LedgerError as exc:
        session.notify(str(exc))
        return False
    session.catalog.reload()
    session.notify(tr("Удалено товаров: {n}", n=len(chosen)))
    return True
