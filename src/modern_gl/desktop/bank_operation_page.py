"""A bank operation (D47, D64): money in or out of one bank account. One row on top, set
before typing — which way, the bank account (one field), the date, the kind; then the
cursor's path — who, the e-qaimə, how much, «Провести». Below — lines: what it paid (an
account, a contract, an e-qaimə) and how much; one line is folded into a summary and its
e-qaimə and amount are typed above."""

from __future__ import annotations

from collections.abc import Sequence
from contextlib import suppress
from dataclasses import replace
from datetime import date
from itertools import pairwise

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from modern_gl.application.bank import (
    BANK_TYPES,
    CUSTOMER,
    FEE,
    IN,
    KIND_TYPES,
    KINDS,
    OTHER,
    OUT,
    SUPPLIER,
    TRANSFER,
    VAT_DEPOSIT_KINDS,
    BankLine,
    BankOperation,
    BankOperationInput,
    BankPlace,
    bank_places,
    default_memo,
    last_lines,
    load_bank_operation,
    place_balance,
)
from modern_gl.application.catalog import AccountInfo, SubcontoInfo
from modern_gl.application.currencies import rate_on
from modern_gl.application.queries import load_document
from modern_gl.desktop.conversion_page import amount_text, fit_currency
from modern_gl.desktop.directories_page import added_value, new_value
from modern_gl.desktop.invoice_picker import InvoicePicker
from modern_gl.desktop.pick import PickBox, SuggestBox
from modern_gl.desktop.session import Session
from modern_gl.desktop.theme import fonts
from modern_gl.desktop.widgets import (
    Chip,
    MenuItem,
    button,
    date_edit,
    edited_date,
    more_button,
    ru_date,
    to_qdate,
)
from modern_gl.domain.accounts import BANK_FEE
from modern_gl.domain.currency import CURRENCY_ONLY, NO_CURRENCY
from modern_gl.domain.errors import LedgerError
from modern_gl.domain.money import format_minor, to_minor
from modern_gl.i18n import tr
from modern_gl.reporting.invoices import DRAFT, PORTAL, OpenInvoice, open_invoices

NONE = "—"
# the line's account suggests the kind of a counterparty's operation
TYPE_KINDS = {
    "payable": SUPPLIER,
    "advance_paid": SUPPLIER,
    "receivable": CUSTOMER,
    "advance_received": CUSTOMER,
}
WITH_COUNTERPARTY = (SUPPLIER, CUSTOMER, OTHER)
SEVERAL = "several"  # the list item «several e-qaimə…»
# an e-qaimə the books do not have yet: an imported draft, or only seen on the portal
SOURCES = {DRAFT: "черновик", PORTAL: "с портала"}


FIELD_WIDTH = 460  # the fields on the cursor's path


def caption(text: str, name: str = "secondary") -> QLabel:
    label = QLabel(text)
    label.setObjectName(name)
    return label


def place_label(place: BankPlace) -> str:
    """A bank account in one field: «ABB · 51 · AZN»."""
    return f"{place.name}  ·  {place.account_code}  ·  {place.currency or 'AZN'}"


def offer_invoices(box: SuggestBox, invoices: Sequence[OpenInvoice]) -> None:
    """The e-qaimə a list offers: number, date, what is left to pay, and where it is known
    from if not from the posted documents; «several» after them."""
    typed = box.text()
    box.clear()
    for i in invoices:
        label = f"{i.invoice} · {ru_date(i.doc_date)} · {format_minor(i.amount)}"
        if i.vat:
            label += f" · ƏDV {format_minor(i.vat)}"
        if i.source in SOURCES:
            label += f" · {tr(SOURCES[i.source])}"
        box.addItem(label, i, i.invoice)
    if len(invoices) > 1:
        box.addItem(tr("Несколько e-qaimə…"), SEVERAL, "")
    box.setText(typed)


def bank_accounts(session: Session) -> list[AccountInfo]:
    """Accounts money is in the bank on: by type, or by the bank account directory."""
    catalog = session.catalog
    return [
        a
        for a in catalog.leaf_accounts
        if a.account_type in BANK_TYPES
        or (
            a.account_type is None
            and any(catalog.kind_codes.get(k or 0) == "bank_account" for k in a.sc_kinds)
        )
    ]


def counterparty_kind(session: Session) -> int | None:
    return next(
        (k for k, code in session.catalog.kind_codes.items() if code == "counterparty"), None
    )


def fits(account: AccountInfo | None, value: SubcontoInfo) -> bool:
    """A bank account fits a GL account by currency: a USD account is not offered on a
    manat-only 51, a manat one not on a currency-only 52."""
    if account is None:
        return True
    if value.currency_id is None:
        return account.currency != CURRENCY_ONLY
    return account.currency != NO_CURRENCY


def select_data(box: PickBox, data, text: str = "") -> None:
    """Choose the item with this data; one no longer offered (hidden) is added."""
    i = box.findData(data)
    if i < 0 and data is not None:
        box.addItem(text or str(data), data)
        i = box.count() - 1
    box.setCurrentIndex(i)


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


class BankOperationPage(QWidget):
    saved = Signal(int)  # the GL document
    close_requested = Signal()
    title_changed = Signal()
    open_gl_document = Signal(int)
    copy_requested = Signal(object)  # BankOperationInput
    next_requested = Signal(object)  # BankOperationInput: the next one of the statement

    def __init__(
        self,
        session: Session,
        operation_id: int | None = None,
        prefill: BankOperationInput | None = None,
    ) -> None:
        super().__init__()
        self.setObjectName("page")
        self.s = session
        self.doc: BankOperation | None = None
        self.read_only = False
        self.dirty = False
        self._loading = False
        self._lines_edited = False  # by hand: a counterparty no longer suggests them
        self.counterparty: int | None = None
        self.open_invoices: list[OpenInvoice] = []  # of the counterparty, for the lines

        root = QVBoxLayout(self)
        root.setContentsMargins(40, 30, 40, 22)
        root.setSpacing(18)

        top = QHBoxLayout()
        self.number = QLabel()
        self.number.setObjectName("tertiary")
        self.number.setFont(fonts().heading)
        top.addWidget(self.number)
        self.memo = QLineEdit()
        self.memo.setObjectName("titleEdit")
        self.memo.setFont(fonts().title)
        top.addWidget(self.memo, 1)
        self.status = Chip()
        top.addWidget(self.status, 0, Qt.AlignmentFlag.AlignVCenter)
        top.addWidget(more_button(self.menu_items))
        root.addLayout(top)

        # Set before typing, the cursor does not go through them (Shift+Tab does): which
        # way, the bank account, the day, the kind of operation.
        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.direction = QButtonGroup(self)
        self.btn_in = button(tr("Приход"), "segment", tr("Деньги пришли на счёт"))
        self.btn_out = button(tr("Расход"), "segment", tr("Деньги ушли со счёта"))
        for b, direction in ((self.btn_out, OUT), (self.btn_in, IN)):
            b.setCheckable(True)
            b.setProperty("direction", direction)
            self.direction.addButton(b)
            bar.addWidget(b)
        bar.addSpacing(20)
        bar.addWidget(caption(tr("Банк")))
        self.places = bank_places(session.conn, session.company_id)
        self.bank = PickBox(NONE)  # the account, its bank and currency in one field
        for place in self.places:
            self.bank.addItem(place_label(place), place)
        self.bank.setFixedWidth(300)
        self.bank.unknown.connect(self._not_listed)
        bar.addWidget(self.bank)
        self.currency = PickBox()  # shown only where the account leaves it to choose
        self.currency.setFixedWidth(90)
        self.currency.unknown.connect(self._not_listed)
        bar.addWidget(self.currency)
        bar.addSpacing(12)
        bar.addWidget(caption(tr("Дата")))
        self.date = date_edit(session.working_date)
        self.date.setFixedWidth(130)
        bar.addWidget(self.date)
        bar.addSpacing(12)
        bar.addWidget(caption(tr("Вид")))
        self.kind = PickBox()
        for kind, name in KINDS:
            self.kind.addItem(tr(name), kind)
        self.kind.setCurrentIndex(0)
        self.kind.unknown.connect(self._not_listed)
        self.kind.setFixedWidth(200)
        bar.addWidget(self.kind)
        bar.addStretch(1)
        self.balance = caption("", "tertiary")
        bar.addWidget(self.balance)
        root.addLayout(bar)

        # What the bank field stands for: the GL account and its subconto (the bank
        # account directory), kept as before so the operation is saved the same way.
        held = QWidget(self)
        held.hide()
        kept = QVBoxLayout(held)
        self.account = PickBox(NONE)
        for a in bank_accounts(session):
            self.account.addItem(a.label, a.id)
        kept.addWidget(self.account)
        self.sc_captions: list[QLabel] = []
        self.sc: list[PickBox] = []
        for _ in range(3):
            box = PickBox(NONE)
            box.activated.connect(self._bank_subconto_changed)
            self.sc_captions.append(QLabel())
            self.sc.append(box)
            kept.addWidget(box)

        # No rate of the date: load the Central Bank's rates right from here.
        self.rate_note = QFrame()
        self.rate_note.setObjectName("note")
        note = QHBoxLayout(self.rate_note)
        note.setContentsMargins(14, 8, 8, 8)
        self.rate_text = QLabel()
        self.rate_text.setWordWrap(True)
        note.addWidget(self.rate_text, 1)
        self.btn_rates = button(tr("Загрузить курс ЦБА"), "flat", tr("Курсы с cbar.az на дату"))
        self.btn_rates.clicked.connect(self.load_rates)
        note.addWidget(self.btn_rates)
        self.rate_note.hide()
        root.addWidget(self.rate_note)

        rule = QFrame()
        rule.setObjectName("rule")
        rule.setFixedHeight(1)
        root.addWidget(rule)

        # The cursor's path: who, the e-qaimə, how much — and post.
        form = QGridLayout()
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(4)
        form.setColumnMinimumWidth(0, 110)
        form.setColumnStretch(2, 1)
        self.counterparty_caption = caption(tr("Контрагент"))
        self.counterparty_edit = PickBox(tr("Название или VÖEN"))
        self.counterparty_edit.setFixedWidth(FIELD_WIDTH)
        self.counterparty_edit.activated.connect(
            lambda _: self._choose_counterparty(self.counterparty_edit.currentData())
        )
        self.counterparty_edit.unknown.connect(self._add_counterparty)
        self.counterparty_edit.added.connect(lambda text: self._add_counterparty(text, True))
        self.counterparty_edit.can_add = True
        form.addWidget(self.counterparty_caption, 0, 0)
        form.addWidget(self.counterparty_edit, 0, 1)
        self.tax_id = caption("", "tertiary")
        form.addWidget(self.tax_id, 1, 1)
        form.setRowMinimumHeight(2, 8)
        # while the operation is one line, its e-qaimə and amount are typed up here
        self.invoice_caption = caption(tr("E-qaimə"))
        self.invoice = SuggestBox(tr("Номер e-qaimə"))
        self.invoice.setFixedWidth(FIELD_WIDTH)
        self.invoice.activated.connect(self._invoice_chosen)
        self.invoice.textEdited.connect(self._invoice_typed)
        form.addWidget(self.invoice_caption, 3, 0)
        form.addWidget(self.invoice, 3, 1)
        form.setRowMinimumHeight(4, 12)
        self.amount_caption = caption(tr("Сумма"))
        self.amount = QLineEdit()
        self.amount.setFont(fonts().total)
        self.amount.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.amount.setPlaceholderText("0.00")
        self.amount.setFixedWidth(200)
        self.amount.textEdited.connect(self._amount_typed)
        self.amount_currency = caption("")
        # a payment's ƏDV goes from (a receipt's to) the ƏDV deposit account (D65): its
        # own operation on that account, typed here with the bank part
        self.vat_caption = caption("")
        self.vat_amount = QLineEdit()
        self.vat_amount.setFont(fonts().total)
        self.vat_amount.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.vat_amount.setPlaceholderText("0.00")
        self.vat_amount.setFixedWidth(170)
        self.vat_amount.textEdited.connect(self._changed)
        self.vat_currency = caption("AZN")
        amount_row = QHBoxLayout()
        amount_row.setSpacing(10)
        amount_row.addWidget(self.amount)
        amount_row.addWidget(self.amount_currency)
        amount_row.addSpacing(26)
        amount_row.addWidget(self.vat_caption)
        amount_row.addWidget(self.vat_amount)
        amount_row.addWidget(self.vat_currency)
        amount_row.addStretch(1)
        form.addWidget(self.amount_caption, 5, 0)
        form.addLayout(amount_row, 5, 1, 1, 2)
        form.setRowMinimumHeight(6, 6)
        self.deposit_caption = caption(tr("Депозит ƏDV"))
        self.deposits = [p for p in self.places if p.account_type == "vat_deposit"]
        self.deposit = PickBox(NONE)
        for place in self.deposits:
            self.deposit.addItem(place_label(place), place)
        self.deposit.setCurrentIndex(0 if self.deposits else -1)
        self.deposit.setFixedWidth(300)
        self.deposit.unknown.connect(self._not_listed)
        self.deposit_date = date_edit(session.working_date)
        self.deposit_date.setFixedWidth(130)
        self.deposit_date.setToolTip(tr("Дата операции на депозитном счёте"))
        self._deposit_day_kept = True  # follows the date until changed by hand
        deposit_row = QHBoxLayout()
        deposit_row.setSpacing(10)
        deposit_row.addWidget(self.deposit)
        deposit_row.addWidget(self.deposit_date)
        deposit_row.addStretch(1)
        form.addWidget(self.deposit_caption, 7, 0)
        form.addLayout(deposit_row, 7, 1, 1, 2)
        self.check = caption("")  # how the amounts close the e-qaimə
        form.addWidget(self.check, 8, 1, 1, 2)
        root.addLayout(form)
        root.addSpacing(8)

        # Where the money goes: one line is shown folded (as last time for the
        # counterparty); several lines, a fee or «Развернуть» show the lines themselves.
        lines_head = QHBoxLayout()
        lines_head.setSpacing(6)
        lines_head.addWidget(caption(tr("Расшифровка платежа")))
        lines_head.addStretch(1)
        self.btn_add_line = button(
            tr("+ Строка"), "flat", tr("Ещё одна e-qaimə, договор или счёт") + " (Ins)"
        )
        self.btn_add_line.clicked.connect(lambda: self.add_line(focus=True))
        lines_head.addWidget(self.btn_add_line)
        self.btn_add_fee = button(tr("+ Комиссия банка"), "flat", "F6")
        self.btn_add_fee.clicked.connect(self.add_fee)
        lines_head.addWidget(self.btn_add_fee)
        self.btn_unfold = button(tr("Развернуть"), "flat", tr("Счёт, субконто и сумма строки"))
        self.btn_unfold.clicked.connect(self.unfold)
        lines_head.addWidget(self.btn_unfold)
        root.addLayout(lines_head)
        self._unfolded = False
        self.summary = QFrame()
        self.summary.setObjectName("summary")
        folded = QHBoxLayout(self.summary)
        folded.setContentsMargins(14, 10, 14, 10)
        self.summary_text = caption("")
        folded.addWidget(self.summary_text, 1)
        root.addWidget(self.summary)
        self.lines_header = QWidget()
        head = QHBoxLayout(self.lines_header)
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(8)
        head.addWidget(caption(tr("Счёт и субконто"), "columnCaption"), 1)
        for text, width in ((tr("E-qaimə"), 160), (tr("Сумма"), 130)):
            column = caption(text, "columnCaption")
            column.setFixedWidth(width)
            head.addWidget(column)
        column.setAlignment(Qt.AlignmentFlag.AlignRight)  # the amount, as the numbers
        head.addSpacing(40)
        root.addWidget(self.lines_header)
        self.line_rows: list[LineRow] = []
        self.lines_box = QVBoxLayout()
        self.lines_box.setSpacing(8)
        root.addLayout(self.lines_box)

        self.total_row = QWidget()
        total = QHBoxLayout(self.total_row)
        total.setContentsMargins(0, 0, 0, 0)
        total.addStretch(1)
        total.addWidget(caption(tr("Итого")))
        self.total = QLabel("0.00")
        self.total.setFont(fonts().total)
        total.addWidget(self.total)
        total.addSpacing(40)
        root.addWidget(self.total_row)

        self.error = QLabel()
        self.error.setObjectName("error")
        self.error.setWordWrap(True)
        self.error.hide()
        root.addWidget(self.error)
        root.addStretch(1)

        # off the cursor's path: the statement's reference (Tab after «Провести»)
        extra = QHBoxLayout()
        self.reference = QLineEdit()
        self.reference.setPlaceholderText(tr("Референс из банковской выписки, необязательно"))
        self.reference.setFixedWidth(FIELD_WIDTH)
        extra.addWidget(self.reference)
        extra.addStretch(1)
        root.addLayout(extra)

        actions = QHBoxLayout()
        self.keys_hint = caption(
            tr("Enter — дальше  ·  Ctrl+Enter — провести  ·  F6 — комиссия"), "tertiary"
        )
        actions.addWidget(self.keys_hint)
        self.btn_delete = button(tr("Удалить"), "danger")
        self.btn_unpost = button(tr("Отменить проведение"), "flat")
        self.btn_gl = button(tr("Открыть проводки"), "flat")
        actions.addWidget(self.btn_delete)
        actions.addWidget(self.btn_unpost)
        actions.addWidget(self.btn_gl)
        actions.addStretch(1)
        self.btn_save = button(tr("Сохранить черновик"), tooltip="Ctrl+S")
        self.btn_post = button(tr("Провести"), "primary", "Ctrl+Enter")
        self.btn_post.setMinimumWidth(130)
        actions.addWidget(self.btn_save)
        actions.addWidget(self.btn_post)
        root.addLayout(actions)

        self.btn_save.clicked.connect(lambda: self.save(post=False))
        self.btn_post.clicked.connect(lambda: self.save(post=True))
        self.btn_delete.clicked.connect(self.delete)
        self.btn_unpost.clicked.connect(self.unpost)
        self.btn_gl.clicked.connect(self._open_gl)
        for keys, fn in (
            ("Ctrl+S", lambda: self.save(post=self.posted)),
            ("Ctrl+Return", lambda: self.save(post=True)),
            ("Ctrl+Enter", lambda: self.save(post=True)),
            ("Ins", self._insert_line),
            ("F6", self._fee_key),
            ("F9", self._duplicate_line),
            ("Ctrl+Del", self._remove_current_line),
        ):
            shortcut = QShortcut(QKeySequence(keys), self)
            shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            shortcut.activated.connect(fn)
        self.direction.buttonClicked.connect(self._direction_changed)
        self.account.activated.connect(self._bank_account_changed)
        self.bank.activated.connect(self._bank_chosen)
        self.currency.activated.connect(self._changed)
        self.reference.textEdited.connect(self._changed)
        self.memo.textEdited.connect(self._changed)
        self.date.dateChanged.connect(self._changed)
        self.date.dateChanged.connect(self._refresh_invoices)
        self.date.dateChanged.connect(self._show_balance)
        self.date.dateChanged.connect(self._follow_date)
        self.deposit_date.dateChanged.connect(self._deposit_day_changed)
        self.kind.activated.connect(self._kind_changed)
        self._fill_counterparties()

        if operation_id is not None:
            self.load(operation_id)
        else:
            self._set_new(prefill)

    # ---- state -----------------------------------------------------------------------

    @property
    def key(self):
        return ("bank_op", self.doc.id) if self.doc else ("new_bank_op", id(self))

    @property
    def posted(self) -> bool:
        return self.doc is not None and self.doc.status == "posted"

    @property
    def direction_value(self) -> str:
        return IN if self.btn_in.isChecked() else OUT

    def title(self) -> str:
        if self.doc is None:
            title = tr("Новый приход") if self.direction_value == IN else tr("Новый расход")
        elif self.doc.direction == IN:
            title = tr("Приход №{n}", n=self.doc.number)
        else:
            title = tr("Расход №{n}", n=self.doc.number)
        return title + (" •" if self.dirty else "")

    def is_dirty(self) -> bool:
        return self.dirty

    def focus_table(self) -> None:
        """The cursor starts where typing starts: who, else how much."""
        if not self.counterparty_edit.isHidden() and self.counterparty is None:
            self.counterparty_edit.setFocus()
        elif self.line_rows:
            self._amount_of(self.line_rows[0]).setFocus()

    def _set_new(self, prefill: BankOperationInput | None) -> None:
        self._loading = True
        data = prefill or BankOperationInput(
            doc_date=self.s.working_date.isoformat(), direction=OUT, account_id=None
        )
        if prefill is None or (prefill.kind == OTHER and not prefill.lines):
            # the usual ones: paid to a supplier, received from a customer
            data = replace(data, kind=SUPPLIER if data.direction == OUT else CUSTOMER)
        if data.account_id is None:  # the first bank account
            accounts = bank_accounts(self.s)
            first = next((a for a in accounts if a.account_type == "bank"), None)
            if first is not None:
                data = replace(data, account_id=first.id)
        self._fill(data)
        if not self.line_rows:
            self.add_line()
            self._default_lines()
        self.number.setText("")
        self.status.set(tr("Новый"), "blue")
        self._loading = False
        self.dirty = prefill is not None and bool(prefill.lines)
        self._lines_edited = bool(prefill and prefill.lines)
        self._apply_mode()
        self._update()
        QTimer.singleShot(0, self.focus_table)

    def load(self, operation_id: int) -> None:
        self.doc = load_bank_operation(self.s.conn, self.s.company_id, operation_id)
        d = self.doc
        self._loading = True
        self._fill(d)
        self._loading = False
        self._lines_edited = True
        self.number.setText(f"№{d.number}")
        closed = load_document(self.s.conn, self.s.company_id, d.document_id).closed
        self.read_only = d.status == "posted" and closed
        if d.status == "draft":
            self.status.set(tr("Черновик"), "amber")
        else:
            self.status.set(tr("Проведён"), "green")
        self.dirty = False
        self._apply_mode()
        self._update()
        self.title_changed.emit()

    def _fill(self, d: BankOperationInput) -> None:
        (self.btn_in if d.direction == IN else self.btn_out).setChecked(True)
        self.date.setDate(to_qdate(date.fromisoformat(d.doc_date)))
        if d.account_id is not None:
            select_data(self.account, d.account_id, self.s.catalog.accounts[d.account_id].label)
        else:
            self.account.setCurrentIndex(-1)
        self._bank_account_changed(chosen=d.subconto)
        select_data(self.currency, d.currency_id)
        self.reference.setText(d.reference)
        select_data(self.kind, d.kind)
        self._set_counterparty(d.counterparty_id)
        for row in list(self.line_rows):
            self._remove_line(row)
        for line in d.lines:
            self.add_line().set_line(line)
        self.memo.setText(d.memo)
        self._kind_visibility()

    def _apply_mode(self) -> None:
        ro = self.read_only
        for w in (self.date, self.bank, self.account, self.kind, self.btn_in, self.btn_out):
            w.setEnabled(not ro)
        for box in self.sc:
            box.setEnabled(not ro)
        if ro:
            self.currency.setEnabled(False)
        self.counterparty_edit.setEnabled(not ro)
        for edit in (self.memo, self.reference, self.invoice, self.amount):
            edit.setReadOnly(ro)
        for row in self.line_rows:
            row.set_read_only(ro)
        self.btn_add_line.setVisible(not ro)
        self.btn_add_fee.setVisible(not ro)
        self.keys_hint.setVisible(not ro)
        self._layout_lines()
        self.btn_delete.setVisible(self.doc is not None and not ro)
        self.btn_unpost.setVisible(self.posted and not ro)
        self.btn_gl.setVisible(self.posted)
        self.btn_save.setVisible(not ro and not self.posted)  # Ctrl+S reposts it
        self.btn_post.setVisible(not ro)

    def menu_items(self) -> list[MenuItem]:
        if self.doc is None:
            return []
        return [(tr("Копировать"), self._copy)]

    def _copy(self) -> None:
        try:
            data = self.collect()
        except (LedgerError, ValueError) as e:
            self.show_error(str(e))
            return
        self.copy_requested.emit(self.copy_of(data))

    @staticmethod
    def copy_of(data: BankOperationInput) -> BankOperationInput:
        """A new operation like this one (a monthly rent): the statement reference and the
        e-qaimə belong to the original."""
        lines = tuple(replace(line, invoice="") for line in data.lines)
        return replace(data, reference="", lines=lines)

    # ---- the bank account ------------------------------------------------------------

    @property
    def bank_info(self) -> AccountInfo | None:
        account_id = self.account.currentData()
        return self.s.catalog.accounts.get(account_id) if account_id is not None else None

    def _bank_account_changed(self, *_, chosen: Sequence[int | None] = ()) -> None:
        account = self.bank_info
        kinds = account.sc_kinds if account else (None, None, None)
        chosen = [*chosen, None, None, None][:3]
        for caption, box, kind, value in zip(self.sc_captions, self.sc, kinds, chosen, strict=True):
            box.clear()
            shown = kind is not None
            caption.setVisible(shown)
            box.setVisible(shown)
            if kind is None:
                continue
            caption.setText(self.s.catalog.kinds[kind])
            values = [v for v in self.s.catalog.values(kind) if fits(account, v)]
            for v in values:
                box.addItem(v.name, v.id)
            if value is not None:
                select_data(box, value, self.s.catalog.value(value).name)
            elif len(values) == 1:  # the only one: chosen already
                box.setCurrentIndex(0)
        self._fit_currency()
        self._show_bank()
        self._kind_visibility()
        self._changed()

    def _bank_subconto_changed(self, *_) -> None:
        self._fit_currency()
        self._show_bank()
        self._changed()

    def _fit_currency(self) -> None:
        fit_currency(self.currency, self.s, self.bank_info, self.bank_subconto())
        self.currency.setVisible(self.currency.isEnabled())  # a currency left to choose

    def _bank_chosen(self, *_) -> None:
        """The one bank field: its GL account and the element of the bank directory."""
        place = self.bank.currentData()
        if not isinstance(place, BankPlace):
            return
        label = self.s.catalog.accounts[place.account_id].label
        select_data(self.account, place.account_id, label)
        self._bank_account_changed(chosen=self._place_subconto(place))

    def _show_bank(self) -> None:
        """The bank field shows the account and bank chosen, and its balance on the day."""
        account_id = self.account.currentData()
        values = {v for v in self.bank_subconto() if v is not None}
        found = next(
            (
                i
                for i, place in enumerate(self.places)
                if place.account_id == account_id
                and (place.value_id is None or place.value_id in values)
            ),
            -1,
        )
        if found < 0 and account_id is not None:  # not among the bank accounts any more
            self.bank.addItem(self.s.catalog.accounts[account_id].label, None)
            found = self.bank.count() - 1
        self.bank.setCurrentIndex(found)
        self._show_balance()

    def _show_balance(self, *_) -> None:
        place = self.bank.currentData()
        if not isinstance(place, BankPlace):
            self.balance.setText("")
            return
        day = edited_date(self.date).isoformat()
        amount = place_balance(self.s.conn, self.s.company_id, place, day)
        self.balance.setText(tr("остаток {amount}", amount=format_minor(amount)))

    def bank_subconto(self) -> tuple[int | None, ...]:
        return tuple(box.currentData() for box in self.sc)

    def currency_code(self) -> str:
        return self.currency.currentText()

    # ---- the operation and the counterparty ------------------------------------------

    def _kind_visibility(self) -> None:
        """A counterparty for payments to and from partners; the ƏDV deposit account
        offers only what it may pay (D41)."""
        kind = self.kind.currentData()
        shown = kind in WITH_COUNTERPARTY
        for w in (self.counterparty_caption, self.counterparty_edit, self.tax_id):
            w.setVisible(shown)
        deposit = self.bank_info is not None and self.bank_info.account_type == "vat_deposit"
        for i in range(self.kind.count()):
            allowed = not deposit or self.kind.itemData(i) in VAT_DEPOSIT_KINDS
            self.kind.setItemHidden(i, not allowed)
        self.memo.setPlaceholderText(self._default_memo())

    def _kind_changed(self, *_) -> None:
        kind = self.kind.currentData()
        if kind not in WITH_COUNTERPARTY:
            self._set_counterparty(None)
        self._kind_visibility()
        if not self._lines_edited:
            self._default_lines()
        self._changed()

    def _direction_changed(self, *_) -> None:
        if not self._lines_edited:
            if self.kind.currentData() in (SUPPLIER, CUSTOMER):  # who usually pays which way
                select_data(self.kind, SUPPLIER if self.direction_value == OUT else CUSTOMER)
            self._suggest()
        self._refresh_invoices()
        self._kind_visibility()
        self._changed()
        self.title_changed.emit()

    def _fill_counterparties(self) -> None:
        """Found by name or VÖEN; the field shows the name, the VÖEN is under it."""
        box = self.counterparty_edit
        box.clear()
        kind = counterparty_kind(self.s)
        for v in self.s.catalog.values(kind) if kind is not None else []:
            box.addItem(v.label, v.id, v.name)

    def _not_listed(self, text: str) -> None:
        self.show_error(tr("«{text}» нет в списке", text=text))

    def _new_value(
        self, listed: bool, kind: int, text: str, owner_id=None, currency_id=None
    ) -> int | None:
        """Picked as "+ Добавить «…»": added at once, as in the journal; typed with the
        list closed: the directory's window, to check the name first (D49, D54)."""
        add = added_value if listed else new_value
        return add(self.s, self, kind, text, owner_id=owner_id, currency_id=currency_id)

    def _add_counterparty(self, text: str, listed: bool = False) -> None:
        """A counterparty not yet in the directory: added right here (D49)."""
        kind = counterparty_kind(self.s)
        if kind is None or self.read_only:
            return
        value = self._new_value(listed, kind, text)
        if value is None:
            return
        self._fill_counterparties()
        self._choose_counterparty(value)
        self._focus_after(self.counterparty_edit, listed)

    def _add_bank_value(self, position: int, text: str, listed: bool = False) -> None:
        """A bank account not yet in the directory (a new bank): added right here."""
        account = self.bank_info
        kind = account.sc_kinds[position] if account else None
        if kind is None or self.read_only:
            return
        currency = self.currency.currentData() if account and account.currency else None
        value = self._new_value(listed, kind, text, currency_id=currency)
        if value is None:
            return
        chosen = list(self.bank_subconto())
        chosen[position] = value
        self._bank_account_changed(chosen=chosen)
        self._focus_after(self.sc[position], listed)

    def _add_line_value(self, row: LineRow, position: int, text: str, listed=False) -> None:
        """A contract (or any element of the line's account) added right here."""
        account = row.account_info
        kind = account.sc_kinds[position] if account else None
        if kind is None or self.read_only:
            return
        value = self._new_value(listed, kind, text, owner_id=row.owner_of(position))
        if value is None:
            return
        row.set_subconto(position, value)
        self._focus_after(row.sc[position], listed)

    def _focus_after(self, field: QWidget, listed: bool = False) -> None:
        """Back from a dialog: on to the field after the one just filled (picked from
        the list, the field goes on by itself)."""
        if listed:
            return
        field.setFocus()
        self.focusNextChild()

    def _choose_counterparty(self, value: int | None) -> None:
        if value == self.counterparty:
            self._show_counterparty()
            return
        self._set_counterparty(value)
        if value is not None and not self._lines_edited:
            self._suggest()
        self._kind_visibility()
        self._changed()

    def _set_counterparty(self, value: int | None) -> None:
        self.counterparty = value
        for row in self.line_rows:
            row.set_counterparty(value)
        self._show_counterparty()
        self._refresh_invoices()

    def _refresh_invoices(self, *_) -> None:
        """The unpaid e-qaimə of the counterparty on the day: owed to it when paying out,
        owed by it when money comes in."""
        if self.counterparty is None:
            self.open_invoices = []
        else:
            self.open_invoices = open_invoices(
                self.s.conn,
                self.s.company_id,
                self.counterparty,
                payable=self.direction_value == OUT,
                on_date=edited_date(self.date),
            )
        offer_invoices(self.invoice, self.open_invoices)
        for row in self.line_rows:
            row.set_invoices(self.open_invoices)

    def _pay_several(self, row: LineRow) -> None:
        """One payment over several e-qaimə: a line for each, the same account; the
        amount typed in the line is spread oldest first, what is left — an advance."""
        typed = row.amount.text().strip()
        try:
            total = to_minor(typed) if typed else None
        except ValueError:
            total = None
        picker = InvoicePicker(self.open_invoices, total, self)
        if picker.exec() != QDialog.DialogCode.Accepted:
            (self.invoice if self.folded else row.invoice).setFocus()
            return
        line = row.value() or BankLine(row.account.currentData(), 0, row.subconto())
        at = self.line_rows.index(row)
        parts = [*picker.chosen, *([("", picker.left)] if picker.left else [])]
        for n, (invoice, amount) in enumerate(parts):
            target = row if n == 0 else self.add_line(at=at + n)
            target.set_line(replace(line, amount=amount, invoice=invoice))
        self._lines_edited = True
        self._unfolded |= len(parts) > 1
        self._changed()
        self._amount_of(self.line_rows[at + len(parts) - 1]).setFocus()

    def _show_counterparty(self) -> None:
        value = self.counterparty
        info = self.s.catalog.value(value) if value is not None else None
        select_data(self.counterparty_edit, value, info.name if info else "")
        self.tax_id.setText(f"VÖEN {info.tax_id}" if info and info.tax_id else "")

    def _suggest(self) -> None:
        """Lines as last time for this counterparty (D47), else the kind's account."""
        if self.counterparty is None:
            self._default_lines()
            return
        found = last_lines(self.s.conn, self.s.company_id, self.direction_value, self.counterparty)
        if not found:
            self._default_lines()
            return
        amount = self.line_rows[0].amount.text() if self.line_rows else ""
        for row in list(self.line_rows):
            self._remove_line(row, changed=False)
        for line in found:
            self.add_line().set_line(line, amount=False)
        self.line_rows[0].amount.setText(amount)
        account = self.s.catalog.accounts.get(found[0].account_id or 0)
        if self.kind.currentData() == OTHER and account is not None:
            select_data(self.kind, TYPE_KINDS.get(account.account_type or "", OTHER))

    def _default_lines(self) -> None:
        """The first line takes the account of the kind: 60, 62, 68…, the bank fee, or
        another bank account in the same currency for a transfer."""
        if not self.line_rows:
            return
        row = self.line_rows[0]
        line = self._kind_line()
        if line is None:
            return
        row.set_line(line, amount=False)

    def _kind_line(self) -> BankLine | None:
        kind = self.kind.currentData()
        catalog = self.s.catalog
        if kind == FEE:
            account_id = self.s.ledger.account_role(self.s.company_id, BANK_FEE)
            return BankLine(account_id, 0, self._fee_subconto(account_id))
        if kind == TRANSFER:
            own = (self.account.currentData(), self.bank_subconto()[:1])
            currency = self.currency.currentData()
            for place in bank_places(self.s.conn, self.s.company_id):
                if (place.account_id, (place.value_id,)) != own and (place.currency_id == currency):
                    return BankLine(place.account_id, 0, place.subconto)
            return None
        account_type = KIND_TYPES.get(kind)
        if account_type is None:
            return None
        found = next((a for a in catalog.leaf_accounts if a.account_type == account_type), None)
        return BankLine(found.id, 0) if found else None

    def _fee_subconto(self, account_id: int | None) -> tuple[int | None, ...]:
        """The item «Комиссия банка» of the fee account (made on first use, as a
        conversion makes it)."""
        if account_id is None:
            return ()
        values = self.s.ledger.named_subconto(self.s.company_id, account_id, tr("Комиссия банка"))
        self.s.catalog.reload()
        return values

    def add_line(self, focus: bool = False, at: int | None = None) -> LineRow:
        row = LineRow(self.s)
        row.set_counterparty(self.counterparty)
        row.set_invoices(self.open_invoices)
        row.several.connect(lambda r: QTimer.singleShot(0, lambda: self._pay_several(r)))
        row.set_read_only(self.read_only)
        row.changed.connect(self._changed)
        row.edited.connect(self._line_edited)
        row.removed.connect(self._remove_line)
        row.unknown.connect(self._add_line_value)
        row.added.connect(lambda r, p, text: self._add_line_value(r, p, text, True))
        row.error.connect(self.show_error)
        at = len(self.line_rows) if at is None else at
        self.line_rows.insert(at, row)
        self.lines_box.insertWidget(at, row)
        self._chain()
        self._layout_lines()
        if focus:
            row.account.setFocus()
        return row

    def _insert_line(self) -> None:
        if not self.read_only:
            self._unfolded = True
            self.add_line(focus=True)

    def _current_line(self) -> LineRow | None:
        focused = QApplication.focusWidget()
        return next((r for r in self.line_rows if focused and r.isAncestorOf(focused)), None)

    def _duplicate_line(self) -> None:
        """F9: one more line like this one (another e-qaimə of the same supplier)."""
        row = self._current_line()
        if row is None or self.read_only or (line := row.value()) is None:
            return
        self._unfolded = True
        copy = self.add_line()
        copy.set_line(replace(line, invoice=""))
        (copy.amount if copy.invoice.isHidden() else copy.invoice).setFocus()
        self._changed()

    def _remove_current_line(self) -> None:
        """Ctrl+Del: the line the cursor is in; the cursor goes to the one above."""
        row = self._current_line()
        if row is None or self.read_only:
            return
        at = self.line_rows.index(row)
        self._remove_line(row)
        if self.line_rows:
            self.line_rows[max(at - 1, 0)].account.setFocus()

    def _chain(self) -> None:
        """Enter and Tab go in the order things are typed: who, the e-qaimə and amount (or
        the lines), «Провести»; the bank, day and kind before them (Shift+Tab), the
        statement reference and the purpose after (the lines are made later than the
        buttons below them, so Qt's own order would put them last)."""
        fields: list[QWidget] = [self.btn_out, self.btn_in, self.bank, self.currency, self.date]
        fields += [self.kind, self.counterparty_edit, self.invoice, self.amount, self.vat_amount]
        for row in self.line_rows:
            fields += [row.account, *row.sc, row.invoice, row.amount]
        fields += [self.btn_post, self.reference, self.deposit, self.deposit_date, self.memo]
        for first, second in pairwise(fields):
            QWidget.setTabOrder(first, second)

    def keyPressEvent(self, event) -> None:
        key, focused = event.key(), QApplication.focusWidget()
        # Enter a field did not want (it took what was typed): on to the next one
        enter = key in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not event.modifiers()
        if enter and focused is self.btn_post:
            self.btn_post.click()
            return
        if enter:
            self.focusNextChild()
            return
        # ← → on «Приход / Расход»: the other way
        if key in (Qt.Key.Key_Left, Qt.Key.Key_Right) and focused in (self.btn_in, self.btn_out):
            if not self.read_only:
                other = self.btn_in if self.btn_out.isChecked() else self.btn_out
                other.click()
                other.setFocus()
            return
        super().keyPressEvent(event)

    def add_fee(self) -> None:
        """A bank fee taken with the payment: a line on the fee account."""
        account_id = self.s.ledger.account_role(self.s.company_id, BANK_FEE)
        self._unfolded = True
        row = self.add_line()
        row.set_line(BankLine(account_id, 0, self._fee_subconto(account_id)), amount=False)
        row.amount.setFocus()
        self._changed()

    def _fee_key(self) -> None:
        if not self.read_only:
            self.add_fee()

    # ---- one line, folded --------------------------------------------------------------

    @property
    def folded(self) -> bool:
        """One line, as last time: its e-qaimə and amount are typed above, the line itself
        is one summary; several lines (or «Развернуть») are shown as they are."""
        return len(self.line_rows) == 1 and not self._unfolded

    def unfold(self) -> None:
        self._unfolded = True
        self._layout_lines()
        if self.line_rows:
            self.line_rows[0].account.setFocus()

    def _amount_of(self, row: LineRow) -> QLineEdit:
        return self.amount if self.folded and row is self.line_rows[0] else row.amount

    def _layout_lines(self) -> None:
        folded = self.folded
        for row in self.line_rows:
            row.setVisible(not folded)
        self.lines_header.setVisible(not folded and bool(self.line_rows))
        self.total_row.setVisible(not folded)
        self.summary.setVisible(folded)
        self.btn_unfold.setVisible(folded and not self.read_only)
        for w in (self.amount_caption, self.amount, self.amount_currency):
            w.setVisible(folded)
        deposit = self.deposit_shown
        for w in (self.vat_caption, self.vat_amount, self.vat_currency):
            w.setVisible(deposit)
        for w in (self.deposit_caption, self.deposit, self.deposit_date):
            w.setVisible(deposit)
        into = self.direction_value == IN
        if deposit:
            self.amount_caption.setText(tr("В банк") if into else tr("Из банка"))
            self.vat_caption.setText(tr("На депозит ƏDV") if into else tr("С депозита ƏDV"))
        else:
            self.amount_caption.setText(tr("Сумма"))
        self._show_check()
        row = self.line_rows[0] if folded else None
        takes = row is not None and not row.invoice.isHidden()  # its account takes e-qaimə
        self.invoice_caption.setVisible(takes)
        self.invoice.setVisible(takes)
        if row is None:
            return
        # the fields above show the line (set only when different: the cursor stays put)
        if self.invoice.text() != row.invoice.text():
            self.invoice.setText(row.invoice.text())
        if self.amount.text() != row.amount.text():
            self.amount.setText(row.amount.text())
        parts = [row.account.text() or tr("Счёт не выбран")]
        parts += [box.text() or box.placeholderText() for box in row.sc if not box.isHidden()]
        self.summary_text.setText("  ·  ".join(parts))

    def _invoice_chosen(self, index: int) -> None:
        """An e-qaimə from the list above: the line's, with what is left to pay on it."""
        if not self.line_rows:
            return
        row = self.line_rows[0]
        chosen = self.invoice.itemData(index) if index >= 0 else None
        if chosen == SEVERAL:
            QTimer.singleShot(0, lambda: self._pay_several(row))
            return
        i = row.invoice.findData(chosen) if chosen is not None else -1
        if i < 0:
            self._invoice_typed(self.invoice.text())
            return
        empty = not row.amount.text().strip() and not self.vat_amount.text().strip()
        if isinstance(chosen, OpenInvoice) and empty:
            if self.deposit_shown:  # the ƏDV from the deposit, the rest from the bank
                row.amount.setText(amount_text(chosen.amount - chosen.vat))
                self.vat_amount.setText(amount_text(chosen.vat) if chosen.vat else "")
            elif self._on_deposit():  # the deposit itself pays only the ƏDV
                row.amount.setText(amount_text(chosen.vat or chosen.amount))
        row.invoice.setCurrentIndex(i)
        row.invoice.activated.emit(i)

    def _invoice_typed(self, text: str) -> None:
        if self.line_rows:
            self.line_rows[0].invoice.setText(text)
            self.line_rows[0].changed.emit()

    def _amount_typed(self, text: str) -> None:
        if self.line_rows:
            self.line_rows[0].amount.setText(text)
            self.line_rows[0].changed.emit()

    # ---- the ƏDV deposit part ------------------------------------------------------------

    @property
    def deposit_shown(self) -> bool:
        """A new payment to a supplier (from a customer) on a current account, folded,
        with an ƏDV deposit account in the company: its ƏDV part is typed beside (D65)."""
        return (
            self.doc is None
            and not self.read_only
            and self.folded
            and bool(self.deposits)
            and self.kind.currentData() in (SUPPLIER, CUSTOMER)
            and not self._on_deposit()
        )

    def _on_deposit(self) -> bool:
        return self.bank_info is not None and self.bank_info.account_type == "vat_deposit"

    def _follow_date(self, *_) -> None:
        if self._deposit_day_kept:
            self.deposit_date.blockSignals(True)
            self.deposit_date.setDate(self.date.date())
            self.deposit_date.blockSignals(False)

    def _deposit_day_changed(self, *_) -> None:
        self._deposit_day_kept = self.deposit_date.date() == self.date.date()
        self._changed()

    def _show_check(self) -> None:
        """How the amounts typed close the e-qaimə chosen: in full, partly, or over."""
        row = self.line_rows[0] if self.folded else None
        number = row.invoice.text().strip().upper() if row is not None else ""
        chosen = next((i for i in self.open_invoices if i.invoice == number), None)
        if chosen is None or self.doc is not None:
            self.check.hide()
            return
        try:
            bank = to_minor(row.amount.text()) if row and row.amount.text().strip() else 0
            vat = to_minor(self.vat_amount.text()) if self.vat_amount.text().strip() else 0
        except ValueError:
            self.check.hide()
            return
        vat = vat if self.deposit_shown else 0
        paid = bank + vat
        parts = (
            tr(
                "банк {bank} + депозит {vat} = {total}",
                bank=format_minor(bank),
                vat=format_minor(vat),
                total=format_minor(paid),
            )
            if vat
            else ""
        )
        if paid == chosen.amount:
            text, tone = tr("✓ e-qaimə оплачивается полностью"), "success"
        elif paid < chosen.amount:
            left = format_minor(chosen.amount - paid)
            text, tone = tr("по e-qaimə останется {left}", left=left), "tertiary"
        else:
            over = format_minor(paid - chosen.amount)
            text, tone = tr("больше остатка по e-qaimə на {over}", over=over), "caution"
        self.check.setText(f"{parts}   ·   {text}" if parts else text)
        self.check.setObjectName(tone)
        self.check.style().unpolish(self.check)  # the new name's color
        self.check.style().polish(self.check)
        self.check.show()

    def _deposit_part(self, data: BankOperationInput) -> BankOperationInput | None:
        """The operation on the ƏDV deposit account, if its amount is typed: the same
        counterparty, line and e-qaimə, its own day."""
        text = self.vat_amount.text().strip()
        if not self.deposit_shown or not text or not data.lines:
            return None
        amount = to_minor(text)
        place = self.deposit.currentData()
        if amount == 0 or not isinstance(place, BankPlace):
            return None
        return replace(
            data,
            doc_date=edited_date(self.deposit_date).isoformat(),
            account_id=place.account_id,
            subconto=self._place_subconto(place),
            currency_id=None,
            reference="",
            lines=(replace(data.lines[0], amount=amount),),
        )

    def _place_subconto(self, place: BankPlace) -> tuple[int | None, ...]:
        """The element of the bank directory at its own position of the account."""
        chosen: list[int | None] = [None, None, None]
        account = self.s.catalog.accounts.get(place.account_id)
        if account is not None and place.value_id is not None:
            codes = [self.s.catalog.kind_codes.get(k or 0) for k in account.sc_kinds]
            if "bank_account" in codes:
                chosen[codes.index("bank_account")] = place.value_id
        return tuple(chosen)

    def _line_edited(self) -> None:
        if not self._loading:
            self._lines_edited = True

    def _remove_line(self, row: LineRow, changed: bool = True) -> None:
        self.line_rows.remove(row)
        self.lines_box.removeWidget(row)
        row.hide()  # out of the Enter / Tab order at once
        row.deleteLater()
        self._layout_lines()
        if changed:
            self._changed()

    def _default_memo(self) -> str:
        name = self.s.catalog.value(self.counterparty).name if self.counterparty else ""
        kind = self.kind.currentData() or OTHER
        return default_memo(self.direction_value, kind, name)

    # ---- input -----------------------------------------------------------------------

    def _changed(self, *_) -> None:
        if self._loading:
            return
        self.error.hide()
        self._update()
        if not self.dirty and not self.read_only:
            self.dirty = True
            self.title_changed.emit()

    def collect(self) -> BankOperationInput:
        lines = tuple(line for row in self.line_rows if (line := row.value()) is not None)
        return BankOperationInput(
            doc_date=edited_date(self.date).isoformat(),
            direction=self.direction_value,
            account_id=self.account.currentData(),
            lines=lines,
            kind=self.kind.currentData() or OTHER,
            subconto=self.bank_subconto(),
            currency_id=self.currency.currentData(),
            counterparty_id=None if self.counterparty_edit.isHidden() else self.counterparty,
            memo=self.memo.text().strip() or self._default_memo(),
            reference=self.reference.text().strip(),
        )

    def _update(self) -> None:
        total = 0
        for row in self.line_rows:
            text = row.amount.text().strip()
            with suppress(ValueError):  # a typo: counted once it is a number
                total += to_minor(text) if text else 0
        self.total.setText(f"{format_minor(total)} {self.currency_code()}")
        self.amount_currency.setText(self.currency_code())
        self._layout_lines()
        self._update_rate_note()

    def _update_rate_note(self) -> None:
        currency_id = self.currency.currentData()
        if self.read_only or self.posted or currency_id is None:
            self.rate_note.hide()
            return
        day = edited_date(self.date).isoformat()
        code = self.s.catalog.currencies[currency_id].code
        rate = rate_on(self.s.conn, self.s.company_id, currency_id, day)
        if rate is not None and rate.rate_date == day:
            self.rate_note.hide()
            return
        what = (
            tr("нет курса {code}", code=code)
            if rate is None
            else tr("курс {code} от {old}", code=code, old=ru_date(rate.rate_date))
        )
        self.rate_text.setText(
            tr("На {date} курс не загружен: {what}", date=ru_date(day), what=what)
        )
        self.rate_note.show()

    def load_rates(self) -> None:
        day = edited_date(self.date)
        QGuiApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            count = self.s.ledger.import_rates(self.s.company_id, day, self.s.fetch_rates(day))
        except LedgerError as e:
            self.show_error(str(e))
            return
        finally:
            QGuiApplication.restoreOverrideCursor()
        self._update()
        self.s.notify(
            tr("Курсы ЦБА на {date} загружены: {n}", date=ru_date(day.isoformat()), n=count)
        )

    # ---- actions ---------------------------------------------------------------------

    def show_error(self, message: str) -> None:
        self.error.setText(message)
        self.error.show()

    def save(self, post: bool) -> bool:
        if self.read_only:
            return False
        new = self.doc is None
        self.error.hide()
        try:
            data = self.collect()
            if self.doc is None:  # a new one: with its ƏDV part on the deposit, if typed
                deposit = self._deposit_part(data)
                saved = self.s.ledger.save_bank_payment(self.s.company_id, data, deposit, post=post)
            else:
                saved = [
                    self.s.ledger.save_bank_operation(
                        self.s.company_id, data, self.doc.id, post=post
                    )
                ]
        except (LedgerError, ValueError) as e:
            self.show_error(str(e))
            return False
        self.load(saved[0])
        assert self.doc is not None
        numbers = [self.doc.number]
        numbers += [
            load_bank_operation(self.s.conn, self.s.company_id, i).number for i in saved[1:]
        ]
        if len(numbers) == 2:
            first, second = numbers
            message = (
                tr("Операции №{a} и №{b} проведены", a=first, b=second)
                if post
                else tr("Черновики №{a} и №{b} сохранены", a=first, b=second)
            )
        elif post:
            message = tr("Операция №{n} проведена", n=self.doc.number)
        else:
            message = tr("Черновик №{n} сохранён", n=self.doc.number)
        self.s.notify(message)
        self.saved.emit(self.doc.document_id)
        if new and post:  # a statement is typed one operation after another
            self.next_requested.emit(self.next_of(data))
        return True

    @staticmethod
    def next_of(data: BankOperationInput) -> BankOperationInput:
        """The next operation of the statement: the same bank account, day and way."""
        return BankOperationInput(
            doc_date=data.doc_date,
            direction=data.direction,
            account_id=data.account_id,
            subconto=data.subconto,
            currency_id=data.currency_id,
        )

    def unpost(self) -> None:
        if self.doc is None:
            return
        try:
            self.s.ledger.unpost_bank_operation(self.s.company_id, self.doc.id)
        except LedgerError as e:
            self.show_error(str(e))
            return
        self.load(self.doc.id)
        self.saved.emit(self.doc.document_id)

    def delete(self) -> None:
        if self.doc is None:
            return
        question = tr("Удалить операцию №{n}?", n=self.doc.number)
        if QMessageBox.question(self, tr("Удалить"), question) != QMessageBox.StandardButton.Yes:
            return
        try:
            self.s.ledger.delete_bank_operation(self.s.company_id, self.doc.id)
        except LedgerError as e:
            self.show_error(str(e))
            return
        self.saved.emit(self.doc.document_id)
        self.dirty = False
        self.close_requested.emit()

    def _open_gl(self) -> None:
        if self.doc is not None:
            self.open_gl_document.emit(self.doc.document_id)
