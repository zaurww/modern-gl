"""The fields of the entry line under a statement (D78), left to right as typed:
[date] · counterparty · account · [its analytics] · e-qaimə · money in · money out (or
one amount with its sign) · purpose. The parts of the line fill and read them."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QLineEdit, QVBoxLayout, QWidget

from modern_gl.application.bank import BankPlace
from modern_gl.desktop.pick import PickBox, SuggestBox
from modern_gl.desktop.session import Session
from modern_gl.desktop.widgets import date_edit
from modern_gl.i18n import tr
from modern_gl.reporting.invoices import OpenInvoice

TWO, ONE = "two", "one"  # money in two columns, or one with its sign


def amount_edit(placeholder: str) -> QLineEdit:
    edit = QLineEdit()
    edit.setPlaceholderText(placeholder)
    edit.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    edit.setFixedWidth(120)
    return edit


class EntryFields(QWidget):
    def __init__(self, session: Session) -> None:
        super().__init__()
        self.s = session
        self.place: BankPlace | None = None
        self.period = ("", "")
        self.mode = TWO
        self.counterparty: int | None = None
        self.auto_account = False  # the account came "as last time": Enter goes past it
        self.analytics_position: int | None = None
        self.contract_position: int | None = None
        self.invoices: list[OpenInvoice] = []
        self.chosen_invoices: list[OpenInvoice] = []  # the e-qaimə the line pays
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)
        self.frame = QFrame()
        self.frame.setObjectName("note")  # the one place of the page that takes typing
        row = QHBoxLayout(self.frame)
        row.setContentsMargins(8, 8, 8, 8)
        row.setSpacing(6)
        self._build_fields(row)
        root.addWidget(self.frame)
        self.error = QLabel()
        self.error.setObjectName("error")
        self.error.setWordWrap(True)
        self.error.hide()
        root.addWidget(self.error)

    def _build_fields(self, row: QHBoxLayout) -> None:
        self.date = date_edit(self.s.working_date)
        self.date.setFixedWidth(120)
        self.counterparty_box = PickBox(tr("Контрагент"))
        self.counterparty_box.can_add = True
        self.account = PickBox(tr("Счёт: 60, 70, 68…"))
        self.analytics = PickBox()
        self.analytics.setFixedWidth(170)
        self.invoice = SuggestBox(tr("E-qaimə"))
        self.invoice.setFixedWidth(150)
        self.money_in = amount_edit(tr("Приход"))
        self.money_out = amount_edit(tr("Расход"))
        self.amount = amount_edit("0.00")
        self.sign = QLabel()
        self.sign.setObjectName("secondary")
        self.sign.setFixedWidth(64)
        self.memo = QLineEdit()
        self.memo.setPlaceholderText(tr("Назначение"))
        for widget, stretch in (
            (self.date, 0),
            (self.counterparty_box, 2),
            (self.account, 3),
            (self.analytics, 0),
            (self.invoice, 0),
            (self.money_in, 0),
            (self.money_out, 0),
            (self.amount, 0),
            (self.sign, 0),
            (self.memo, 2),
        ):
            row.addWidget(widget, stretch)

    def amount_fields(self) -> list[QLineEdit]:
        return [self.amount] if self.mode == ONE else [self.money_in, self.money_out]

    def show_mode(self) -> None:
        one = self.mode == ONE
        self.amount.setVisible(one)
        self.sign.setVisible(one)
        self.money_in.setVisible(not one)
        self.money_out.setVisible(not one)

    def show_error(self, message: str) -> None:
        self.error.setText(message)
        self.error.setVisible(bool(message))
