"""«Сменить счёт у отмеченных»: the lines of the marked operations on one account go to
another (fees loaded before the bank's settings said 26) — one scenario of the bank."""

from __future__ import annotations

from collections import Counter

from PySide6.QtWidgets import QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLabel

from modern_gl.application.bank import load_bank_operations
from modern_gl.desktop.session import Session
from modern_gl.desktop.theme import fonts
from modern_gl.domain.accounts import BANK_FEE
from modern_gl.i18n import tr


class ChangeAccountDialog(QDialog):
    """The account the marked lines are on now (the most used one first) and the new
    one — the bank fee's account of the settings, if any."""

    def __init__(self, session: Session, operation_ids: list[int], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("Сменить счёт у отмеченных"))
        self.setMinimumWidth(540)
        operations = load_bank_operations(session.conn, session.company_id, operation_ids)
        used = Counter(
            line.account_id
            for op in operations.values()
            for line in op.lines
            if line.account_id is not None
        )
        accounts = session.catalog.accounts
        form = QFormLayout(self)
        self.old = QComboBox()
        for account_id, _ in used.most_common():
            self.old.addItem(accounts[account_id].label, account_id)
        self.new = QComboBox()
        for account in session.catalog.leaf_accounts:
            self.new.addItem(account.label, account.id)
        fee = session.ledger.account_role(session.company_id, BANK_FEE)
        self.new.setCurrentIndex(max(self.new.findData(fee), 0))
        for box in (self.old, self.new):
            box.setSizeAdjustPolicy(
                QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
            )
            box.setMinimumContentsLength(28)
        form.addRow(tr("Счёт сейчас"), self.old)
        form.addRow(tr("Новый счёт"), self.new)
        hint = QLabel(
            tr(
                "Отмечено операций: {n}. Каждая сохранит номер и статус, проведённая будет "
                "проведена заново; прежний вид — в журнале действий.",
                n=len(operations),
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
