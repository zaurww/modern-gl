"""«Настройки банка»: the account «+ Комиссия банка» puts on a new line (D62)."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QMessageBox,
)

from modern_gl.desktop.session import Session
from modern_gl.desktop.theme import fonts
from modern_gl.domain.accounts import BANK_FEE
from modern_gl.domain.errors import LedgerError
from modern_gl.i18n import tr


class BankSettingsDialog(QDialog):
    """The account «+ Комиссия банка» puts on a new line (role bank_fee, shared with
    conversions); a line may still take another account."""

    def __init__(self, session: Session, parent=None) -> None:
        super().__init__(parent)
        self.s = session
        self.setWindowTitle(tr("Настройки банка"))
        self.setMinimumWidth(500)
        form = QFormLayout(self)
        self.fee = QComboBox()
        # long account names do not squeeze the label
        self.fee.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self.fee.setMinimumContentsLength(28)
        self.fee.addItem(tr("— не указан —"), None)
        for account in session.catalog.leaf_accounts:
            self.fee.addItem(account.label, account.id)
        current = session.ledger.account_role(session.company_id, BANK_FEE)
        self.fee.setCurrentIndex(max(self.fee.findData(current), 0))
        form.addRow(tr("Счёт комиссии банка"), self.fee)
        hint = QLabel(
            tr(
                "Счёт по умолчанию для «+ Комиссия банка» и для конвертации. "
                "В операции счёт строки можно сменить."
            )
        )
        hint.setObjectName("tertiary")
        hint.setFont(fonts().small)
        hint.setWordWrap(True)
        form.addRow(hint)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def _save(self) -> None:
        account_id = self.fee.currentData()
        try:
            if account_id != self.s.ledger.account_role(self.s.company_id, BANK_FEE):
                self.s.ledger.set_account_role(self.s.company_id, BANK_FEE, account_id)
        except LedgerError as exc:
            QMessageBox.warning(self, tr("Настройки банка"), str(exc))
            return
        self.accept()
