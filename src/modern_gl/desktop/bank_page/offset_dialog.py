"""«Зачесть авансы» (D78): what was paid ahead to a counterparty (or by it) set against its
e-qaimə that came later, oldest first — Dt 60.1 [e-qaimə] / Ct 60.2 (a supplier), Dt 62.2
/ Ct 62.1 [e-qaimə] (a customer). The payments and their statements stay as they were."""

from __future__ import annotations

from PySide6.QtWidgets import QDialog, QFormLayout, QHBoxLayout, QLabel, QVBoxLayout

from modern_gl.application.bank import AdvanceOffset
from modern_gl.desktop.bank_operation_page.common import counterparty_kind
from modern_gl.desktop.pick import PickBox
from modern_gl.desktop.session import Session
from modern_gl.desktop.theme import fonts
from modern_gl.desktop.widgets import button, ru_date
from modern_gl.domain.errors import LedgerError
from modern_gl.domain.money import format_minor
from modern_gl.i18n import tr


class AdvanceOffsetDialog(QDialog):
    def __init__(self, session: Session, day: str, parent=None) -> None:
        super().__init__(parent)
        self.s, self.day = session, day
        self.offsets: list[AdvanceOffset] = []
        self.setWindowTitle(tr("Зачесть авансы"))
        self.setMinimumWidth(520)
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 20)
        root.setSpacing(14)
        title = QLabel(tr("Зачесть авансы на {day}", day=ru_date(day)))
        title.setFont(fonts().heading)
        root.addWidget(title)
        form = QFormLayout()
        self.counterparty = PickBox(tr("Название или VÖEN"))
        kind = counterparty_kind(session)
        for v in session.catalog.values(kind) if kind is not None else []:
            self.counterparty.addItem(v.label, v.id, v.name)
        self.counterparty.activated.connect(lambda _: self.plan())
        form.addRow(tr("Контрагент"), self.counterparty)
        root.addLayout(form)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        root.addWidget(self.summary, 1)
        row = QHBoxLayout()
        row.addStretch(1)
        cancel, self.ok = button(tr("Отмена")), button(tr("Зачесть"), "primary")
        cancel.clicked.connect(self.reject)
        self.ok.clicked.connect(self.offset)
        self.ok.setEnabled(False)
        row.addWidget(cancel)
        row.addWidget(self.ok)
        root.addLayout(row)

    def plan(self) -> None:
        """Each advance of the counterparty against its unpaid e-qaimə, oldest first."""
        value = self.counterparty.currentData()
        self.offsets = (
            []
            if value is None
            else self.s.ledger.bank.plan_advance_offsets(self.s.company_id, self.day, value)
        )
        lines = [self._describe(o) for o in self.offsets]
        self.summary.setText("\n\n".join(lines) or tr("Авансов к зачёту нет."))
        self.ok.setEnabled(any(o.parts for o in self.offsets))

    def _describe(self, o: AdvanceOffset) -> str:
        account = self.s.catalog.accounts[o.advance]
        head = tr(
            "{account}: аванс {amount}",
            account=account.label,
            amount=format_minor(o.advance_amount),
        )
        if not o.parts:
            return head + " — " + tr("неоплаченных e-qaimə нет")
        rows = [f"    {number}  {format_minor(amount)}" for number, amount in o.parts]
        return "\n".join([head, *rows])

    def offset(self) -> None:
        try:
            self.s.ledger.bank.offset_all_advances(
                self.s.company_id, self.day, self.counterparty.currentData()
            )
        except LedgerError as e:
            self.summary.setText(str(e))
            return
        self.accept()
