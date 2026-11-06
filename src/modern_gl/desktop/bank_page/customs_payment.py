"""«Таможенный платёж»: one payment, what it pays by name; no accounts to think of (D212)."""

from __future__ import annotations

from datetime import date

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
)

from modern_gl.application.bank import BankOperation
from modern_gl.application.bank.customs_payment import CustomsPayment
from modern_gl.application.default_accounts import SUPPLIER, default_account
from modern_gl.application.table_text import plain_number
from modern_gl.desktop.session import Session
from modern_gl.desktop.widgets import caption, date_edit, edited_date, money
from modern_gl.domain.errors import LedgerError
from modern_gl.domain.money import to_minor
from modern_gl.i18n import tr
from modern_gl.reporting.inventory import customs_declarations, last_customs_party


class CustomsPaymentDialog(QDialog):
    def __init__(
        self,
        session: Session,
        account_id: int,
        subconto,
        day: str,
        parent=None,
        loaded: BankOperation | None = None,
    ) -> None:
        """`loaded` — the statement's line this payment is: its day and sum are the bank's."""
        super().__init__(parent)
        self.loaded = loaded
        self.s = session
        self.account_id, self.subconto = account_id, tuple(subconto)
        self.setWindowTitle(tr("Таможенный платёж"))
        self.setMinimumWidth(520)
        form = QFormLayout(self)
        hint = caption(
            tr(
                "Заполните только то, что есть в платеже. По короткой декларации обычно есть "
                "только терминал: его сумма — вместе с ƏDV, как в его e-qaimə."
            )
        )
        hint.setWordWrap(True)
        form.addRow(hint)
        self.date = date_edit(date.fromisoformat(loaded.doc_date if loaded else day))
        self.date.setEnabled(loaded is None)
        form.addRow(tr("Дата"), self.date)
        self.declaration = QComboBox()
        self.declaration.setEditable(True)
        self.declaration.addItem("")
        self.declaration.addItems(customs_declarations(session.conn, session.company_id))
        form.addRow(tr("Декларация"), self.declaration)
        self.fees = self._amount()
        form.addRow(tr("Пошлины и сборы"), self.fees)
        self.terminal_party = self._parties()
        self.terminal = self._amount()
        form.addRow(tr("Терминал"), self.terminal_party)
        form.addRow(tr("Сумма терминалу"), self.terminal)
        self.customs_party = self._parties()
        chosen = last_customs_party(session.conn, session.company_id)
        self.customs_party.setCurrentIndex(max(self.customs_party.findData(chosen), 0))
        self.vat = self._amount()
        form.addRow(tr("Таможня"), self.customs_party)
        form.addRow(tr("ƏDV декларации"), self.vat)
        self.total = QLabel()
        form.addRow(tr("Итого"), self.total)
        self.error = QLabel()
        self.error.setWordWrap(True)
        self.error.hide()
        form.addRow(self.error)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)
        self._count()

    def _amount(self) -> QLineEdit:
        field = QLineEdit()
        field.textChanged.connect(lambda _text: self._count())
        return field

    def _parties(self) -> QComboBox:
        """The counterparties, found by typing."""
        combo = QComboBox()
        combo.setEditable(True)
        combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        combo.addItem("", None)
        catalog = self.s.catalog
        kind = next((k for k, code in catalog.kind_codes.items() if code == "counterparty"), None)
        for value in catalog.values(kind) if kind is not None else []:
            combo.addItem(value.name, value.id)
        return combo

    @staticmethod
    def _minor(field: QLineEdit) -> int:
        text = field.text().strip()
        return to_minor(plain_number(text)) if text else 0

    def _count(self) -> None:
        try:
            total = sum(self._minor(f) for f in (self.fees, self.terminal, self.vat))
        except (ValueError, ArithmeticError):
            self.total.setText("")
            return
        if self.loaded is None:
            self.total.setText(money(total))
            return
        left = self.loaded.total - total
        text = tr("{total} из {amount}", total=money(total), amount=money(self.loaded.total))
        self.total.setText(text + (f" · {tr('осталось {n}', n=money(left))}" if left else ""))

    def payment(self) -> CustomsPayment:
        account = default_account(self.s.ledger, self.s.company_id, SUPPLIER)
        if account is None:
            raise ValueError(tr("В плане счетов нет счёта поставщиков"))
        return CustomsPayment(
            edited_date(self.date).isoformat(),
            self.account_id,
            self.subconto,
            account,
            self.declaration.currentText().strip(),
            self._minor(self.fees),
            self._minor(self.terminal),
            self.terminal_party.currentData(),
            self._minor(self.vat),
            self.customs_party.currentData(),
        )

    def _save(self) -> None:
        try:
            self.s.ledger.bank.save_customs_payment(
                self.s.company_id,
                self.payment(),
                self.loaded.id if self.loaded else None,
            )
        except (LedgerError, ValueError, ArithmeticError) as exc:
            self.error.setText(str(exc))
            self.error.show()
            return
        self.accept()
