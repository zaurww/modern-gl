"""The «Расходы по партии» form: its fields and the page's state; the page acts on them."""

from __future__ import annotations

from PySide6.QtCore import (
    Signal,
)
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
)

from modern_gl.application.inventory import (
    Inventory,
    InventoryDocumentData,
)
from modern_gl.application.posting_preview import PostingPreview
from modern_gl.desktop.document_shell import DocumentShell
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
    button,
    caption,
    date_edit,
)
from modern_gl.i18n import N_, tr


class LandedCostForm(DocumentShell, PageWidget):
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
        self.build_head(root, tr("Партия: название или номер инвойса"))

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
        hint = SEPARATOR.join([legend(*HINT), *(tr(t) for t in HINT_TYPED), legend("post")])
        summary = self.build_summary(root, hint)
        summary.addSpacing(24)
        self.totals: dict[str, QLabel] = {}
        for key, text in (
            ("vat", "НДС"),
            ("allocated", N_("Распределено")),
            ("total", "Расходы"),
        ):
            label, value = self.add_figure(summary, tr(text), main=key == "total")
            summary.addSpacing(16)
            self.totals[key] = value
            self.totals[f"{key}_caption"] = label

    def _build_actions(self, root: QVBoxLayout) -> None:
        self.btn_delete = button(tr("Удалить"), "danger")
        self.btn_unpost = button(tr("Отменить проведение"), "flat")
        self.btn_gl = button(tr("Открыть проводки"), "flat")
        self.btn_report = button(tr("Себестоимость партии"), "flat")
        self.build_actions(root, [self.btn_delete, self.btn_unpost, self.btn_gl, self.btn_report])

    def show_error(self, message: str) -> None:
        self.error.setText(message)
        self.error.show()

    def _finish_editing(self) -> None:
        finish_editing(self.charges_table, self.targets_table)
