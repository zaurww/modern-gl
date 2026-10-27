"""The accounts a conversion posts to: the bank fee, exchange gains and losses, transit."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QMessageBox,
    QVBoxLayout,
)

from modern_gl.desktop.session import Session
from modern_gl.desktop.widgets import caption
from modern_gl.domain.accounts import BANK_FEE, FX_GAIN, FX_LOSS, FX_TRANSIT
from modern_gl.domain.errors import LedgerError
from modern_gl.i18n import N_, tr


class ConversionAccountsDialog(QDialog):
    """The accounts conversions post to (account roles, D34)."""

    ROLES = (
        (FX_TRANSIT, N_("Переводы в пути")),
        (FX_GAIN, N_("Доход от курсовой разницы")),
        (FX_LOSS, N_("Убыток от курсовой разницы")),
        (BANK_FEE, "Комиссия банка"),
    )

    def __init__(self, session: Session, parent=None, missing: str | None = None) -> None:
        super().__init__(parent)
        self.s = session
        self.setWindowTitle(tr("Счета конвертации"))
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 16)
        lay.setSpacing(14)
        hint = caption(
            tr("Сюда конвертация относит деньги в пути, курсовую разницу и комиссию банка.")
        )
        hint.setWordWrap(True)
        lay.addWidget(hint)
        form = QFormLayout()
        form.setSpacing(10)
        self.boxes: dict[str, QComboBox] = {}
        for role, title in self.ROLES:
            box = QComboBox()
            box.addItem(tr("— не указан —"), None)
            for account in session.catalog.leaf_accounts:
                box.addItem(account.label, account.id)
            current = session.ledger.account_role(session.company_id, role)
            box.setCurrentIndex(max(box.findData(current), 0))
            form.addRow(tr(title), box)
            self.boxes[role] = box
        lay.addLayout(form)
        if missing in self.boxes:  # opened because this account is not chosen yet
            self.boxes[missing].setFocus()
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

    def accept(self) -> None:
        try:
            for role, box in self.boxes.items():
                self.s.ledger.set_account_role(self.s.company_id, role, box.currentData())
        except LedgerError as e:
            QMessageBox.warning(self, tr("Счета конвертации"), str(e))
            return
        super().accept()
