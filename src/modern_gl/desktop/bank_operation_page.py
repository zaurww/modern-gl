"""A bank operation (D47): money in or out of one bank account. Above — which way, the
date, the bank account and who the money is from or to; below — lines: what it paid (an
account, a contract, an e-qaimə) and how much."""

from __future__ import annotations

from collections.abc import Sequence
from contextlib import suppress
from dataclasses import replace
from datetime import date
from typing import cast

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QCompleter,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListView,
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
    bank_places,
    default_memo,
    last_lines,
    load_bank_operation,
)
from modern_gl.application.catalog import AccountInfo, SubcontoInfo
from modern_gl.application.currencies import rate_on
from modern_gl.application.queries import load_document
from modern_gl.desktop.conversion_page import amount_text, fit_currency
from modern_gl.desktop.postings import attach_list
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

NONE = "—"
# the line's account suggests the kind of a counterparty's operation
TYPE_KINDS = {
    "payable": SUPPLIER,
    "advance_paid": SUPPLIER,
    "receivable": CUSTOMER,
    "advance_received": CUSTOMER,
}
WITH_COUNTERPARTY = (SUPPLIER, CUSTOMER, OTHER)


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


def select_data(box: QComboBox, data, text: str = "") -> None:
    """Choose the item with this data; one no longer offered (hidden) is added."""
    i = box.findData(data)
    if i < 0 and data is not None:
        box.addItem(text or str(data), data)
        i = box.count() - 1
    box.setCurrentIndex(max(i, 0))


class LineRow(QWidget):
    """One line: the account, its subconto (the counterparty of the operation fills its
    own position), the e-qaimə and the amount."""

    changed = Signal()
    edited = Signal()  # the account or subconto changed by hand: no more suggestions
    removed = Signal(object)

    def __init__(self, session: Session) -> None:
        super().__init__()
        self.s = session
        self.counterparty: int | None = None
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        self.account = QComboBox()
        self.account.addItem(tr("Счёт…"), None)
        for a in session.catalog.leaf_accounts:
            self.account.addItem(a.label, a.id)
        self.account.setMinimumWidth(200)
        lay.addWidget(self.account, 3)
        self.sc: list[QComboBox] = []
        for _ in range(3):
            box = QComboBox()
            box.setMinimumWidth(120)
            box.activated.connect(self._subconto_edited)
            self.sc.append(box)
            lay.addWidget(box, 2)
        self.invoice = QLineEdit()
        self.invoice.setPlaceholderText(tr("E-qaimə"))
        self.invoice.setFixedWidth(140)
        lay.addWidget(self.invoice)
        self.amount = QLineEdit()
        self.amount.setFixedWidth(130)
        self.amount.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.amount.setPlaceholderText("0.00")
        lay.addWidget(self.amount)
        self.remove = button("×", "flat", tr("Убрать строку"))
        self.remove.setFixedWidth(32)
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
            box.addItem(catalog.kinds[kind] + "…", None)
            for v in catalog.values(kind, owner):
                box.addItem(v.label, v.id)
            if value is not None:
                select_data(box, value, catalog.value(value).name)
            elif box.count() == 2:  # the only element: chosen already
                box.setCurrentIndex(1)
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
            self.account.setCurrentIndex(0)
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

        # which way the money goes, and the day
        bar = QHBoxLayout()
        bar.setSpacing(6)
        self.direction = QButtonGroup(self)
        self.btn_in = button(tr("Приход"), "segment", tr("Деньги пришли на счёт"))
        self.btn_out = button(tr("Расход"), "segment", tr("Деньги ушли со счёта"))
        for b, direction in ((self.btn_out, OUT), (self.btn_in, IN)):
            b.setCheckable(True)
            b.setProperty("direction", direction)
            self.direction.addButton(b)
            bar.addWidget(b)
        bar.addStretch(1)
        caption = QLabel(tr("Дата"))
        caption.setObjectName("secondary")
        bar.addWidget(caption)
        self.date = date_edit(session.working_date)
        self.date.setFixedWidth(130)
        bar.addWidget(self.date)
        root.addLayout(bar)

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

        cards = QHBoxLayout()
        cards.setSpacing(18)
        bank_card, bank = self._card(tr("Банковский счёт"))
        self.account = QComboBox()
        self.account.addItem(NONE, None)
        for a in bank_accounts(session):
            self.account.addItem(a.label, a.id)
        self._row(bank, tr("Счёт"), self.account)
        self.sc_captions: list[QLabel] = []
        self.sc: list[QComboBox] = []
        for _ in range(3):
            caption = QLabel()
            caption.setObjectName("secondary")
            box = QComboBox()
            box.activated.connect(self._bank_subconto_changed)
            self.sc_captions.append(caption)
            self.sc.append(box)
            self._row(bank, caption, box)
        self.currency = QComboBox()
        self._row(bank, tr("Валюта"), self.currency)
        self.reference = QLineEdit()
        self.reference.setPlaceholderText(tr("из банковской выписки, необязательно"))
        self._row(bank, tr("Референс"), self.reference)
        cards.addWidget(bank_card, 1)

        whom_card, whom = self._card(tr("Операция"))
        self.kind = QComboBox()
        for kind, name in KINDS:
            self.kind.addItem(tr(name), kind)
        self._row(whom, tr("Вид"), self.kind)
        self.counterparty_caption = QLabel(tr("Контрагент"))
        self.counterparty_caption.setObjectName("secondary")
        self.counterparty_edit = QLineEdit()
        self.counterparty_edit.setPlaceholderText(tr("Название или VÖEN"))
        self._row(whom, self.counterparty_caption, self.counterparty_edit)
        self.tax_id = QLabel()
        self.tax_id.setObjectName("secondary")
        self._row(whom, "", self.tax_id)
        cards.addWidget(whom_card, 1)
        root.addLayout(cards)

        lines_head = QHBoxLayout()
        lines_caption = QLabel(tr("Расшифровка платежа"))
        lines_caption.setObjectName("secondary")
        lines_head.addWidget(lines_caption)
        self.btn_add_line = button(tr("+ Строка"), "flat", tr("Ещё одна e-qaimə, договор или счёт"))
        self.btn_add_line.clicked.connect(lambda: self.add_line(focus=True))
        lines_head.addWidget(self.btn_add_line)
        self.btn_add_fee = button(tr("+ Комиссия банка"), "flat")
        self.btn_add_fee.clicked.connect(self.add_fee)
        lines_head.addWidget(self.btn_add_fee)
        lines_head.addStretch(1)
        root.addLayout(lines_head)
        self.line_rows: list[LineRow] = []
        self.lines_box = QVBoxLayout()
        self.lines_box.setSpacing(8)
        root.addLayout(self.lines_box)

        total = QHBoxLayout()
        total.addStretch(1)
        total_caption = QLabel(tr("Итого"))
        total_caption.setObjectName("secondary")
        total.addWidget(total_caption)
        self.total = QLabel("0.00")
        self.total.setFont(fonts().total)
        total.addWidget(self.total)
        total.addSpacing(40)
        root.addLayout(total)

        self.error = QLabel()
        self.error.setObjectName("error")
        self.error.setWordWrap(True)
        self.error.hide()
        root.addWidget(self.error)
        root.addStretch(1)

        actions = QHBoxLayout()
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
        ):
            QShortcut(QKeySequence(keys), self).activated.connect(fn)
        self.direction.buttonClicked.connect(self._direction_changed)
        self.account.activated.connect(self._bank_account_changed)
        self.currency.activated.connect(self._changed)
        self.reference.textEdited.connect(self._changed)
        self.memo.textEdited.connect(self._changed)
        self.date.dateChanged.connect(self._changed)
        self.kind.activated.connect(self._kind_changed)
        self._counterparty_labels: dict[str, int] = {}
        kind = counterparty_kind(session)
        if kind is not None:
            self._counterparty_labels = {v.label: v.id for v in session.catalog.values(kind)}
        attach_list(  # the list shows up as the name or VÖEN is typed
            self.counterparty_edit,
            list(self._counterparty_labels),
            False,
            lambda _editor, text: self._counterparty_chosen(text),
        )
        self.counterparty_edit.editingFinished.connect(self._counterparty_typed)
        # the list looks at the text once the page is built: a loaded counterparty is not
        # being typed, so its list does not open
        completer = self.counterparty_edit.findChild(QCompleter)
        popup = completer.popup() if completer is not None else None
        if popup is not None:
            QTimer.singleShot(0, popup.hide)

        if operation_id is not None:
            self.load(operation_id)
        else:
            self._set_new(prefill)

    # ---- layout helpers --------------------------------------------------------------

    @staticmethod
    def _card(title: str) -> tuple[QFrame, QGridLayout]:
        card = QFrame()
        card.setObjectName("card")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(22, 18, 22, 20)
        lay.setSpacing(12)
        heading = QLabel(title)
        heading.setFont(fonts().heading)
        lay.addWidget(heading)
        form = QGridLayout()
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(10)
        form.setColumnStretch(1, 1)
        lay.addLayout(form)
        lay.addStretch(1)
        return card, form

    @staticmethod
    def _row(form: QGridLayout, caption: str | QLabel, widget: QWidget) -> None:
        if isinstance(caption, str):
            caption = QLabel(caption)
            caption.setObjectName("secondary")
        row = form.rowCount()
        form.addWidget(caption, row, 0)
        form.addWidget(widget, row, 1)

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
        if not self.counterparty_edit.isHidden() and self.counterparty is None:
            self.counterparty_edit.setFocus()
        elif self.line_rows:
            self.line_rows[0].amount.setFocus()

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
            self.account.setCurrentIndex(0)
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
        for w in (self.date, self.account, self.kind, self.btn_in, self.btn_out, *self.sc):
            w.setEnabled(not ro)
        if ro:
            self.currency.setEnabled(False)
        for edit in (self.memo, self.reference, self.counterparty_edit):
            edit.setReadOnly(ro)
        for row in self.line_rows:
            row.set_read_only(ro)
        self.btn_add_line.setVisible(not ro)
        self.btn_add_fee.setVisible(not ro)
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
            if len(values) != 1:
                box.addItem(NONE, None)
            for v in values:
                box.addItem(v.name, v.id)
            if value is not None:
                select_data(box, value, self.s.catalog.value(value).name)
        self._fit_currency()
        self._kind_visibility()
        self._changed()

    def _bank_subconto_changed(self, *_) -> None:
        self._fit_currency()
        self._changed()

    def _fit_currency(self) -> None:
        fit_currency(self.currency, self.s, self.bank_info, self.bank_subconto())

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
        view = cast(QListView, self.kind.view())
        for i in range(self.kind.count()):
            allowed = not deposit or self.kind.itemData(i) in VAT_DEPOSIT_KINDS
            view.setRowHidden(i, not allowed)
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
        self._kind_visibility()
        self._changed()
        self.title_changed.emit()

    def _counterparty_chosen(self, text: str) -> None:
        value = self._counterparty_labels.get(text)
        if value is not None:
            self._choose_counterparty(value)

    def _counterparty_typed(self) -> None:
        """Typed without picking from the list: the name or VÖEN, if it is one element."""
        text = self.counterparty_edit.text().strip()
        if not text:
            self._choose_counterparty(None)
            return
        if text in self._counterparty_labels:
            self._choose_counterparty(self._counterparty_labels[text])
            return
        current = self.counterparty
        if current is not None and text == self.s.catalog.value(current).name:
            return  # shown as chosen (two branches may share the name)
        kind = counterparty_kind(self.s)
        try:
            found = self.s.catalog.resolve_value(kind, text) if kind is not None else None
        except LookupError as e:
            self.show_error(str(e))
            return
        if found is None:
            self.show_error(tr("контрагент «{text}» не найден", text=text))
            return
        self._choose_counterparty(found)

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

    def _show_counterparty(self) -> None:
        value = self.counterparty
        info = self.s.catalog.value(value) if value is not None else None
        self.counterparty_edit.setText(info.name if info else "")
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

    def add_line(self, focus: bool = False) -> LineRow:
        row = LineRow(self.s)
        row.set_counterparty(self.counterparty)
        row.changed.connect(self._changed)
        row.edited.connect(self._line_edited)
        row.removed.connect(self._remove_line)
        self.line_rows.append(row)
        self.lines_box.addWidget(row)
        if focus:
            row.account.setFocus()
        return row

    def add_fee(self) -> None:
        """A bank fee taken with the payment: a line on the fee account."""
        account_id = self.s.ledger.account_role(self.s.company_id, BANK_FEE)
        row = self.add_line()
        row.set_line(BankLine(account_id, 0, self._fee_subconto(account_id)), amount=False)
        row.amount.setFocus()
        self._changed()

    def _line_edited(self) -> None:
        if not self._loading:
            self._lines_edited = True

    def _remove_line(self, row: LineRow, changed: bool = True) -> None:
        self.line_rows.remove(row)
        self.lines_box.removeWidget(row)
        row.deleteLater()
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
        self.error.hide()
        try:
            data = self.collect()
            operation_id = self.s.ledger.save_bank_operation(
                self.s.company_id, data, self.doc.id if self.doc else None, post=post
            )
        except (LedgerError, ValueError) as e:
            self.show_error(str(e))
            return False
        self.load(operation_id)
        assert self.doc is not None
        self.s.notify(
            tr("Операция №{n} проведена", n=self.doc.number)
            if post
            else tr("Черновик №{n} сохранён", n=self.doc.number)
        )
        self.saved.emit(self.doc.document_id)
        return True

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
