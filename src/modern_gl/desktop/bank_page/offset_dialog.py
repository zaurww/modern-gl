"""«Зачесть авансы» (D78): what was paid ahead to a counterparty (or by it) set against its
e-qaimə that came later, oldest first — Dt 60.1 [e-qaimə] / Ct 60.2 (a supplier), Dt 62.2
/ Ct 62.1 [e-qaimə] (a customer). The payments and their statements stay as they were."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtWidgets import QDialog, QFormLayout, QHBoxLayout, QLabel, QVBoxLayout

from modern_gl.application.bank import allocate, counterparty_balance
from modern_gl.desktop.bank_operation_page.common import counterparty_kind
from modern_gl.desktop.pick import PickBox
from modern_gl.desktop.session import Session
from modern_gl.desktop.theme import fonts
from modern_gl.desktop.widgets import button, ru_date
from modern_gl.domain.accounts import ADVANCE_PAID, ADVANCE_RECEIVED
from modern_gl.domain.errors import LedgerError
from modern_gl.domain.money import format_minor
from modern_gl.i18n import tr
from modern_gl.infrastructure.db import transaction
from modern_gl.reporting.invoices import open_invoices

# (the settlement account's type, the advance's role, the company owes the e-qaimə)
SIDES = (("payable", ADVANCE_PAID, True), ("receivable", ADVANCE_RECEIVED, False))


@dataclass
class Offset:
    settlement: int  # 60.1 / 62.1
    advance: int  # 60.2 / 62.2
    advance_amount: int
    parts: list[tuple[str, int]]  # (e-qaimə, amount)


class AdvanceOffsetDialog(QDialog):
    def __init__(self, session: Session, day: str, parent=None) -> None:
        super().__init__(parent)
        self.s, self.day = session, day
        self.offsets: list[Offset] = []
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
        self.offsets = []
        lines: list[str] = []
        if value is not None:
            for settlement_type, role, payable in SIDES:
                offset = self._plan_side(value, settlement_type, role, payable)
                if offset is not None:
                    self.offsets.append(offset)
                    lines.append(self._describe(offset))
        self.summary.setText("\n\n".join(lines) or tr("Авансов к зачёту нет."))
        self.ok.setEnabled(any(o.parts for o in self.offsets))

    def _plan_side(
        self, value: int, settlement_type: str, role: str, payable: bool
    ) -> Offset | None:
        conn, cid = self.s.conn, self.s.company_id
        advance = self.s.ledger.account_role(cid, role)
        settlement = next(
            (a.id for a in self.s.catalog.leaf_accounts if a.account_type == settlement_type),
            None,
        )
        if advance is None or settlement is None:
            return None
        balance = counterparty_balance(conn, cid, advance, value, self.day)
        amount = balance if payable else -balance
        if amount <= 0:
            return None
        invoices = [
            i
            for i in open_invoices(conn, cid, value, payable=payable, on_date=self.day)
            if not i.source  # only what the books owe
        ]
        paid, _ = allocate(amount, [i.amount for i in invoices])
        parts = [(i.invoice, p) for i, p in zip(invoices, paid, strict=True) if p]
        return Offset(settlement, advance, amount, parts)

    def _describe(self, o: Offset) -> str:
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
        value = self.counterparty.currentData()
        try:
            with transaction(self.s.conn):
                for o in self.offsets:
                    if o.parts:
                        self.s.ledger.offset_advances(
                            self.s.company_id, self.day, value, o.settlement, o.advance, o.parts
                        )
        except LedgerError as e:
            self.summary.setText(str(e))
            return
        self.accept()
