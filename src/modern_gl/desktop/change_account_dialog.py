"""«Сменить счёт у отмеченных» of the journal (D225): the account the
marked documents are on now and the one their lines go to."""

from __future__ import annotations

from PySide6.QtWidgets import QDialog, QDialogButtonBox, QFormLayout, QLabel

from modern_gl.desktop.pick import PickBox
from modern_gl.desktop.session import Session
from modern_gl.desktop.theme import fonts
from modern_gl.i18n import tr


class AccountChangeDialog(QDialog):
    """`used` — the accounts of the marked documents, the most used first."""

    def __init__(self, session: Session, used: list[int], marked: int, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("Сменить счёт у отмеченных"))
        self.setMinimumWidth(560)
        accounts = session.catalog.accounts
        form = QFormLayout(self)
        self.old = PickBox(tr("Код или название"))
        for account_id in used:
            self.old.addItem(accounts[account_id].label, account_id)
        self.new = PickBox(tr("Код или название"))
        for account in session.catalog.leaf_accounts:
            self.new.addItem(account.label, account.id)
        form.addRow(tr("Счёт сейчас"), self.old)
        form.addRow(tr("Новый счёт"), self.new)
        hint = QLabel(
            tr(
                "Отмечено документов: {n}. Каждый сохранит номер и статус, проведённый будет "
                "проведён заново; прежний вид — в журнале действий. В покупке меняется счёт "
                "строк без товара; счёт товара и ƏDV остаются.",
                n=marked,
            )
        )
        hint.setObjectName("tertiary")
        hint.setFont(fonts().small)
        hint.setWordWrap(True)
        form.addRow(hint)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def chosen(self) -> tuple[int, int] | None:
        """(the account now, the new one); nothing to change — None."""
        old, new = self.old.currentData(), self.new.currentData()
        if old is None or new is None or old == new:
            return None
        return old, new
