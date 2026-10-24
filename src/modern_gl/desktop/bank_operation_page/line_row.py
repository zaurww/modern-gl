"""One line of a bank operation: an account, its subconto, the e-qaimə and the amount."""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLineEdit,
    QWidget,
)

from modern_gl.application.bank import BankLine
from modern_gl.application.catalog import AccountInfo
from modern_gl.application.invoices import OpenInvoice
from modern_gl.desktop.bank_operation_page.common import (
    SEVERAL,
    counterparty_kind,
    offer_invoices,
    select_data,
)
from modern_gl.desktop.conversion_page.common import amount_text
from modern_gl.desktop.pick import PickBox, SuggestBox
from modern_gl.desktop.session import Session
from modern_gl.desktop.widgets import button
from modern_gl.domain.money import to_minor
from modern_gl.i18n import tr


class LineRow(QWidget):
    """One line: the account, its subconto (the counterparty of the operation fills its
    own position), the e-qaimə and the amount."""

    changed = Signal()
    edited = Signal()  # the account or subconto changed by hand: no more suggestions
    removed = Signal(object)
    unknown = Signal(object, int, str)  # the row, the subconto position, the typed name
    added = Signal(object, int, str)  # the same, "+ Добавить «…»" picked from the list
    error = Signal(str)
    several = Signal(object)  # the row: one payment over several e-qaimə

    def __init__(self, session: Session) -> None:
        super().__init__()
        self.s = session
        self.counterparty: int | None = None
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        self.account = PickBox(tr("Счёт…"))
        for a in session.catalog.leaf_accounts:
            self.account.addItem(a.label, a.id)
        self.account.setMinimumWidth(200)
        self.account.unknown.connect(
            lambda text: self.error.emit(tr("«{text}» нет в списке", text=text))
        )
        lay.addWidget(self.account, 3)
        self.sc: list[PickBox] = []
        for position in range(3):
            box = PickBox()
            box.setMinimumWidth(120)
            box.activated.connect(self._subconto_edited)
            box.unknown.connect(lambda text, p=position: self.unknown.emit(self, p, text))
            box.added.connect(lambda text, p=position: self.added.emit(self, p, text))
            box.can_add = True
            self.sc.append(box)
            lay.addWidget(box, 2)
        self.invoice = SuggestBox(tr("E-qaimə"))  # the unpaid ones of the counterparty
        self.invoice.setFixedWidth(160)
        self.invoice.activated.connect(self._invoice_chosen)
        lay.addWidget(self.invoice)
        self.amount = QLineEdit()
        self.amount.setFixedWidth(130)
        self.amount.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.amount.setPlaceholderText("0.00")
        lay.addWidget(self.amount)
        self.remove = button("×", "flat", tr("Убрать строку") + " (Ctrl+Del)")
        self.remove.setFixedWidth(32)
        self.remove.setFocusPolicy(Qt.FocusPolicy.NoFocus)  # Ctrl+Del from the keyboard
        lay.addWidget(self.remove)

        self.account.activated.connect(self._account_edited)
        self.invoice.textEdited.connect(lambda _: self.changed.emit())
        self.amount.textEdited.connect(lambda _: self.changed.emit())
        self.remove.clicked.connect(lambda: self.removed.emit(self))
        self._fill_subconto(())

    @property
    def account_info(self) -> AccountInfo | None:
        account_id = self.account.currentData()
        return self.s.catalog.accounts.get(account_id) if account_id is not None else None

    def _account_edited(self, *_) -> None:
        self._fill_subconto(())
        self.edited.emit()
        self.changed.emit()

    def _subconto_edited(self, *_) -> None:
        self.edited.emit()
        self.changed.emit()

    def _fill_subconto(self, chosen: Sequence[int | None]) -> None:
        """A picker per subconto of the account; the counterparty of the operation is its
        own position, so that one is not shown. Contracts are the counterparty's."""
        catalog = self.s.catalog
        account = self.account_info
        kinds = account.sc_kinds if account else (None, None, None)
        own = counterparty_kind(self.s)
        chosen = [*chosen, None, None, None][:3]
        for box, kind, value in zip(self.sc, kinds, chosen, strict=True):
            box.clear()
            hidden = kind is None or (kind == own and self.counterparty is not None)
            box.setVisible(not hidden)
            if hidden:
                continue
            assert kind is not None
            owner = self.counterparty if catalog.owner_kinds.get(kind) == own else None
            box.setPlaceholderText(catalog.kinds[kind] + "…")
            for v in catalog.values(kind, owner):
                box.addItem(v.label, v.id, v.name)
            if value is not None:
                select_data(box, value, catalog.value(value).name)
            elif box.count() == 1:  # the only element: chosen already
                box.setCurrentIndex(0)
        self.invoice.setVisible(catalog.takes_invoice(account.id if account else None))

    def set_counterparty(self, counterparty: int | None) -> None:
        if counterparty == self.counterparty:
            return
        kept = self.subconto()
        self.counterparty = counterparty
        own = counterparty_kind(self.s)
        account = self.account_info
        if account is not None:  # a contract of another counterparty goes
            kept = tuple(
                None if v is not None and self.s.catalog.owned_elsewhere(v, counterparty) else v
                for v in kept
            )
            kept = tuple(
                None if k == own else v for k, v in zip(account.sc_kinds, kept, strict=True)
            )
        self._fill_subconto(kept)

    def set_invoices(self, invoices: Sequence[OpenInvoice]) -> None:
        offer_invoices(self.invoice, invoices)

    def _invoice_chosen(self, index: int) -> None:
        chosen = self.invoice.itemData(index) if index >= 0 else None
        if chosen == SEVERAL:
            self.several.emit(self)
            return
        if isinstance(chosen, OpenInvoice) and not self.amount.text().strip():
            self.amount.setText(amount_text(chosen.amount))  # what is left to pay on it
        self.changed.emit()

    def owner_of(self, position: int) -> int | None:
        """Whose a new element at this position is: a contract is the counterparty's."""
        account = self.account_info
        kind = account.sc_kinds[position] if account else None
        if kind is None or self.s.catalog.owner_kinds.get(kind) != counterparty_kind(self.s):
            return None
        return self.counterparty

    def set_subconto(self, position: int, value: int) -> None:
        chosen = list(self.subconto())
        chosen[position] = value
        self._fill_subconto(chosen)
        self._subconto_edited()

    def subconto(self) -> tuple[int | None, ...]:
        """The chosen subconto; the counterparty's position is left to the operation."""
        return tuple(None if box.isHidden() else box.currentData() for box in self.sc)

    def is_empty(self) -> bool:
        return self.account.currentData() is None and not self.amount.text().strip()

    def value(self) -> BankLine | None:
        """None for an empty line (just added, not filled in)."""
        if self.is_empty():
            return None
        text = self.amount.text().strip()
        return BankLine(
            self.account.currentData(),
            to_minor(text) if text else 0,
            self.subconto(),
            "" if self.invoice.isHidden() else self.invoice.text().strip(),
        )

    def set_line(self, line: BankLine, amount: bool = True) -> None:
        if line.account_id is not None:
            select_data(
                self.account, line.account_id, self.s.catalog.accounts[line.account_id].label
            )
        else:
            self.account.setCurrentIndex(-1)
        self._fill_subconto(line.subconto)
        if amount:
            self.amount.setText(amount_text(line.amount))
            self.invoice.setText(line.invoice)

    def set_read_only(self, read_only: bool) -> None:
        for w in (self.account, *self.sc):
            w.setEnabled(not read_only)
        for edit in (self.invoice, self.amount):
            edit.setReadOnly(read_only)
        self.remove.setVisible(not read_only)
