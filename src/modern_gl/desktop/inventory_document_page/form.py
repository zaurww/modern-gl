"""The warehouse document's form: its fields and the page's state, and what every part of
the page asks of them. The parts that act on the fields are groups in their own modules,
put together by the page."""

from __future__ import annotations

from decimal import Decimal

from PySide6.QtCore import (
    QPersistentModelIndex,
    Qt,
    Signal,
)
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QTableView,
    QVBoxLayout,
)

from modern_gl.application.inventory import (
    INCOMING_REASONS,
    Inventory,
    InventoryDocumentData,
    default_vat_rate,
)
from modern_gl.application.posting_preview import PostingPreview
from modern_gl.desktop.grid_editing import EditableRows, GridEditing
from modern_gl.desktop.inventory_document_page.columns import (
    DOCUMENT_TYPES,
    HINT,
    VAT_DOCUMENTS,
    VAT_RATES,
)
from modern_gl.desktop.inventory_document_page.lines_model import (
    InventoryLinesModel,
)
from modern_gl.desktop.inventory_document_page.lines_table import (
    InventoryLinesDelegate,
    InventoryLinesTable,
)
from modern_gl.desktop.page import PageWidget
from modern_gl.desktop.pick import PickBox
from modern_gl.desktop.posting_preview import PostingsPanel
from modern_gl.desktop.session import Session
from modern_gl.desktop.shortcuts import legend
from modern_gl.desktop.theme import fonts
from modern_gl.desktop.widgets import (
    Chip,
    button,
    caption,
    date_edit,
    edited_date,
)
from modern_gl.domain.invoice import CUSTOMS, EQAIME
from modern_gl.i18n import tr

AWAITING = "awaiting"  # the basis box: a purchase waiting for its e-qaimə (D119)


GAP = 16  # between the groups of the header: a document fits a 1366 px screen


class InventoryDocumentForm(GridEditing, PageWidget):
    saved = Signal(int)
    close_requested = Signal()
    title_changed = Signal()
    open_gl_document = Signal(int)
    make_return = Signal(str, int)  # the return's type, the purchase (sale) it returns
    buy_shortage = Signal(int)  # a draft short of goods: a purchase «ждёт e-qaimə» of them

    DUPLICATE_COLUMN = 0  # the copy of a line: on its item

    def _grid(self) -> QTableView:
        return self.table

    def _rows(self) -> EditableRows:
        return self.model

    def __init__(self, session: Session, doc_type: str) -> None:
        super().__init__()
        self.setObjectName("page")
        self.s = session
        self.inventory = Inventory(session.conn, actor=session.ledger.actor)
        self.doc: InventoryDocumentData | None = None
        self.doc_type = doc_type
        self.dirty = False

        root = QVBoxLayout(self)
        root.setContentsMargins(40, 30, 40, 22)
        root.setSpacing(14)
        self._build_head(root)
        self._build_meta(root)
        self._build_party(root)

        self._show_vat_rate(default_vat_rate(session.ledger, session.company_id, doc_type))
        self.model = InventoryLinesModel(
            session,
            doc_type,
            vat_rate=self._chosen_vat_rate(),
            incoming_account=self._incoming_account(),
            doc_date=edited_date(self.date),
        )
        self.delegate = InventoryLinesDelegate(self)
        self.table = InventoryLinesTable(self.model, self.delegate)
        self.expense_columns = self._expense_columns()  # shown for these
        root.addWidget(self.table, 1)

        self.error = QLabel()
        self.error.setObjectName("error")
        self.error.setWordWrap(True)
        self.error.hide()
        root.addWidget(self.error)

        self._build_summary(root)
        self.postings = PostingsPanel(session, self.postings_preview)
        root.addWidget(self.postings)
        self._build_actions(root)

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
        self.memo.setPlaceholderText(tr("Комментарий складского документа"))
        top.addWidget(self.memo, 1)
        self.status = Chip()
        top.addWidget(self.status, 0, Qt.AlignmentFlag.AlignVCenter)
        root.addLayout(top)

    def _build_meta(self, root: QVBoxLayout) -> None:
        meta = QHBoxLayout()
        meta.setSpacing(8)  # a caption by its field; the groups part by GAP
        date_caption = caption(tr("Дата"))
        meta.addWidget(date_caption)
        self.date = date_edit(self.s.working_date)
        self.date.setFixedWidth(130)
        meta.addWidget(self.date)
        meta.addSpacing(GAP)
        # what the document is, in a word: «Покупка» needs no caption
        self.type_label = QLabel(tr(DOCUMENT_TYPES.get(self.doc_type, self.doc_type)))
        self.type_label.setFont(fonts().heading)
        meta.addWidget(self.type_label)
        meta.addSpacing(GAP)
        self.vat_caption = caption(tr("НДС"))
        meta.addWidget(self.vat_caption)
        self.vat_rate = PickBox()
        self.vat_rate.setFixedWidth(110)
        for rate, label in VAT_RATES:
            self.vat_rate.addItem(tr(label), rate)
        meta.addWidget(self.vat_rate)
        meta.addSpacing(GAP)
        self._build_reason(meta)
        self._build_basis(meta)
        self._build_currency(meta)
        meta.addStretch(1)
        root.addLayout(meta)

    def _build_basis(self, meta: QHBoxLayout) -> None:
        # the basis of a receipt: an e-qaimə, or a customs declaration for imported goods
        self.basis = PickBox()
        self.basis.setFixedWidth(120)
        self.basis.addItem(tr("E-qaimə"), EQAIME)
        self.basis.addItem(tr("Декларация"), CUSTOMS)
        self.basis.addItem(tr("Ждёт e-qaimə"), AWAITING)  # goods came first (D119)
        self.basis.setCurrentIndex(0)
        self.basis.setToolTip(
            tr(
                "Основание: e-qaimə или таможенная декларация (импорт). «Ждёт e-qaimə» — "
                "товар пришёл раньше документов: номер и ƏDV допишет загрузка с портала"
            )
        )
        meta.addWidget(self.basis)
        self.invoice_caption = caption(tr("E-qaimə"))  # a sale's basis is always an e-qaimə
        meta.addWidget(self.invoice_caption)
        self.invoice = QLineEdit()
        self.invoice.setFixedWidth(140)  # «MT2601001842» and room to spare
        self.invoice.setPlaceholderText(tr("номер"))
        meta.addWidget(self.invoice)
        # what the portal said of it when last read: awaiting approval, cancelled… (D53)
        self.portal_status = Chip()
        self.portal_status.hide()
        meta.addWidget(self.portal_status)
        meta.addSpacing(GAP)

    def _build_reason(self, meta: QHBoxLayout) -> None:
        # why goods come in without a purchase (D91): it chooses the account credited
        self.reason_caption = caption(tr("Причина"))
        meta.addWidget(self.reason_caption)
        self.reason = PickBox()
        self.reason.setFixedWidth(260)
        for key, (name, _role) in INCOMING_REASONS.items():
            self.reason.addItem(tr(name), key)
        meta.addWidget(self.reason)
        meta.addSpacing(GAP)

    def _build_currency(self, meta: QHBoxLayout) -> None:
        self.currency_caption = caption(tr("Валюта"))
        meta.addWidget(self.currency_caption)
        self.currency = PickBox()
        self.currency.setFixedWidth(80)
        self.currency.addItem("AZN", None)
        for currency in self.s.catalog.active_currencies:
            self.currency.addItem(currency.code, currency.id)
        self.currency.setCurrentIndex(0)
        meta.addWidget(self.currency)
        self.rate_caption = caption(tr("Курс"))
        meta.addWidget(self.rate_caption)
        self.rate = QLineEdit()
        self.rate.setFixedWidth(90)
        self.rate.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.rate.setPlaceholderText(tr("курс"))
        self.rate.setToolTip(tr("Курс на дату документа; можно исправить (например, курс таможни)"))
        meta.addWidget(self.rate)
        self.rate_typed = False  # typed by hand: a new date no longer changes it

    def _build_summary(self, root: QVBoxLayout) -> None:
        summary = QHBoxLayout()
        self.hint = QLabel(legend(*HINT))
        self.hint.setObjectName("tertiary")
        self.hint.setFont(fonts().small)
        self.hint.setWordWrap(True)  # never widens the window
        summary.addWidget(self.hint, 1)
        summary.addSpacing(24)
        self.currency_total = caption()
        summary.addWidget(self.currency_total)
        summary.addSpacing(16)
        self.vat_total_caption = caption(tr("НДС"))
        summary.addWidget(self.vat_total_caption)
        self.vat_total = QLabel()
        self.vat_total.setMinimumWidth(90)
        self.vat_total.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        summary.addWidget(self.vat_total)
        summary.addSpacing(16)
        total_caption = caption(tr("Итого"))
        summary.addWidget(total_caption)
        self.total = QLabel()
        self.total.setMinimumWidth(130)
        self.total.setFont(fonts().total)
        self.total.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        summary.addWidget(self.total)
        root.addLayout(summary)

    def _build_actions(self, root: QVBoxLayout) -> None:
        actions = QHBoxLayout()
        self.btn_delete = button(tr("Удалить"), "danger")
        self.btn_unpost = button(tr("Отменить проведение"), "flat")
        self.btn_gl = button(tr("Открыть проводки"), "flat")
        self.btn_accrual = button(tr("Начисление"), "flat")
        self.btn_accrual.setToolTip(
            tr("Проводки начисления дохода в месяце услуги")
            if self.doc_type == "sale"
            else tr("Проводки начисления расхода в месяце услуги")
        )
        actions.addWidget(self.btn_delete)
        actions.addWidget(self.btn_unpost)
        actions.addWidget(self.btn_gl)
        actions.addWidget(self.btn_accrual)
        self.btn_objects = button(tr("Объекты по названиям строк"), "flat")
        self.btn_objects.setToolTip(
            tr("Каждая отмеченная строка получит своё основное средство — по своему названию")
        )
        self.btn_objects.hide()
        actions.addWidget(self.btn_objects)
        self.btn_return = button(tr("Оформить возврат"), "flat")
        self.btn_return.setToolTip(
            tr("Товар вернули: возврат по этому документу — его цены и ƏDV, без лишнего ввода")
        )
        actions.addWidget(self.btn_return)
        self.btn_shortage = button(tr("Оприходовать недостающее…"), "flat")
        self.btn_shortage.setToolTip(
            tr(
                "Товар пришёл, а документов нет: покупка «ждёт e-qaimə» на недостающее по "
                "последней цене; проведите её — и этот документ проведётся"
            )
        )
        self.btn_shortage.hide()
        actions.addWidget(self.btn_shortage)
        actions.addStretch(1)
        self.btn_save = button(tr("Сохранить черновик"), tooltip="Ctrl+S")
        self.btn_post = button(tr("Провести"), "primary", "Ctrl+Enter")
        self.btn_post.setMinimumWidth(130)
        actions.addWidget(self.btn_save)
        actions.addWidget(self.btn_post)
        root.addLayout(actions)

    # ---- what the parts ask of the fields --------------------------------------------

    def _shown(self, column: int) -> bool:
        return not self.table.isColumnHidden(column)

    def _show_vat_rate(self, rate: int | None) -> None:
        index = self.vat_rate.findData(rate)
        if index < 0:  # a rate not in the list (set elsewhere): show it as it is
            self.vat_rate.addItem(f"{Decimal(rate or 0).scaleb(-2).normalize():f}%", rate)
            index = self.vat_rate.count() - 1
        self.vat_rate.setCurrentIndex(index)
        with_vat = self.doc_type in VAT_DOCUMENTS
        self.vat_caption.setVisible(with_vat)
        self.vat_rate.setVisible(with_vat)

    def _chosen_vat_rate(self) -> int | None:
        return self.vat_rate.currentData() if self.doc_type in VAT_DOCUMENTS else None

    def _chosen_currency(self) -> int | None:
        return self.currency.currentData() if self.doc_type == "receipt" else None

    def _chosen_reason(self) -> str | None:
        return self.reason.currentData() if self.doc_type == "incoming" else None

    def _incoming_account(self) -> int | None:
        """The account a mədaxil of the chosen reason credits (D91)."""
        reason = self._chosen_reason()
        return self.inventory.incoming_account(self.s.company_id, reason) if reason else None

    def _expense_columns(self) -> tuple[bool, set[int], bool, bool]:
        """What decides the columns shown: a service line, its subconto, goods, the
        supplier (customer) of every line in the header."""
        model = self.model
        return (
            model.has_expenses(),
            model.expense_positions(),
            model.has_goods(),
            model.party_in_header(),
        )

    def show_error(self, message: str) -> None:
        self.error.setText(message)
        self.error.show()

    # ---- made by the groups of the page; each group may call the others --------------

    def _changed(self, *_args) -> None:  # the page
        raise NotImplementedError

    def postings_preview(self) -> PostingPreview:  # the page
        raise NotImplementedError

    def _split_months(self, index: QPersistentModelIndex) -> None:  # the splits
        raise NotImplementedError

    def _build_party(self, root: QVBoxLayout) -> None:  # the party
        raise NotImplementedError
