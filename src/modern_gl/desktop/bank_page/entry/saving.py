"""The entry line becomes a posted bank operation (D78): one line on the account typed,
its kind by that account, the direction by the column the amount is in (or its sign)."""

from __future__ import annotations

from modern_gl.application.bank import (
    FEE,
    IN,
    OUT,
    BankLine,
    BankOperationInput,
    default_memo,
    kind_of_account,
)
from modern_gl.desktop.bank_page.entry.choices import EntryChoices
from modern_gl.desktop.bank_page.entry.fields import ONE
from modern_gl.desktop.widgets import edited_date
from modern_gl.domain.accounts import BANK_FEE
from modern_gl.domain.errors import LedgerError
from modern_gl.domain.money import to_minor
from modern_gl.i18n import tr


class EntrySaving(EntryChoices):
    def read_amount(self) -> tuple[int, str]:
        """(amount, direction); raises ValueError with what to fix."""
        if self.mode == ONE:
            text = self.amount.text().strip().replace("−", "-")
            if not text.lstrip("+-"):
                raise ValueError(tr("Впишите сумму"))
            sign = text[0] if text[0] in "+-" else ""
            amount = to_minor(text.lstrip("+-"))
            direction = {"+": IN, "-": OUT}.get(sign, self.guessed_direction())
            return amount, direction
        money_in, money_out = self.money_in.text().strip(), self.money_out.text().strip()
        if money_in and money_out:
            raise ValueError(tr("Сумма — либо в приходе, либо в расходе, не в обоих"))
        if not money_in and not money_out:
            raise ValueError(tr("Впишите сумму"))
        return (to_minor(money_in), IN) if money_in else (to_minor(money_out), OUT)

    def operation(self) -> BankOperationInput:
        """What the line says; raises ValueError with what to fix."""
        place, info, data = self.place, self.account_info, self.account.currentData()
        if place is None:
            raise ValueError(tr("Не выбран банковский счёт"))
        if info is None or data is None:
            raise ValueError(tr("Выберите счёт: куда ушли деньги или откуда пришли"))
        codes = self.s.catalog.kind_codes
        needs_counterparty = any(
            k is not None and codes.get(k) == "counterparty" and i not in info.sc_optional
            for i, k in enumerate(info.sc_kinds)
        )
        if needs_counterparty and self.counterparty is None:
            raise ValueError(tr("Для счёта {code} нужен контрагент", code=info.short))
        position = self.analytics_position
        empty = position is not None and self.analytics.currentData() is None
        if empty and position not in info.sc_optional:
            raise ValueError(tr("Не заполнено «{kind}»", kind=self.analytics.placeholderText()))
        amount, direction = self.read_amount()
        if amount <= 0:
            raise ValueError(tr("Сумма должна быть больше нуля"))
        kind = self._kind(info.id, info.account_type)
        name = self.s.catalog.value(self.counterparty).name if self.counterparty else ""
        return BankOperationInput(
            doc_date=self.day(),
            direction=direction,
            account_id=place.account_id,
            subconto=place.subconto,
            currency_id=place.currency_id,
            kind=kind,
            counterparty_id=self.counterparty,
            lines=(BankLine(info.id, amount, self._line_subconto(), self.invoice.text().strip()),),
            memo=self.memo.text().strip() or default_memo(direction, kind, name),
        )

    def _kind(self, account_id: int, account_type: str | None) -> str:
        fee = self.s.ledger.account_role(self.s.company_id, BANK_FEE)
        return FEE if account_id == fee else kind_of_account(account_type)

    def _line_subconto(self) -> tuple[int | None, ...]:
        """The bank of a transfer, the analytics, the only contract; the counterparty
        fills its own position when the operation is saved."""
        account_id, bank = self.account.currentData()
        info = self.s.catalog.accounts[account_id]
        values: list[int | None] = [None, None, None]
        if bank is not None:
            codes = self.s.catalog.kind_codes
            at = next(i for i, k in enumerate(info.sc_kinds) if codes.get(k or 0) == "bank_account")
            values[at] = bank
        if self.analytics_position is not None:
            values[self.analytics_position] = self.analytics.currentData()
        if self.contract_position is not None:
            values[self.contract_position] = self.contract()
        return tuple(values)

    def day(self) -> str:
        start, end = self.period
        return start if start == end else edited_date(self.date).isoformat()

    def save(self) -> bool:
        """Post what the line says; the line is cleared for the next one."""
        try:
            data = self.operation()
            start, end = self.period
            if not start <= data.doc_date <= end:
                raise ValueError(tr("Дата — в пределах выписки"))
            self.s.ledger.save_bank_operation(self.s.company_id, data, post=True)
        except (ValueError, LedgerError) as e:
            self.show_error(str(e))
            return False
        self.show_error("")
        self.clear(keep_date=True)
        return True

    def clear(self, keep_date: bool = False) -> None:
        for box in (self.counterparty_box, self.account, self.analytics):
            box.setCurrentIndex(-1)
        self.invoice.setText("")  # its list stays: the counterparty's e-qaimə
        for edit in (self.money_in, self.money_out, self.amount, self.memo):
            edit.clear()
        self.counterparty, self.auto_account = None, False
        self.account_chosen()
        if not keep_date:
            self.show_error("")
