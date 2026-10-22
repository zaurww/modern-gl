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
from modern_gl.domain.accounts import ADVANCE_PAID, ADVANCE_RECEIVED, BANK_FEE
from modern_gl.domain.errors import LedgerError
from modern_gl.i18n import tr


class BankSettingsDialog(QDialog):
    """The account «+ Комиссия банка» puts on a new line (role bank_fee, shared with
    conversions; D62), and where an advance goes (D78): the advance accounts, or none —
    an advance stays on the settlement account without an e-qaimə."""

    ROLES = (
        (BANK_FEE, "Счёт комиссии банка", "— не указан —"),
        (ADVANCE_PAID, "Авансы выданные", "— на счёте поставщика —"),
        (ADVANCE_RECEIVED, "Авансы полученные", "— на счёте покупателя —"),
    )

    def __init__(self, session: Session, parent=None) -> None:
        super().__init__(parent)
        self.s = session
        self.setWindowTitle(tr("Настройки банка"))
        self.setMinimumWidth(540)
        form = QFormLayout(self)
        self.boxes: dict[str, QComboBox] = {}
        for role, caption, nothing in self.ROLES:
            box = QComboBox()
            # long account names do not squeeze the label
            box.setSizeAdjustPolicy(
                QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
            )
            box.setMinimumContentsLength(28)
            box.addItem(tr(nothing), None)
            for account in session.catalog.leaf_accounts:
                box.addItem(account.label, account.id)
            current = session.ledger.account_role(session.company_id, role)
            box.setCurrentIndex(max(box.findData(current), 0))
            form.addRow(tr(caption), box)
            self.boxes[role] = box
        self.fee = self.boxes[BANK_FEE]
        hint = QLabel(
            tr(
                "Комиссия — для «+ Комиссия банка» (F6) и конвертации. Оплата больше долга "
                "контрагента — аванс: на счёт авансов, а без него — на счёт расчётов без "
                "e-qaimə. В строке счёт можно сменить."
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
        led, cid = self.s.ledger, self.s.company_id
        try:
            for role, box in self.boxes.items():
                if box.currentData() != led.account_role(cid, role):
                    led.set_account_role(cid, role, box.currentData())
        except LedgerError as exc:
            QMessageBox.warning(self, tr("Настройки банка"), str(exc))
            return
        self.accept()
