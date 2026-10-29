"""«Комиссии банка → счёт» in the window loading a statement file: the file has fees, so
the account they go to is asked right there, where it matters — a newcomer does not have to
know «Настройки банка». The choice is the same setting (role bank_fee, D62) and is kept."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QWidget

from modern_gl.application.bank import FEE
from modern_gl.application.bank.imported import KNOWN, ImportRow
from modern_gl.desktop.session import Session
from modern_gl.desktop.widgets import caption
from modern_gl.domain.accounts import BANK_FEE
from modern_gl.domain.errors import LedgerError
from modern_gl.i18n import tr


class FeeAccountChoice(QWidget):
    """Shown when the lines to load have a bank fee; a choice saves the setting and
    calls `changed` (the lines are planned again)."""

    def __init__(self, session: Session, changed: Callable[[], None]) -> None:
        super().__init__()
        self.s = session
        self.changed = changed
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(QLabel(tr("Комиссии банка — на счёт")))
        self.box = QComboBox()
        self.box.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self.box.setMinimumContentsLength(28)
        self.box.addItem(tr("— выберите счёт —"), None)
        for account in session.catalog.leaf_accounts:
            self.box.addItem(account.label, account.id)
        self._select()
        self.box.currentIndexChanged.connect(self._chosen)
        row.addWidget(self.box)
        self.note = caption(tr("запомнится для следующих выписок"))
        row.addWidget(self.note)
        row.addStretch(1)
        self.setVisible(False)

    def show_for(self, rows: list[ImportRow]) -> None:
        has_fee = any(r.op.kind == FEE and r.state != KNOWN for r in rows)
        self.setVisible(has_fee and not self.s.read_only)

    def _select(self) -> None:
        current = self.s.ledger.account_role(self.s.company_id, BANK_FEE)
        self.box.blockSignals(True)
        self.box.setCurrentIndex(max(self.box.findData(current), 0))
        self.box.blockSignals(False)

    def _chosen(self) -> None:
        account = self.box.currentData()
        if account is None:
            return
        try:
            self.s.ledger.set_account_role(self.s.company_id, BANK_FEE, account)
        except LedgerError as e:
            self.note.setText(str(e))
            self._select()
            return
        self.note.setText(tr("запомнится для следующих выписок"))
        self.changed()
