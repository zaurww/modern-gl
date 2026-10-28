"""The bank operation's form: its fields and the page's state, and what every part of the
page asks of them (the bank account chosen, folded or not, the ƏDV deposit part shown).
The parts that act on the fields are groups in their own modules, put together by the page."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from modern_gl.application.bank import (
    CUSTOMER,
    IN,
    KINDS,
    OUT,
    SUPPLIER,
    BankOperation,
    BankPlace,
)
from modern_gl.application.catalog import AccountInfo
from modern_gl.application.invoices import OpenInvoice
from modern_gl.application.posting_preview import PostingPreview
from modern_gl.desktop.bank_operation_page.common import (
    FIELD_WIDTH,
    NONE,
    bank_accounts,
    caption,
)
from modern_gl.desktop.bank_operation_page.line_row import LineRow
from modern_gl.desktop.directories_page import added_value, new_value
from modern_gl.desktop.page import PageWidget
from modern_gl.desktop.pick import PickBox, SuggestBox
from modern_gl.desktop.posting_preview import PostingsPanel
from modern_gl.desktop.rate_note import rate_note
from modern_gl.desktop.session import Session
from modern_gl.desktop.theme import fonts
from modern_gl.desktop.widgets import Chip, MenuItem, button, date_edit, more_button
from modern_gl.i18n import tr


class BankOperationForm(PageWidget):
    saved = Signal(int)  # the GL document
    close_requested = Signal()
    title_changed = Signal()
    open_gl_document = Signal(int)
    copy_requested = Signal(object)  # BankOperationInput
    next_requested = Signal(object)  # BankOperationInput: the next one of the statement
    draft_requested = Signal(int)  # the next operation of the bank account to check

    def __init__(self, session: Session) -> None:
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
        self._build_head(root)
        self._build_bar(root)
        self._build_held()
        self._build_rate_note(root)
        rule = QFrame()
        rule.setObjectName("rule")
        rule.setFixedHeight(1)
        root.addWidget(rule)
        self._build_path(root)
        root.addSpacing(8)
        self._build_lines(root)
        self.error = QLabel()
        self.error.setObjectName("error")
        self.error.setWordWrap(True)
        self.error.hide()
        root.addWidget(self.error)
        self.postings = PostingsPanel(session, self.postings_preview)
        root.addWidget(self.postings)
        root.addStretch(1)
        self._build_footer(root)

    # ---- the fields ------------------------------------------------------------------

    def _build_head(self, root: QVBoxLayout) -> None:
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

    def _build_bar(self, root: QVBoxLayout) -> None:
        """Set before typing, the cursor does not go through them (Shift+Tab does): which
        way, the bank account, the day, the kind of operation."""
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
        self.places: list[BankPlace] = []  # _fill_banks
        self.bank = PickBox(NONE)  # the account, its bank and currency in one field
        self.bank.setFixedWidth(300)
        self.bank.can_add = True  # a new bank: added right here (D49)
        bar.addWidget(self.bank)
        self.currency = PickBox()  # shown only where the account leaves it to choose
        self.currency.setFixedWidth(90)
        bar.addWidget(self.currency)
        bar.addSpacing(12)
        bar.addWidget(caption(tr("Дата")))
        self.date = date_edit(self.s.working_date)
        self.date.setFixedWidth(130)
        bar.addWidget(self.date)
        bar.addSpacing(12)
        bar.addWidget(caption(tr("Вид")))
        self.kind = PickBox()
        for kind, name in KINDS:
            self.kind.addItem(tr(name), kind)
        self.kind.setCurrentIndex(0)
        self.kind.setFixedWidth(200)
        bar.addWidget(self.kind)
        bar.addStretch(1)
        self.balance = caption("", "tertiary")
        bar.addWidget(self.balance)
        root.addLayout(bar)

    def _build_held(self) -> None:
        """What the bank field stands for: the GL account and its subconto (the bank
        account directory), kept as before so the operation is saved the same way."""
        held = QWidget(self)
        held.hide()
        kept = QVBoxLayout(held)
        self.account = PickBox(NONE)
        for a in bank_accounts(self.s):
            self.account.addItem(a.label, a.id)
        kept.addWidget(self.account)
        self.sc_captions: list[QLabel] = []
        self.sc: list[PickBox] = []
        for _ in range(3):
            box = PickBox(NONE)
            self.sc_captions.append(QLabel(held))  # not a window of its own when shown
            self.sc.append(box)
            kept.addWidget(box)

    def _build_rate_note(self, root: QVBoxLayout) -> None:
        """No rate of the date: load the Central Bank's rates right from here."""
        self.rate_note, self.rate_text, self.btn_rates = rate_note(tr("Курсы с cbar.az на дату"))
        root.addWidget(self.rate_note)

    def _build_path(self, root: QVBoxLayout) -> None:
        """The cursor's path: who, the e-qaimə, how much — and post."""
        form = QGridLayout()
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(4)
        form.setColumnMinimumWidth(0, 110)
        form.setColumnStretch(2, 1)
        self.counterparty_caption = caption(tr("Контрагент"))
        self.counterparty_edit = PickBox(tr("Название или VÖEN"))
        self.counterparty_edit.setFixedWidth(FIELD_WIDTH)
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
        form.addWidget(self.invoice_caption, 3, 0)
        form.addWidget(self.invoice, 3, 1)
        form.setRowMinimumHeight(4, 12)
        self.amount_caption = caption(tr("Сумма"))
        form.addWidget(self.amount_caption, 5, 0)
        form.addLayout(self._amount_row(), 5, 1, 1, 2)
        form.setRowMinimumHeight(6, 6)
        self.deposit_caption = caption(tr("Депозит ƏDV"))
        self.deposits: list[BankPlace] = []  # _fill_banks
        self.deposit = PickBox(NONE)
        self.deposit.setFixedWidth(300)
        self.deposit_date = date_edit(self.s.working_date)
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

    def _amount_row(self) -> QHBoxLayout:
        self.amount = QLineEdit()
        self.amount.setFont(fonts().total)
        self.amount.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.amount.setPlaceholderText("0.00")
        self.amount.setFixedWidth(200)
        self.amount_currency = caption("")
        # a payment's ƏDV goes from (a receipt's to) the ƏDV deposit account (D69): its
        # own operation on that account, typed here with the bank part
        self.vat_caption = caption("")
        self.vat_amount = QLineEdit()
        self.vat_amount.setFont(fonts().total)
        self.vat_amount.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.vat_amount.setPlaceholderText("0.00")
        self.vat_amount.setFixedWidth(170)
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
        return amount_row

    def _build_lines(self, root: QVBoxLayout) -> None:
        """Where the money goes: one line is shown folded (as last time for the
        counterparty); several lines, a fee or «Развернуть» show the lines themselves."""
        lines_head = QHBoxLayout()
        lines_head.setSpacing(6)
        lines_head.addWidget(caption(tr("Расшифровка платежа")))
        lines_head.addStretch(1)
        self.btn_add_line = button(
            tr("+ Строка"), "flat", tr("Ещё одна e-qaimə, договор или счёт") + " (Ins)"
        )
        lines_head.addWidget(self.btn_add_line)
        self.btn_unfold = button(tr("Развернуть"), "flat", tr("Счёт, субконто и сумма строки"))
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

    def _build_footer(self, root: QVBoxLayout) -> None:
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

    # ---- what the parts ask of the fields --------------------------------------------

    def postings_preview(self) -> PostingPreview:
        """What the operation posts (the page answers)."""
        raise NotImplementedError

    @property
    def posted(self) -> bool:
        return self.doc is not None and self.doc.status == "posted"

    @property
    def direction_value(self) -> str:
        return IN if self.btn_in.isChecked() else OUT

    @property
    def bank_info(self) -> AccountInfo | None:
        account_id = self.account.currentData()
        return self.s.catalog.accounts.get(account_id) if account_id is not None else None

    def bank_subconto(self) -> tuple[int | None, ...]:
        return tuple(box.currentData() for box in self.sc)

    def currency_code(self) -> str:
        return self.currency.currentText()

    def _place_subconto(self, place: BankPlace) -> tuple[int | None, ...]:
        """The element of the bank directory at its own position of the account."""
        chosen: list[int | None] = [None, None, None]
        account = self.s.catalog.accounts.get(place.account_id)
        if account is not None and place.value_id is not None:
            codes = [self.s.catalog.kind_codes.get(k or 0) for k in account.sc_kinds]
            if "bank_account" in codes:
                chosen[codes.index("bank_account")] = place.value_id
        return tuple(chosen)

    @property
    def folded(self) -> bool:
        """One line, as last time: its e-qaimə and amount are typed above, the line itself
        is one summary; several lines (or «Развернуть») are shown as they are."""
        return len(self.line_rows) == 1 and not self._unfolded

    def _amount_of(self, row: LineRow) -> QLineEdit:
        return self.amount if self.folded and row is self.line_rows[0] else row.amount

    @property
    def deposit_shown(self) -> bool:
        """A new payment to a supplier (from a customer) on a current account, folded,
        with an ƏDV deposit account in the company: its ƏDV part is typed beside (D69)."""
        return (
            self.doc is None
            and not self.read_only
            and self.folded
            and (bool(self.deposits) or self._pays_supplier())
            and self.kind.currentData() in (SUPPLIER, CUSTOMER)
            and not self._on_deposit()
        )

    def _pays_supplier(self) -> bool:
        """A payment to a supplier: its ƏDV may go from this account to their deposit."""
        return self.kind.currentData() == SUPPLIER and self.direction_value == OUT

    def _on_deposit(self) -> bool:
        return self.bank_info is not None and self.bank_info.account_type == "vat_deposit"

    def show_error(self, message: str) -> None:
        self.error.setText(message)
        self.error.show()

    def _not_listed(self, text: str) -> None:
        self.show_error(tr("«{text}» нет в списке", text=text))

    def _new_value(
        self, listed: bool, kind: int, text: str, owner_id=None, currency_id=None
    ) -> int | None:
        """Picked as "+ Добавить «…»": added at once, as in the journal; typed with the
        list closed: the directory's window, to check the name first (D49, D54)."""
        add = added_value if listed else new_value
        return add(self.s, self, kind, text, owner_id=owner_id, currency_id=currency_id)

    def _focus_after(self, field: QWidget, listed: bool = False) -> None:
        """Back from a dialog: on to the field after the one just filled (picked from
        the list, the field goes on by itself)."""
        if listed:
            return
        field.setFocus()
        self.focusNextChild()

    # ---- made by the groups of the page; each group may call the others --------------

    def menu_items(self) -> list[MenuItem]:  # the page
        raise NotImplementedError

    def _changed(self, *_) -> None:  # the page
        raise NotImplementedError

    def _kind_visibility(self) -> None:  # CounterpartyPart
        raise NotImplementedError

    def _suggest(self) -> None:  # LinesPart
        raise NotImplementedError

    def _default_lines(self) -> None:  # LinesPart
        raise NotImplementedError

    def _pay_several(self, row: LineRow) -> None:  # LinesPart
        raise NotImplementedError

    def _layout_lines(self) -> None:  # FoldedPart
        raise NotImplementedError
