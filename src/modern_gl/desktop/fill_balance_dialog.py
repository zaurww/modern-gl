"""«Заполнить остатком…» in a document: which account's balance (12, 60…) on the document's
day, and — if known — where it goes; the lines themselves are the document's to fill."""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtWidgets import QDialog, QDialogButtonBox, QFormLayout, QLabel

from modern_gl.application.balance_fill import BalanceLine, balance_lines
from modern_gl.desktop.pick import PickBox
from modern_gl.desktop.session import Session
from modern_gl.desktop.widgets import caption
from modern_gl.domain.money import format_minor
from modern_gl.i18n import tr


class FillBalanceDialog(QDialog):
    """`lines` — the balance chosen, `other_id` — the account it goes to (None: typed in
    the lines afterwards)."""

    def __init__(
        self,
        session: Session,
        on_date: str,
        layers: Sequence[str],
        document_id: int | None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.s, self.on_date, self.layers, self.document_id = session, on_date, layers, document_id
        self.lines: list[BalanceLine] = []
        self.other_id: int | None = None
        self.setWindowTitle(tr("Заполнить остатком"))
        self.setMinimumWidth(520)
        form = QFormLayout(self)
        form.setContentsMargins(24, 20, 24, 16)
        form.setSpacing(10)
        about = caption(
            tr(
                "Строка на каждый остаток счёта по субконто на дату документа — "
                "чтобы списать его или перенести на другой счёт."
            )
        )
        about.setWordWrap(True)
        form.addRow(about)
        self.account = PickBox(tr("код или название"))
        self.other = PickBox(tr("заполню в строках"))
        system = session.catalog.system_account_ids
        for a in session.catalog.accounts.values():
            if a.active and a.id not in system:
                self.account.addItem(a.label, a.id)
                if not a.is_group:
                    self.other.addItem(a.label, a.id)
        form.addRow(tr("Остаток счёта"), self.account)
        form.addRow(tr("Корр. счёт"), self.other)
        self.found = QLabel()
        self.found.setWordWrap(True)
        form.addRow(self.found)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.ok = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.ok.setText(tr("Заполнить"))
        self.ok.setEnabled(False)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)
        self.account.activated.connect(lambda _i: self._count())
        self.account.setFocus()

    def choose(self, account_id: int, other_id: int | None = None) -> None:
        """Pick the accounts as if typed (tests)."""
        self.account.setCurrentIndex(self.account.findData(account_id))
        if other_id is not None:
            self.other.setCurrentIndex(self.other.findData(other_id))
        self._count()

    def _count(self) -> None:
        account_id = self.account.currentData()
        self.lines = (
            []
            if account_id is None
            else balance_lines(
                self.s.conn,
                self.s.company_id,
                account_id,
                self.on_date,
                self.layers,
                self.document_id,
            )
        )
        if account_id is None:
            self.found.setText("")
        elif not self.lines:
            self.found.setText(tr("На эту дату у счёта нет остатка"))
        else:
            debit = sum(ln.amount for ln in self.lines if ln.amount > 0)
            credit = -sum(ln.amount for ln in self.lines if ln.amount < 0)
            parts = [tr("Строк: {n}", n=len(self.lines))]
            if debit:
                parts.append(tr("дебет {sum}", sum=format_minor(debit)))
            if credit:
                parts.append(tr("кредит {sum}", sum=format_minor(credit)))
            self.found.setText(" · ".join(parts))
        self.ok.setEnabled(bool(self.lines))

    def accept(self) -> None:
        if not self.lines:
            return
        self.other_id = self.other.currentData()
        super().accept()
