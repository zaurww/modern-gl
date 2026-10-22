"""One side of a conversion (what left one account, what came to the other) and a figure
of the summary under them."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from modern_gl.application.catalog import AccountInfo
from modern_gl.application.conversions import ConversionSide
from modern_gl.desktop.conversion_page.common import (
    NONE,
    amount_text,
    fit_currency,
    money_accounts,
)
from modern_gl.desktop.pick import PickBox
from modern_gl.desktop.session import Session
from modern_gl.desktop.theme import fonts
from modern_gl.desktop.widgets import date_edit
from modern_gl.domain.money import to_minor
from modern_gl.i18n import tr


class SidePanel(QFrame):
    """One bank account of the conversion: account, its subconto, currency, amount."""

    changed = Signal()

    def __init__(self, session: Session, title: str, credit: bool) -> None:
        super().__init__()
        self.setObjectName("card")
        self.s = session
        self.credit = credit
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 20)
        lay.setSpacing(12)
        heading = QLabel(title)
        heading.setFont(fonts().heading)
        lay.addWidget(heading)

        self.form = QGridLayout()
        self.form.setHorizontalSpacing(14)
        self.form.setVerticalSpacing(10)
        self.form.setColumnStretch(1, 1)
        lay.addLayout(self.form)
        lay.addStretch(1)

        self.account = PickBox(NONE)
        for a in money_accounts(session):
            self.account.addItem(a.label, a.id)
        self._row(tr("Счёт"), self.account)
        # subconto of the account: one picker per position, shown when the account has it
        self.sc_captions: list[QLabel] = []
        self.sc: list[PickBox] = []
        for _ in range(3):
            caption = QLabel()
            caption.setObjectName("secondary")
            box = PickBox(NONE)
            box.activated.connect(self._subconto_changed)
            self.sc_captions.append(caption)
            self.sc.append(box)
            self._row(caption, box)
        self.currency = PickBox()
        self._row(tr("Валюта"), self.currency)
        self.amount = QLineEdit()
        self.amount.setFont(fonts().total)
        self.amount.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.amount.setPlaceholderText("0.00")
        self._row(tr("Сумма"), self.amount)
        self.date = date_edit(session.working_date)
        self.date.setFixedWidth(130)
        if credit:
            self.date.setToolTip(tr("Банк может зачислить на следующий день"))
            self._row(tr("Дата зачисления"), self.date)
        else:  # the date of the document: the exchange difference is of this day
            self._row(tr("Дата списания"), self.date)
        self.reference = QLineEdit()
        self.reference.setPlaceholderText(tr("из банковской выписки, необязательно"))
        self._row(tr("Референс"), self.reference)

        self.account.activated.connect(self._account_changed)
        self.currency.activated.connect(lambda _: self.changed.emit())
        self.amount.textEdited.connect(lambda _: self.changed.emit())
        self.date.dateChanged.connect(lambda _: self.changed.emit())
        self.reference.textEdited.connect(lambda _: self.changed.emit())
        self._account_changed()

    def _row(self, caption: str | QLabel, widget: QWidget) -> None:
        if isinstance(caption, str):
            caption = QLabel(caption)
            caption.setObjectName("secondary")
        row = self.form.rowCount()
        self.form.addWidget(caption, row, 0)
        self.form.addWidget(widget, row, 1)

    @property
    def account_info(self) -> AccountInfo | None:
        account_id = self.account.currentData()
        return self.s.catalog.accounts.get(account_id) if account_id is not None else None

    def _account_changed(self, *_) -> None:
        account = self.account_info
        kinds = account.sc_kinds if account else (None, None, None)
        for caption, box, kind in zip(self.sc_captions, self.sc, kinds, strict=True):
            box.clear()
            shown = kind is not None
            caption.setVisible(shown)
            box.setVisible(shown)
            if kind is None:
                continue
            caption.setText(self.s.catalog.kinds[kind])
            values = self.s.catalog.values(kind)
            for v in values:
                box.addItem(v.name, v.id)
            if len(values) == 1:  # the only element: chosen already
                box.setCurrentIndex(0)
        self._fit_currency()
        self.changed.emit()

    def _subconto_changed(self, *_) -> None:
        self._fit_currency()
        self.changed.emit()

    def _fit_currency(self) -> None:
        fit_currency(self.currency, self.s, self.account_info, self.subconto())

    def subconto(self) -> tuple[int | None, ...]:
        return tuple(box.currentData() for box in self.sc)

    def code(self) -> str:
        return self.currency.currentText()

    def parsed_amount(self) -> int:
        text = self.amount.text().strip()
        return to_minor(text) if text else 0

    def value(self) -> ConversionSide | None:
        """What is entered, None if not even the account is (a draft without this side)."""
        account_id = self.account.currentData()
        if account_id is None:
            return None
        return ConversionSide(
            account_id,
            self.parsed_amount(),
            self.subconto(),
            self.currency.currentData(),
            self.reference.text().strip(),
        )

    def set_value(self, side: ConversionSide | None) -> None:
        if side is None:
            self.account.setCurrentIndex(-1)
            self._account_changed()
            self.amount.clear()
            self.reference.clear()
            return
        i = self.account.findData(side.account_id)
        if i < 0:  # an account no longer offered (hidden, retyped) stays as it was
            self.account.addItem(self.s.catalog.accounts[side.account_id].label, side.account_id)
            i = self.account.count() - 1
        self.account.setCurrentIndex(i)
        self._account_changed()
        for box, value in zip(self.sc, side.subconto, strict=False):
            if value is None:
                continue
            j = box.findData(value)
            if j < 0:
                box.addItem(self.s.catalog.value(value).name, value)
                j = box.count() - 1
            box.setCurrentIndex(j)
        self._fit_currency()
        j = self.currency.findData(side.currency_id)
        if j >= 0:
            self.currency.setCurrentIndex(j)
        self.amount.setText(amount_text(side.amount))
        self.reference.setText(side.reference)

    def set_read_only(self, read_only: bool) -> None:
        for w in (self.account, self.currency, self.date, *self.sc):
            w.setEnabled(not read_only)
        for edit in (self.amount, self.reference):
            edit.setReadOnly(read_only)
        if not read_only:
            self._fit_currency()


class Stat(QWidget):
    """A caption over a number: the summary under the form."""

    def __init__(self, caption: str) -> None:
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        self.caption = QLabel(caption)
        self.caption.setObjectName("secondary")
        self.caption.setFont(fonts().small)
        self.value = QLabel(NONE)
        self.value.setFont(fonts().heading)
        lay.addWidget(self.caption)
        lay.addWidget(self.value)

    def set(self, text: str, color: str | None = None) -> None:
        self.value.setText(text)
        self.value.setStyleSheet(f"color: {color};" if color else "")
