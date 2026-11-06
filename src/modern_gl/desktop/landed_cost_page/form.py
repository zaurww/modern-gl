"""The «Расходы по партии» form: its fields and the page's state; the page acts on them."""

from __future__ import annotations

from PySide6.QtCore import (
    Qt,
    Signal,
)
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
)

from modern_gl.application.inventory import (
    Inventory,
    InventoryDocumentData,
)
from modern_gl.application.posting_preview import PostingPreview
from modern_gl.desktop.grid_editing import finish_editing
from modern_gl.desktop.landed_cost_page.columns import (
    HINT,
    HINT_TYPED,
    METHODS,
)
from modern_gl.desktop.landed_cost_page.models import ChargesModel, TargetsModel
from modern_gl.desktop.landed_cost_page.table import CellDelegate, LinesTable
from modern_gl.desktop.page import PageWidget
from modern_gl.desktop.pick import PickBox
from modern_gl.desktop.posting_preview import PostingsPanel
from modern_gl.desktop.session import Session
from modern_gl.desktop.shortcuts import SEPARATOR, legend
from modern_gl.desktop.theme import fonts
from modern_gl.desktop.widgets import (
    Chip,
    button,
    caption,
    date_edit,
)
from modern_gl.i18n import N_, tr


class LandedCostForm(PageWidget):
    saved = Signal(int)
    close_requested = Signal()
    title_changed = Signal()
    open_gl_document = Signal(int)

    doc_type = "landed_cost"

    def __init__(self, session: Session) -> None:
        super().__init__()
        self.setObjectName("page")
        self.s = session
        self.inventory = Inventory(session.conn, actor=session.ledger.actor)
        self.doc: InventoryDocumentData | None = None
        self.dirty = False

        root = QVBoxLayout(self)
        root.setContentsMargins(40, 30, 40, 22)
        root.setSpacing(12)
        self._build_head(root)
        self._build_meta(root)
        self.delegate = CellDelegate(self)
        self._build_tables(root)

        self.error = QLabel()
        self.error.setObjectName("error")
        self.error.setWordWrap(True)
        self.error.hide()
        root.addWidget(self.error)

        self._build_summary(root)
        self.postings = PostingsPanel(session, self.postings_preview)
        root.addWidget(self.postings)
        self._build_actions(root)

    def postings_preview(self) -> PostingPreview:
        """What the costs post (the page answers)."""
        raise NotImplementedError

    def _build_head(self, root: QVBoxLayout) -> None:
        top = QHBoxLayout()
        self.number = QLabel()
        self.number.setObjectName("tertiary")
        self.number.setFont(fonts().heading)
        top.addWidget(self.number)
        self.memo = QLineEdit()
        self.memo.setObjectName("titleEdit")
        self.memo.setFont(fonts().title)
        self.memo.setPlaceholderText(tr("Партия: название или номер инвойса"))
        top.addWidget(self.memo, 1)
        self.status = Chip()
        top.addWidget(self.status, 0, Qt.AlignmentFlag.AlignVCenter)
        root.addLayout(top)

    def _build_meta(self, root: QVBoxLayout) -> None:
        meta = QHBoxLayout()
        self.date = date_edit(self.s.working_date)
        self.date.setFixedWidth(130)
        self.method = PickBox()
        self.method.setFixedWidth(170)
        for method, title in METHODS:
            self.method.addItem(tr(title), method)
        self.method.setCurrentIndex(0)
        for text, widget in ((tr("Дата"), self.date), (tr("Распределение"), self.method)):
            label = caption(text)
            meta.addWidget(label)
            meta.addWidget(widget)
            meta.addSpacing(12)
        meta.addStretch(1)
        root.addLayout(meta)

    def _build_tables(self, root: QVBoxLayout) -> None:
        """The costs of the batch and the receipts they are spread over."""
        charges_bar = QHBoxLayout()
        charges_title = QLabel(tr("Расходы"))
        charges_title.setFont(fonts().heading)
        charges_bar.addWidget(charges_title, 1)
        self.btn_add_charge = button(tr("+ Расход"), "flat", "Ins")
        self.btn_from_gl = button(tr("+ Ждущие расходы…"), "flat")
        charges_bar.addWidget(self.btn_add_charge)
        charges_bar.addWidget(self.btn_from_gl)
        root.addLayout(charges_bar)
        self.charges = ChargesModel(self.s, [], read_only=False)
        self.charges_table = LinesTable(self.charges, self.delegate)
        root.addWidget(self.charges_table, 1)

        batch_bar = QHBoxLayout()
        batch_title = QLabel(tr("Партия"))
        batch_title.setFont(fonts().heading)
        batch_bar.addWidget(batch_title, 1)
        self.btn_add_receipts = button(tr("+ Поступления…"), "flat")
        batch_bar.addWidget(self.btn_add_receipts)
        root.addLayout(batch_bar)
        self.targets = TargetsModel([], read_only=False)
        self.targets_table = LinesTable(self.targets, self.delegate)
        root.addWidget(self.targets_table, 1)

    def _build_summary(self, root: QVBoxLayout) -> None:
        summary = QHBoxLayout()
        self.hint = QLabel(
            SEPARATOR.join([legend(*HINT), *(tr(t) for t in HINT_TYPED), legend("post")])
        )
        self.hint.setObjectName("tertiary")
        self.hint.setFont(fonts().small)
        self.hint.setWordWrap(True)  # never widens the window
        summary.addWidget(self.hint, 1)
        summary.addSpacing(24)
        self.totals: dict[str, QLabel] = {}
        for key, text in (
            ("vat", "НДС"),
            ("allocated", N_("Распределено")),
            ("total", "Расходы"),
        ):
            label = caption(tr(text))
            value = QLabel()
            value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            value.setMinimumWidth(90)
            if key == "total":
                value.setFont(fonts().total)
                value.setMinimumWidth(130)
            summary.addWidget(label)
            summary.addWidget(value)
            summary.addSpacing(16)
            self.totals[key] = value
            self.totals[f"{key}_caption"] = label
        root.addLayout(summary)

    def _build_actions(self, root: QVBoxLayout) -> None:
        actions = QHBoxLayout()
        self.btn_delete = button(tr("Удалить"), "danger")
        self.btn_unpost = button(tr("Отменить проведение"), "flat")
        self.btn_gl = button(tr("Открыть проводки"), "flat")
        self.btn_report = button(tr("Себестоимость партии"), "flat")
        actions.addWidget(self.btn_delete)
        actions.addWidget(self.btn_unpost)
        actions.addWidget(self.btn_gl)
        actions.addWidget(self.btn_report)
        actions.addStretch(1)
        self.btn_save = button(tr("Сохранить черновик"), tooltip="Ctrl+S")
        self.btn_post = button(tr("Провести"), "primary", "Ctrl+Enter")
        self.btn_post.setMinimumWidth(130)
        actions.addWidget(self.btn_save)
        actions.addWidget(self.btn_post)
        root.addLayout(actions)

    def show_error(self, message: str) -> None:
        self.error.setText(message)
        self.error.show()

    def _finish_editing(self) -> None:
        finish_editing(self.charges_table, self.targets_table)
