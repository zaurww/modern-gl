"""Currency conversion (D37): two bank accounts side by side — what left one, what came to
the other — and under them the Central Bank's rate, the bank's rate and the difference."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from datetime import date
from fractions import Fraction
from itertools import pairwise

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from modern_gl.application.catalog import AccountInfo
from modern_gl.application.conversions import (
    Conversion,
    ConversionFee,
    ConversionInput,
    ConversionSide,
    bank_rate,
    calculate,
    load_conversion,
)
from modern_gl.application.currencies import rate_on
from modern_gl.application.ledger.conversion import MissingAccountRole
from modern_gl.application.queries import load_document
from modern_gl.desktop.pick import PickBox
from modern_gl.desktop.session import Session
from modern_gl.desktop.theme import P, fonts
from modern_gl.desktop.widgets import (
    Chip,
    MenuItem,
    button,
    date_edit,
    edited_date,
    enter_goes_on,
    more_button,
    ru_date,
    to_qdate,
)
from modern_gl.domain.accounts import BANK_FEE, FX_GAIN, FX_LOSS, FX_TRANSIT
from modern_gl.domain.currency import CURRENCY_OPTIONAL, format_unit_rate
from modern_gl.domain.errors import LedgerError
from modern_gl.domain.money import format_minor, to_minor
from modern_gl.i18n import tr

MONEY_TYPES = ("cash", "bank")
NONE = "—"
BASE = "AZN"  # the manat: amounts without a currency


def money_accounts(session: Session) -> list[AccountInfo]:
    """Where money is kept: cash and bank accounts (by type, or by the bank account
    directory); a chart without either offers every account."""
    catalog = session.catalog
    found = [
        a
        for a in catalog.leaf_accounts
        if a.account_type in MONEY_TYPES
        or any(catalog.kind_codes.get(k or 0) == "bank_account" for k in a.sc_kinds)
    ]
    return found or catalog.leaf_accounts


def amount_text(minor: int) -> str:
    return format_minor(minor) if minor else ""


def fit_currency(
    box: QComboBox | PickBox,
    session: Session,
    account: AccountInfo | None,
    subconto: Sequence[int | None],
    preferred: int | None = None,
) -> None:
    """The currency follows the account: a manat account is in manat, a USD bank
    account in USD; a currency account without one lets the user choose."""
    chosen = box.currentData() if preferred is None else preferred
    box.clear()
    if account is None or not account.currency:
        box.addItem(BASE, None)
        box.setCurrentIndex(0)
        box.setEnabled(False)
        return
    catalog = session.catalog
    fixed = next(
        (
            catalog.value(v).currency_id
            for v in subconto
            if v is not None and catalog.value(v).currency_id is not None
        ),
        None,
    )
    if fixed is not None:
        box.addItem(catalog.currencies[fixed].code, fixed)
        box.setCurrentIndex(0)
        box.setEnabled(False)
        return
    if account.currency == CURRENCY_OPTIONAL:
        box.addItem(BASE, None)
    for c in catalog.active_currencies:
        box.addItem(c.code, c.id)
    box.setEnabled(True)
    box.setCurrentIndex(max(box.findData(chosen), 0))


def money_places(session: Session) -> list[tuple[str, tuple[int, tuple[int | None, ...]]]]:
    """Where a fee can be taken from: every bank account (an element of the account's first
    directory: "Kapital Bank USD · 52") and every money account without one."""
    catalog = session.catalog
    places = []
    for account in money_accounts(session):
        kind = account.sc_kinds[0]
        if kind is None:
            places.append((account.label, (account.id, ())))
            continue
        places.extend(
            (f"{value.name}  ·  {account.short}", (account.id, (value.id,)))
            for value in catalog.values(kind)
        )
    return places


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


class ConversionAccountsDialog(QDialog):
    """The accounts conversions post to (account roles, D34)."""

    ROLES = (
        (FX_TRANSIT, "Переводы в пути"),
        (FX_GAIN, "Доход от курсовой разницы"),
        (FX_LOSS, "Убыток от курсовой разницы"),
        (BANK_FEE, "Комиссия банка"),
    )

    def __init__(self, session: Session, parent=None, missing: str | None = None) -> None:
        super().__init__(parent)
        self.s = session
        self.setWindowTitle(tr("Счета конвертации"))
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 16)
        lay.setSpacing(14)
        hint = QLabel(
            tr("Сюда конвертация относит деньги в пути, курсовую разницу и комиссию банка.")
        )
        hint.setObjectName("secondary")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        form = QFormLayout()
        form.setSpacing(10)
        self.boxes: dict[str, QComboBox] = {}
        for role, caption in self.ROLES:
            box = QComboBox()
            box.addItem(tr("— не указан —"), None)
            for account in session.catalog.leaf_accounts:
                box.addItem(account.label, account.id)
            current = session.ledger.account_role(session.company_id, role)
            box.setCurrentIndex(max(box.findData(current), 0))
            form.addRow(tr(caption), box)
            self.boxes[role] = box
        lay.addLayout(form)
        if missing in self.boxes:  # opened because this account is not chosen yet
            self.boxes[missing].setFocus()
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

    def accept(self) -> None:
        try:
            for role, box in self.boxes.items():
                self.s.ledger.set_account_role(self.s.company_id, role, box.currentData())
        except LedgerError as e:
            QMessageBox.warning(self, tr("Счета конвертации"), str(e))
            return
        super().accept()


class ConversionPage(QWidget):
    saved = Signal(int)  # the GL document
    close_requested = Signal()
    title_changed = Signal()
    open_gl_document = Signal(int)
    copy_requested = Signal(object)  # ConversionInput

    def __init__(
        self,
        session: Session,
        conversion_id: int | None = None,
        prefill: ConversionInput | None = None,
    ) -> None:
        super().__init__()
        self.setObjectName("page")
        self.s = session
        self.doc: Conversion | None = None
        self.read_only = False
        self.dirty = False
        self._loading = False

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
        self.memo.setPlaceholderText(tr("Конвертация валюты"))
        top.addWidget(self.memo, 1)
        self.status = Chip()
        top.addWidget(self.status, 0, Qt.AlignmentFlag.AlignVCenter)
        top.addWidget(more_button(self.menu_items))
        root.addLayout(top)

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

        sides = QHBoxLayout()
        sides.setSpacing(18)
        self.source = SidePanel(session, tr("Списано с"), credit=False)
        self.target = SidePanel(session, tr("Зачислено на"), credit=True)
        self.date = self.source.date
        self._last_date = self.date.date()
        arrow = QLabel("→")
        arrow.setObjectName("tertiary")
        arrow.setFont(fonts().title)
        sides.addWidget(self.source, 1)
        sides.addWidget(arrow, 0, Qt.AlignmentFlag.AlignVCenter)
        sides.addWidget(self.target, 1)
        root.addLayout(sides)

        # bank fees: any number, each from any money account in its own currency
        fees_head = QHBoxLayout()
        fees_caption = QLabel(tr("Комиссии банка"))
        fees_caption.setObjectName("secondary")
        fees_head.addWidget(fees_caption)
        self.btn_add_fee = button(tr("+ Комиссия"), "flat", tr("Комиссия, которую удержал банк"))
        self.btn_add_fee.clicked.connect(lambda: self.add_fee(focus=True))
        fees_head.addWidget(self.btn_add_fee)
        fees_head.addStretch(1)
        root.addLayout(fees_head)
        self.fee_rows: list[FeeRow] = []
        self.fees_box = QVBoxLayout()
        self.fees_box.setSpacing(8)
        root.addLayout(self.fees_box)

        summary = QFrame()
        summary.setObjectName("card")
        stats = QHBoxLayout(summary)
        stats.setContentsMargins(22, 16, 22, 16)
        stats.setSpacing(36)
        self.cbar = Stat(tr("Курс ЦБА"))
        self.bank = Stat(tr("Курс банка"))
        self.difference = Stat(tr("Курсовая разница"))
        self.fee_value = Stat(tr("Комиссии, {code}", code=BASE))
        for stat in (self.cbar, self.bank, self.difference, self.fee_value):
            stats.addWidget(stat)
        stats.addStretch(1)
        root.addWidget(summary)

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
            ("Ins", lambda: self.add_fee(focus=True)),
            ("Ctrl+Del", self._remove_current_fee),
        ):
            shortcut = QShortcut(QKeySequence(keys), self)
            shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            shortcut.activated.connect(fn)
        self.btn_add_fee.setToolTip(tr("Комиссия, которую удержал банк") + " (Ins)")
        for panel in (self.source, self.target):
            panel.changed.connect(self._changed)
        self.memo.textEdited.connect(self._changed)
        self.date.dateChanged.connect(self._date_changed)

        if conversion_id is not None:
            self.load(conversion_id)
        else:
            self._set_new(prefill)
        self._chain()

    # ---- state -----------------------------------------------------------------------

    @property
    def key(self):
        return ("conversion", self.doc.id) if self.doc else ("new_conversion", id(self))

    @property
    def posted(self) -> bool:
        return self.doc is not None and self.doc.status == "posted"

    def title(self) -> str:
        title = tr("Конвертация №{n}", n=self.doc.number) if self.doc else tr("Новая конвертация")
        return title + (" •" if self.dirty else "")

    def is_dirty(self) -> bool:
        return self.dirty

    def focus_table(self) -> None:
        self.source.amount.setFocus()

    def _set_new(self, prefill: ConversionInput | None) -> None:
        self._loading = True
        if prefill is not None:
            self._fill(prefill)
        else:
            # the usual case: currency sold from a currency account to a manat one
            accounts = money_accounts(self.s)
            banks = sorted(accounts, key=lambda a: a.account_type != "bank")  # cash last
            foreign = next((a for a in banks if a.currency), None)
            local = next((a for a in banks if not a.currency), None)
            for panel, account in ((self.source, foreign), (self.target, local)):
                if account is not None:
                    panel.account.setCurrentIndex(panel.account.findData(account.id))
                    panel._account_changed()
        self.number.setText("")
        self.status.set(tr("Новый"), "blue")
        self._loading = False
        self.dirty = prefill is not None
        self._apply_mode()
        self._update_summary()
        QTimer.singleShot(0, self.source.amount.setFocus)

    def load(self, conversion_id: int) -> None:
        self.doc = load_conversion(self.s.conn, self.s.company_id, conversion_id)
        d = self.doc
        self._loading = True
        self._fill(d)
        self._loading = False
        self.number.setText(f"№{d.number}")
        closed = load_document(self.s.conn, self.s.company_id, d.document_id).closed
        self.read_only = d.status == "posted" and closed
        if d.status == "draft":
            self.status.set(tr("Черновик"), "amber")
        else:
            self.status.set(tr("Проведён"), "green")
        self.dirty = False
        self._apply_mode()
        self._update_summary()
        self.title_changed.emit()

    def _fill(self, d: ConversionInput) -> None:
        self.memo.setText(d.memo)
        self.date.setDate(to_qdate(date.fromisoformat(d.doc_date)))
        self.source.set_value(d.source)
        self.target.set_value(d.target)
        self.target.date.setDate(to_qdate(date.fromisoformat(d.target_date or d.doc_date)))
        for row in list(self.fee_rows):
            self._remove_fee(row)
        for fee in d.fees:
            self.add_fee().set_value(fee)

    def _apply_mode(self) -> None:
        ro = self.read_only
        self.date.setEnabled(not ro)
        self.memo.setReadOnly(ro)
        self.btn_add_fee.setVisible(not ro)
        for row in self.fee_rows:
            row.set_read_only(ro)
        self.source.set_read_only(ro)
        self.target.set_read_only(ro)
        self.btn_delete.setVisible(self.doc is not None and not ro)
        self.btn_unpost.setVisible(self.posted and not ro)
        self.btn_gl.setVisible(self.posted)
        self.btn_save.setVisible(not ro and not self.posted)  # Ctrl+S reposts it
        self.btn_post.setVisible(not ro)

    def menu_items(self) -> list[MenuItem]:
        items: list[MenuItem] = [(tr("Счета конвертации…"), self.edit_accounts)]
        if self.doc is not None:
            items.append((tr("Копировать"), self._copy))
        return items

    def edit_accounts(self, missing: str | None = None) -> bool:
        dialog = ConversionAccountsDialog(self.s, self, missing)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return False
        self.error.hide()
        return True

    def _copy(self) -> None:
        try:
            data = self.collect()
        except (LedgerError, ValueError) as e:
            self.show_error(str(e))
            return
        self.copy_requested.emit(self.copy_of(data))

    @staticmethod
    def copy_of(data: ConversionInput) -> ConversionInput:
        """A new conversion like this one; the bank references belong to the original."""
        source, target = (
            None if side is None else replace(side, reference="")
            for side in (data.source, data.target)
        )
        return ConversionInput(
            data.doc_date,
            source,
            target,
            data.target_date,
            data.fees,
            data.memo,
        )

    def add_fee(self, focus: bool = False) -> FeeRow:
        """A new fee line; it is taken from the account sold from, until changed."""
        row = FeeRow(self.s)
        source = self.source.value()
        if source is not None:
            row.set_place(source.account_id, source.subconto)
        row.changed.connect(self._changed)
        row.removed.connect(self._remove_fee)
        self.fee_rows.append(row)
        self.fees_box.addWidget(row)
        self._chain()
        if focus and not self.read_only:
            row.amount.setFocus()
        return row

    def _remove_fee(self, row: FeeRow) -> None:
        self.fee_rows.remove(row)
        self.fees_box.removeWidget(row)
        row.hide()  # out of the Enter / Tab order at once
        row.deleteLater()
        self._changed()

    def _remove_current_fee(self) -> None:
        """Ctrl+Del: the fee the cursor is in goes; the cursor to the one above it."""
        focused = QApplication.focusWidget()
        row = next((r for r in self.fee_rows if focused and r.isAncestorOf(focused)), None)
        if row is None or self.read_only:
            return
        at = self.fee_rows.index(row)
        self._remove_fee(row)
        if self.fee_rows:
            self.fee_rows[max(at - 1, 0)].amount.setFocus()

    def _chain(self) -> None:
        """Enter and Tab go in the order things are typed: the title, the side sold from,
        the side bought to, then the fees (made later than the buttons below them, so
        Qt's own order would put them last)."""
        fields: list[QWidget] = [self.memo]
        for panel in (self.source, self.target):
            fields += [panel.account, *panel.sc, panel.currency, panel.amount]
            fields += [panel.date, panel.reference]
        for row in self.fee_rows:
            fields += [row.amount, row.currency, row.place, row.expense]
        fields.append(self.btn_post)
        for first, second in pairwise(fields):
            QWidget.setTabOrder(first, second)

    def keyPressEvent(self, event) -> None:
        """Enter goes on to the next field, as Tab does (as in the journal)."""
        if not enter_goes_on(self, event):
            super().keyPressEvent(event)

    def _changed(self, *_) -> None:
        if self._loading:
            return
        self.error.hide()
        self._update_summary()
        if not self.dirty and not self.read_only:
            self.dirty = True
            self.title_changed.emit()

    def _date_changed(self, *_) -> None:
        # the credit usually comes the same day: it follows until set apart
        day, credit = self.date.date(), self.target.date.date()
        if not self._loading and (credit == self._last_date or credit < day):
            self.target.date.setDate(day)
        self._last_date = day
        self._changed()

    # ---- input and summary -------------------------------------------------------------

    def collect(self) -> ConversionInput:
        doc_date = edited_date(self.date).isoformat()
        target_date = edited_date(self.target.date).isoformat()
        source, target = self.source.value(), self.target.value()
        memo = self.memo.text().strip()
        if not memo and source is not None and target is not None:
            memo = tr(
                "Конвертация {source} → {target}",
                source=self.source.code(),
                target=self.target.code(),
            )
        return ConversionInput(
            doc_date=doc_date,
            source=source,
            target=target,
            target_date=None if target_date == doc_date else target_date,
            fees=tuple(f for row in self.fee_rows if (f := row.value()) is not None),
            memo=memo,
        )

    def _update_summary(self) -> None:
        try:
            data = self.collect()
        except ValueError:
            for stat in (self.cbar, self.bank, self.difference, self.fee_value):
                stat.set(NONE)
            return
        base = BASE
        calc = calculate(self.s.conn, self.s.company_id, data)
        src, tgt = self.source.code(), self.target.code()
        # quoted as the bank does: the foreign currency (the source of a cross) per unit
        unit, quote = (tgt, src) if data.source and data.source.currency_id is None else (src, tgt)
        cbar = self._cbar_rate(data, calc.rates)
        self.cbar.set(f"1 {unit} = {format_unit_rate(cbar)} {quote}" if cbar else NONE)
        rate = bank_rate(data)
        self.bank.set(f"1 {unit} = {format_unit_rate(rate)} {quote}" if rate else NONE)
        diff = calc.difference
        if diff is None or calc.missing:
            self.difference.set(NONE)
        elif diff == 0:
            self.difference.set("0.00")
        elif diff > 0:
            self.difference.set(tr("{amount} убыток", amount=format_minor(diff)), P.red)
        else:
            self.difference.set(tr("{amount} доход", amount=format_minor(-diff)), P.green)
        self.fee_value.caption.setText(tr("Комиссии, {code}", code=base))
        self.fee_value.set(format_minor(calc.fee_total) if calc.fee_total else NONE)
        self._update_rate_note(data)

    def _cbar_rate(self, data: ConversionInput, rates) -> Fraction | None:
        if data.source is None or data.target is None:
            return None
        src, tgt = data.source.currency_id, data.target.currency_id
        per_unit = {c: r.per_unit for c, r in rates.items()}
        if src is None:
            return per_unit.get(tgt) if tgt is not None else None
        if src not in per_unit:
            return None
        if tgt is None:
            return per_unit[src]
        return per_unit[src] / per_unit[tgt] if tgt in per_unit else None

    def _update_rate_note(self, data: ConversionInput) -> None:
        """Currencies without a rate set for the date itself: offer the official ones."""
        if self.read_only or self.posted:
            self.rate_note.hide()
            return
        day = data.doc_date
        parts = []
        for side in (data.source, data.target):
            if side is None or side.currency_id is None:
                continue
            code = self.s.catalog.currencies[side.currency_id].code
            rate = rate_on(self.s.conn, self.s.company_id, side.currency_id, day)
            if rate is None:
                parts.append(tr("нет курса {code}", code=code))
            elif rate.rate_date < day:
                parts.append(tr("курс {code} от {old}", code=code, old=ru_date(rate.rate_date)))
        if not parts:
            self.rate_note.hide()
            return
        self.rate_text.setText(
            tr("На {date} курс не загружен: {what}", date=ru_date(day), what=", ".join(parts))
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
        self._update_summary()
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
            conversion_id = self.s.ledger.save_conversion(
                self.s.company_id, data, self.doc.id if self.doc else None, post=post
            )
        except MissingAccountRole as e:
            # a chart without the accounts: choose them now and post again
            chosen = self.edit_accounts(missing=e.role)
            if chosen and self.s.ledger.account_role(self.s.company_id, e.role) is not None:
                return self.save(post)
            self.show_error(str(e))
            return False
        except (LedgerError, ValueError) as e:
            self.show_error(str(e))
            return False
        self.s.catalog.reload()  # items of the difference and the fee may be new
        self.load(conversion_id)
        assert self.doc is not None
        self.s.notify(
            tr("Конвертация №{n} проведена", n=self.doc.number)
            if post
            else tr("Черновик №{n} сохранён", n=self.doc.number)
        )
        self.saved.emit(self.doc.document_id)
        return True

    def unpost(self) -> None:
        if self.doc is None:
            return
        try:
            self.s.ledger.unpost_conversion(self.s.company_id, self.doc.id)
        except LedgerError as e:
            self.show_error(str(e))
            return
        self.load(self.doc.id)
        self.saved.emit(self.doc.document_id)

    def delete(self) -> None:
        if self.doc is None:
            return
        question = tr("Удалить конвертацию №{n}?", n=self.doc.number)
        if QMessageBox.question(self, tr("Удалить"), question) != QMessageBox.StandardButton.Yes:
            return
        try:
            self.s.ledger.delete_conversion(self.s.company_id, self.doc.id)
        except LedgerError as e:
            self.show_error(str(e))
            return
        self.saved.emit(self.doc.document_id)
        self.dirty = False
        self.close_requested.emit()

    def _open_gl(self) -> None:
        if self.doc is not None:
            self.open_gl_document.emit(self.doc.document_id)
