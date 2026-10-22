"""The warehouse document's form: its fields and the page's state, and what every part of
the page asks of them. The parts that act on the fields are groups in their own modules,
put together by the page."""

from __future__ import annotations

from decimal import Decimal

from PySide6.QtCore import (
    Qt,
    Signal,
)
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemDelegate,
    QAbstractItemView,
    QApplication,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from modern_gl.application.inventory import (
    INCOMING_REASONS,
    STANDARD_VAT_RATE,
    Inventory,
    InventoryDocumentData,
)
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
from modern_gl.desktop.pick import PickBox
from modern_gl.desktop.session import Session
from modern_gl.desktop.theme import fonts
from modern_gl.desktop.widgets import (
    Chip,
    button,
    date_edit,
)
from modern_gl.domain.accounts import INPUT_VAT, OUTPUT_VAT
from modern_gl.domain.invoice import CUSTOMS, EQAIME
from modern_gl.i18n import tr


class InventoryDocumentForm(QWidget):
    saved = Signal(int)
    close_requested = Signal()
    title_changed = Signal()
    open_gl_document = Signal(int)

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

        # a new receipt (sale) has VAT when the company has an account to post its VAT to
        vat_role = OUTPUT_VAT if doc_type == "sale" else INPUT_VAT
        has_vat_account = session.ledger.account_role(session.company_id, vat_role) is not None
        self._show_vat_rate(STANDARD_VAT_RATE if has_vat_account else None)
        self.model = InventoryLinesModel(
            session,
            doc_type,
            vat_rate=self._chosen_vat_rate(),
            incoming_account=self._incoming_account(),
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
        date_caption = QLabel(tr("Дата"))
        date_caption.setObjectName("secondary")
        meta.addWidget(date_caption)
        self.date = date_edit(self.s.working_date)
        self.date.setFixedWidth(130)
        meta.addWidget(self.date)
        meta.addSpacing(12)
        type_caption = QLabel(tr("Операция"))
        type_caption.setObjectName("secondary")
        meta.addWidget(type_caption)
        self.type_label = QLabel(tr(DOCUMENT_TYPES.get(self.doc_type, self.doc_type)))
        self.type_label.setFont(fonts().heading)
        meta.addWidget(self.type_label)
        meta.addSpacing(12)
        self.vat_caption = QLabel(tr("НДС"))
        self.vat_caption.setObjectName("secondary")
        meta.addWidget(self.vat_caption)
        self.vat_rate = PickBox()
        self.vat_rate.setFixedWidth(110)
        for rate, label in VAT_RATES:
            self.vat_rate.addItem(tr(label), rate)
        meta.addWidget(self.vat_rate)
        meta.addSpacing(12)
        self._build_reason(meta)
        self._build_basis(meta)
        self._build_expense_month(meta)
        self._build_currency(meta)
        meta.addStretch(1)
        root.addLayout(meta)

    def _build_basis(self, meta: QHBoxLayout) -> None:
        # the basis of a receipt: an e-qaimə, or a customs declaration for imported goods
        self.basis = PickBox()
        self.basis.setFixedWidth(120)
        self.basis.addItem(tr("E-qaimə"), EQAIME)
        self.basis.addItem(tr("Декларация"), CUSTOMS)
        self.basis.setCurrentIndex(0)
        self.basis.setToolTip(tr("Основание: e-qaimə или таможенная декларация (импорт)"))
        meta.addWidget(self.basis)
        self.invoice_caption = QLabel(tr("E-qaimə"))  # a sale's basis is always an e-qaimə
        self.invoice_caption.setObjectName("secondary")
        meta.addWidget(self.invoice_caption)
        self.invoice = QLineEdit()
        self.invoice.setFixedWidth(170)
        self.invoice.setPlaceholderText(tr("номер"))
        meta.addWidget(self.invoice)
        # what the portal said of it when last read: awaiting approval, cancelled… (D53)
        self.portal_status = Chip()
        self.portal_status.hide()
        meta.addWidget(self.portal_status)
        meta.addSpacing(12)

    def _build_reason(self, meta: QHBoxLayout) -> None:
        # why goods come in without a purchase (D91): it chooses the account credited
        self.reason_caption = QLabel(tr("Причина"))
        self.reason_caption.setObjectName("secondary")
        meta.addWidget(self.reason_caption)
        self.reason = PickBox()
        self.reason.setFixedWidth(260)
        for key, (name, _role) in INCOMING_REASONS.items():
            self.reason.addItem(tr(name), key)
        meta.addWidget(self.reason)
        meta.addSpacing(12)

    def _build_expense_month(self, meta: QHBoxLayout) -> None:
        # services of an earlier month whose e-qaimə came later: accrued there (D65)
        self.expense_caption = QLabel(tr("Расход за"))
        self.expense_caption.setObjectName("secondary")
        meta.addWidget(self.expense_caption)
        self.expense_month = PickBox()
        self.expense_month.setFixedWidth(150)
        self.expense_month.setToolTip(
            tr(
                "Месяц расхода по услугам, если e-qaimə пришла позже: расход начисляется "
                "последним днём этого месяца (Дт затрат / Кт 76H), долг поставщику и НДС — "
                "датой e-qaimə"
            )
        )
        meta.addWidget(self.expense_month)
        meta.addSpacing(12)

    def _build_currency(self, meta: QHBoxLayout) -> None:
        self.currency_caption = QLabel(tr("Валюта"))
        self.currency_caption.setObjectName("secondary")
        meta.addWidget(self.currency_caption)
        self.currency = PickBox()
        self.currency.setFixedWidth(80)
        self.currency.addItem("AZN", None)
        for currency in self.s.catalog.active_currencies:
            self.currency.addItem(currency.code, currency.id)
        self.currency.setCurrentIndex(0)
        meta.addWidget(self.currency)
        self.rate_caption = QLabel(tr("Курс"))
        self.rate_caption.setObjectName("secondary")
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
        self.hint = QLabel(tr(HINT))
        self.hint.setObjectName("tertiary")
        self.hint.setFont(fonts().small)
        summary.addWidget(self.hint, 1)
        summary.addSpacing(24)
        self.currency_total = QLabel()
        self.currency_total.setObjectName("secondary")
        summary.addWidget(self.currency_total)
        summary.addSpacing(16)
        self.vat_total_caption = QLabel(tr("НДС"))
        self.vat_total_caption.setObjectName("secondary")
        summary.addWidget(self.vat_total_caption)
        self.vat_total = QLabel()
        self.vat_total.setMinimumWidth(90)
        self.vat_total.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        summary.addWidget(self.vat_total)
        summary.addSpacing(16)
        total_caption = QLabel(tr("Итого"))
        total_caption.setObjectName("secondary")
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
        self.btn_accrual.setToolTip(tr("Проводки начисления расхода в месяце услуги"))
        actions.addWidget(self.btn_delete)
        actions.addWidget(self.btn_unpost)
        actions.addWidget(self.btn_gl)
        actions.addWidget(self.btn_accrual)
        actions.addStretch(1)
        self.btn_save = button(tr("Сохранить черновик"), tooltip="Ctrl+S")
        self.btn_post = button(tr("Провести"), "primary", "Ctrl+Enter")
        self.btn_post.setMinimumWidth(130)
        actions.addWidget(self.btn_save)
        actions.addWidget(self.btn_post)
        root.addLayout(actions)

    # ---- what the parts ask of the fields --------------------------------------------

    def _shortcut(self, keys: str, callback) -> None:
        shortcut = QShortcut(QKeySequence(keys), self)
        shortcut.activated.connect(callback)

    def _grid_shortcut(self, keys: str, callback, *, while_editing: bool = False) -> None:
        shortcut = QShortcut(QKeySequence(keys), self.table)
        shortcut.setContext(
            Qt.ShortcutContext.WidgetWithChildrenShortcut
            if while_editing
            else Qt.ShortcutContext.WidgetShortcut
        )
        shortcut.activated.connect(callback)

    def _finish_editing(self) -> None:
        editor = QApplication.focusWidget()
        if self.table.state() == QAbstractItemView.State.EditingState and editor is not None:
            self.table.commitData(editor)
            self.table.closeEditor(editor, QAbstractItemDelegate.EndEditHint.NoHint)

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

    def _expense_date(self) -> str | None:
        return self.expense_month.currentData() if self.doc_type == "receipt" else None

    def _chosen_reason(self) -> str | None:
        return self.reason.currentData() if self.doc_type == "incoming" else None

    def _incoming_account(self) -> int | None:
        """The account a mədaxil of the chosen reason credits (D91)."""
        reason = self._chosen_reason()
        return self.inventory.incoming_account(self.s.company_id, reason) if reason else None

    def _expense_columns(self) -> tuple[bool, set[int], bool]:
        return self.model.has_expenses(), self.model.expense_positions(), self.model.has_goods()

    def show_error(self, message: str) -> None:
        self.error.setText(message)
        self.error.show()

    # ---- made by the groups of the page; each group may call the others --------------

    def _changed(self, *_args) -> None:  # the page
        raise NotImplementedError
