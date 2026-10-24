"""The entry line under a statement (D78): a bank statement's line typed as it is read —
Enter goes on through what is left to type and posts at the amount, as in the journal
(D55); the account "as last time" is passed by; F6 — a bank fee; F2 — the full form
(the ƏDV deposit, several accounts); Esc — empty again, and on an empty line — back to
the statements."""

from __future__ import annotations

from datetime import date

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QApplication, QLineEdit, QWidget

from modern_gl.application.bank import IN, BankPlace
from modern_gl.desktop.bank_operation_page.common import select_data
from modern_gl.desktop.bank_page.entry.fields import ONE
from modern_gl.desktop.bank_page.entry.saving import EntrySaving
from modern_gl.desktop.session import Session
from modern_gl.desktop.widgets import to_qdate
from modern_gl.domain.accounts import BANK_FEE
from modern_gl.i18n import tr

ENTER = (Qt.Key.Key_Return, Qt.Key.Key_Enter)


class EntryLine(EntrySaving):
    saved = Signal()  # an operation was posted: the statement reads its lines again
    expand = Signal(object)  # F2: what is typed, to the full form (BankOperationInput)

    def __init__(self, session: Session) -> None:
        super().__init__(session)
        self.counterparty_box.activated.connect(self.counterparty_chosen)
        self.counterparty_box.added.connect(self._add_counterparty)
        self.counterparty_box.unknown.connect(
            lambda text: self.show_error(tr("«{text}» нет в справочнике", text=text))
        )
        self.account.activated.connect(self._account_typed)
        self.account.unknown.connect(
            lambda text: self.show_error(tr("Счёта «{text}» нет", text=text))
        )
        self.invoice.activated.connect(self.invoice_chosen)
        self.amount.textEdited.connect(lambda _: self.account_hook())
        self.show_mode()
        self.analytics.hide()

    def show_for(self, place: BankPlace, date_from: str, date_to: str, mode: str) -> None:
        """The line of this statement: its account, its days, the way amounts go."""
        changed = (place.key, (date_from, date_to)) != (
            self.place.key if self.place else None,
            self.period,
        )
        self.place, self.period, self.mode = place, (date_from, date_to), mode
        self.date.setVisible(date_from != date_to)
        self.date.setDateRange(
            to_qdate(date.fromisoformat(date_from)), to_qdate(date.fromisoformat(date_to))
        )
        self.show_mode()
        if changed:
            self.fill_lists()
            self.clear()

    def start(self) -> None:
        """The cursor where a new line begins."""
        (self.date if self.date.isVisible() else self.counterparty_box).setFocus()

    # ---- the way through the line ------------------------------------------------------

    def order(self) -> list[QWidget]:
        fields: list[QWidget] = [self.date] if self.date.isVisible() else []
        fields += [self.counterparty_box, self.account]
        if self.analytics_position is not None:
            fields.append(self.analytics)
        if self.invoices_apply():
            fields.append(self.invoice)
        if self.mode == ONE:
            fields.append(self.amount)
        elif self.guessed_direction() == IN:
            fields += [self.money_in, self.money_out]
        else:
            fields += [self.money_out, self.money_in]
        return [*fields, self.memo]

    def focusNextPrevChild(self, next: bool) -> bool:  # Tab, and a list's choice
        self.go(forward=next)
        return True

    def go(self, forward: bool) -> None:
        order = self.order()
        here = QApplication.focusWidget()
        if here is None:
            return
        at = next((i for i, w in enumerate(order) if w is here or w.isAncestorOf(here)), -1)
        if not forward:
            if at > 0:
                order[at - 1].setFocus()
            return
        if here in (self.money_in, self.money_out, self.amount) and isinstance(here, QLineEdit):
            if here.text().strip():
                self.post()
                return
            if self.mode != ONE and order[at + 1] in (self.money_in, self.money_out):
                order[at + 1].setFocus()  # the other column: money went the other way
                return
            self.show_error(tr("Впишите сумму"))
            return
        if here is self.memo:
            self.post()
            return
        step = 2 if here is self.counterparty_box and self.auto_account else 1
        if 0 <= at < len(order) - step:
            order[at + step].setFocus()

    def post(self) -> None:
        if self.save():
            self.saved.emit()
            self.start()

    def keyPressEvent(self, event) -> None:
        key = event.key()
        if key in ENTER and not event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            self.go(forward=True)  # a field took what was typed and passed the key on
        elif key == Qt.Key.Key_Escape and self.is_empty():
            event.ignore()  # nothing to clear: the page goes back
        elif key == Qt.Key.Key_Escape:
            self.clear()
            self.start()
        elif key == Qt.Key.Key_F6:
            self.fee()
        elif key == Qt.Key.Key_F2:
            data = self.draft()
            self.clear(keep_date=True)
            self.expand.emit(data)
        else:
            super().keyPressEvent(event)

    def is_empty(self) -> bool:
        fields = (self.counterparty_box, self.account, self.analytics, self.invoice)
        fields += (self.money_in, self.money_out, self.amount, self.memo)
        return not any(f.text().strip() for f in fields)

    # ---- choices -----------------------------------------------------------------------

    def _account_typed(self, *_) -> None:
        self.auto_account = False  # chosen by hand: Enter stops on it from now on
        self.account_chosen()

    def _add_counterparty(self, name: str) -> None:
        """A counterparty the directory lacks: added from the list (D54)."""
        from modern_gl.desktop.bank_operation_page.common import counterparty_kind

        kind = counterparty_kind(self.s)
        if kind is None:
            return
        value = self.s.ledger.add_subconto_value(self.s.company_id, kind, name)
        self.s.catalog.reload()
        self.fill_lists()
        select_data(self.counterparty_box, value)
        self.counterparty_chosen()

    def fee(self) -> None:
        """A bank fee: its account (settings of the bank, D62), the cursor on the amount."""
        fee = self.s.ledger.account_role(self.s.company_id, BANK_FEE)
        if fee is None or self.account.findData((fee, None)) < 0:
            self.show_error(tr("Счёт комиссии банка не указан: «⋯ → Настройки банка»"))
            return
        self.clear(keep_date=True)
        select_data(self.account, (fee, None))
        self.account_chosen()
        (self.amount if self.mode == ONE else self.money_out).setFocus()

    def account_hook(self) -> None:
        """The way the money goes, shown by a one-column amount; the purpose by default."""
        if self.mode == ONE:
            text = self.amount.text().strip()
            sign = text[:1] if text[:1] in "+-−" else ""
            money_in = sign == "+" or (not sign and self.guessed_direction() == IN)
            self.sign.setText(tr("приход") if money_in else tr("расход"))
            self.sign.setObjectName("success" if money_in else "secondary")
            self.sign.style().unpolish(self.sign)
            self.sign.style().polish(self.sign)
