"""Windows of the page «Банк» (D78): a new bank account or business card and its details,
a statement for a period (a weekend, a card's month)."""

from __future__ import annotations

from datetime import date

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from modern_gl.application.bank import ACCOUNT_KINDS, CARD, CURRENCY, VAT_DEPOSIT, BankAccount
from modern_gl.desktop.session import Session
from modern_gl.desktop.theme import fonts
from modern_gl.desktop.widgets import button, date_edit, edited_date
from modern_gl.domain.errors import LedgerError
from modern_gl.i18n import tr
from modern_gl.infrastructure.db import transaction

# the GL account a new account of a kind goes on, the first of these that exists
USUAL_ACCOUNTS = {CARD: ("55", "51"), CURRENCY: ("52",), VAT_DEPOSIT: ("54",)}


class BankAccountDialog(QDialog):
    """New: the name, kind, GL account, currency, a card's digits and holder, IBAN.
    Existing: the same but the GL account and currency (old postings carry them)."""

    def __init__(self, session: Session, account: BankAccount | None, parent=None) -> None:
        super().__init__(parent)
        self.s, self.account = session, account
        self.saved_value: int | None = None
        self.setWindowTitle(tr("Банковский счёт") if account else tr("Новый банковский счёт"))
        self.setMinimumWidth(520)
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 20)
        root.setSpacing(16)
        title = QLabel(self.windowTitle())
        title.setFont(fonts().heading)
        root.addWidget(title)
        form = QFormLayout()
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(10)
        self.name = QLineEdit(account.place.name if account else "")
        self.name.setPlaceholderText(tr("ABB, Kapital Bank USD, ABB Visa…"))
        self.kind = QComboBox()
        for kind, title in ACCOUNT_KINDS:
            self.kind.addItem(tr(title), kind)
        self.ledger_account = QComboBox()
        for a in self._bank_ledger_accounts():
            self.ledger_account.addItem(a.label, a.id)
        self.currency = QComboBox()
        self.currency.addItem("AZN", None)
        for c in session.catalog.active_currencies:
            self.currency.addItem(c.code, c.id)
        self.digits = QLineEdit(account.card_digits if account else "")
        self.digits.setMaxLength(4)
        self.digits.setPlaceholderText("4417")
        self.digits.setFixedWidth(90)
        self.holder = QComboBox()
        self.holder.addItem(tr("— не указан —"), None)
        for v in self._employees():
            self.holder.addItem(v.name, v.id)
        self.iban = QLineEdit(account.iban if account else "")
        self.iban.setPlaceholderText("AZ00 XXXX 0000 0000 0000 0000 0000")
        self.closed = QCheckBox(tr("Счёт закрыт — в конце списка"))
        form.addRow(tr("Название"), self.name)
        form.addRow(tr("Вид"), self.kind)
        form.addRow(tr("Счёт учёта"), self.ledger_account)
        form.addRow(tr("Валюта"), self.currency)
        self.card_rows = [(tr("Последние 4 цифры"), self.digits), (tr("Держатель"), self.holder)]
        for caption, widget in self.card_rows:
            form.addRow(caption, widget)
        form.addRow("IBAN", self.iban)
        form.addRow("", self.closed)
        self.form = form
        root.addLayout(form)
        self.error = QLabel()
        self.error.setObjectName("error")
        self.error.setWordWrap(True)
        self.error.hide()
        root.addWidget(self.error)
        root.addLayout(self._buttons())
        self.kind.currentIndexChanged.connect(self._kind_changed)
        if account:
            self._load(account)
        else:
            self.closed.hide()
            self._kind_changed()

    def _buttons(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.addStretch(1)
        cancel, save = button(tr("Отмена")), button(tr("Сохранить"), "primary")
        save.setDefault(True)
        cancel.clicked.connect(self.reject)
        save.clicked.connect(self.save)
        row.addWidget(cancel)
        row.addWidget(save)
        return row

    def _bank_ledger_accounts(self):
        cat = self.s.catalog
        return [
            a
            for a in cat.leaf_accounts
            if a.account_type in ("bank", "vat_deposit")
            or any(k is not None and cat.kind_codes.get(k) == "bank_account" for k in a.sc_kinds)
        ]

    def _employees(self):
        cat = self.s.catalog
        kind = next((k for k, code in cat.kind_codes.items() if code == "employee"), None)
        return cat.values(kind) if kind is not None else []

    def _load(self, a: BankAccount) -> None:
        self.kind.setCurrentIndex(max(self.kind.findData(a.kind), 0))
        self.ledger_account.setCurrentIndex(
            max(self.ledger_account.findData(a.place.account_id), 0)
        )
        self.currency.setCurrentIndex(max(self.currency.findData(a.place.currency_id), 0))
        holder = next(
            (i for i in range(self.holder.count()) if self.holder.itemText(i) == a.holder), 0
        )
        self.holder.setCurrentIndex(holder)
        self.closed.setChecked(a.closed)
        self.ledger_account.setEnabled(False)  # old postings are on it
        self.currency.setEnabled(False)
        self._show_card_rows()

    def _kind_changed(self, *_) -> None:
        if self.account is None:
            codes = USUAL_ACCOUNTS.get(self.kind.currentData(), ("51",))
            by_code = self.s.catalog.by_code
            usual = next((by_code[c].id for c in codes if c in by_code), None)
            if usual is not None and self.ledger_account.findData(usual) >= 0:
                self.ledger_account.setCurrentIndex(self.ledger_account.findData(usual))
        self._show_card_rows()

    def _show_card_rows(self) -> None:
        card = self.kind.currentData() == CARD
        for _, widget in self.card_rows:
            self.form.setRowVisible(widget, card)

    def save(self) -> None:
        led, cid = self.s.ledger, self.s.company_id
        kind = self.kind.currentData()
        card = kind == CARD
        digits = self.digits.text().strip() if card else ""
        holder = self.holder.currentData() if card else None
        try:
            if self.account is None:
                self.saved_value = led.add_bank_account(
                    cid,
                    self.name.text(),
                    self.ledger_account.currentData(),
                    kind,
                    currency_id=self.currency.currentData(),
                    card_digits=digits,
                    holder_id=holder,
                    iban=self.iban.text(),
                )
            else:
                place = self.account.place
                with transaction(self.s.conn):
                    if place.value_id is not None and self.name.text().strip() != place.name:
                        led.update_subconto_value(cid, place.value_id, self.name.text())
                    led.set_bank_account(
                        cid,
                        place.account_id,
                        place.value_id,
                        kind=kind,
                        card_digits=digits,
                        holder_id=holder,
                        iban=self.iban.text(),
                        closed=self.closed.isChecked(),
                    )
                self.saved_value = place.value_id
        except LedgerError as e:
            self.error.setText(str(e))
            self.error.show()
            return
        self.s.catalog.reload()
        self.accept()


class PeriodDialog(QDialog):
    """A statement for several days: a weekend, a card's month."""

    def __init__(self, start: date, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("Выписка за период"))
        root = QVBoxLayout(self)
        row = QHBoxLayout()
        self.date_from, self.date_to = date_edit(start), date_edit(start)
        for caption, edit in ((tr("Период с"), self.date_from), (tr("по"), self.date_to)):
            label = QLabel(caption)
            label.setObjectName("secondary")
            edit.setFixedWidth(130)
            row.addWidget(label)
            row.addWidget(edit)
        root.addLayout(row)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel, ok = button(tr("Отмена")), button(tr("Создать"), "primary")
        ok.setDefault(True)
        cancel.clicked.connect(self.reject)
        ok.clicked.connect(self.accept)
        buttons.addWidget(cancel)
        buttons.addWidget(ok)
        root.addLayout(buttons)

    def period(self) -> tuple[str, str]:
        return edited_date(self.date_from).isoformat(), edited_date(self.date_to).isoformat()
