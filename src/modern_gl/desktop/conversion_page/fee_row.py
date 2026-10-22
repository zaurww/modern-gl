"""One bank fee of a conversion: from any money account, in its own currency."""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QWidget,
)

from modern_gl.application.conversions import ConversionFee
from modern_gl.desktop.conversion_page.common import (
    amount_text,
    fit_currency,
    money_places,
)
from modern_gl.desktop.pick import PickBox
from modern_gl.desktop.session import Session
from modern_gl.desktop.widgets import button
from modern_gl.domain.money import to_minor
from modern_gl.i18n import tr


class FeeRow(QWidget):
    """One bank fee: how much, from which money account (in its currency), to which expense."""

    changed = Signal()
    removed = Signal(object)

    def __init__(self, session: Session) -> None:
        super().__init__()
        self.s = session
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)
        self.amount = QLineEdit()
        self.amount.setFixedWidth(110)
        self.amount.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.amount.setPlaceholderText("0.00")
        lay.addWidget(self.amount)
        self.currency = PickBox()
        self.currency.setFixedWidth(80)
        lay.addWidget(self.currency)
        taken = QLabel(tr("удержана с"))
        taken.setObjectName("secondary")
        lay.addWidget(taken)
        self.place = PickBox(tr("Счёт…"))
        for label, data in money_places(session):
            self.place.addItem(label, data)
        self.place.setCurrentIndex(0)
        lay.addWidget(self.place, 2)
        to = QLabel(tr("на счёт"))
        to.setObjectName("secondary")
        lay.addWidget(to)
        self.expense = PickBox(tr("по настройкам"))
        for account in session.catalog.leaf_accounts:
            self.expense.addItem(account.label, account.id)
        lay.addWidget(self.expense, 1)
        self.remove = button("×", "flat", tr("Убрать комиссию"))
        self.remove.setFixedWidth(32)
        self.remove.setFocusPolicy(Qt.FocusPolicy.NoFocus)  # not a stop on the Enter path
        lay.addWidget(self.remove)

        self.amount.textEdited.connect(lambda _: self.changed.emit())
        self.currency.activated.connect(lambda _: self.changed.emit())
        self.place.activated.connect(self._place_changed)
        self.expense.activated.connect(lambda _: self.changed.emit())
        self.remove.clicked.connect(lambda: self.removed.emit(self))
        self._place_changed()

    def _where(self) -> tuple[int, tuple[int | None, ...]] | None:
        return self.place.currentData()

    def _place_changed(self, *_) -> None:
        self._fit_currency()
        self.changed.emit()

    def _fit_currency(self) -> None:
        where = self._where()
        account = self.s.catalog.accounts.get(where[0]) if where else None
        fit_currency(self.currency, self.s, account, where[1] if where else ())

    def set_place(self, account_id: int, subconto: Sequence[int | None]) -> None:
        data = (account_id, tuple(v for v in subconto if v is not None)[:1])
        i = next((i for i in range(self.place.count()) if self.place.itemData(i) == data), -1)
        if i < 0:  # an account or element no longer offered
            account = self.s.catalog.accounts[account_id]
            name = " / ".join(self.s.catalog.value(v).name for v in data[1])
            self.place.addItem(f"{name}  ·  {account.short}" if name else account.label, data)
            i = self.place.count() - 1
        self.place.setCurrentIndex(i)
        self._place_changed()

    def value(self) -> ConversionFee | None:
        """None while the amount is empty: a line just added and not filled in."""
        text = self.amount.text().strip()
        where = self._where()
        if not text or where is None:
            return None
        return ConversionFee(
            where[0],
            to_minor(text),
            where[1],
            self.currency.currentData(),
            self.expense.currentData(),
        )

    def set_value(self, fee: ConversionFee) -> None:
        self.set_place(fee.account_id, fee.subconto)
        fit_currency(
            self.currency,
            self.s,
            self.s.catalog.accounts.get(fee.account_id),
            fee.subconto,
            fee.currency_id,
        )
        self.amount.setText(amount_text(fee.amount))
        self.expense.setCurrentIndex(self.expense.findData(fee.expense_account_id))

    def set_read_only(self, read_only: bool) -> None:
        self.amount.setReadOnly(read_only)
        for w in (self.place, self.expense):
            w.setEnabled(not read_only)
        self.remove.setVisible(not read_only)
        if read_only:
            self.currency.setEnabled(False)
        else:  # only a currency the account leaves open can be chosen
            self._fit_currency()
