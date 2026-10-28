"""The conversion's form: the two sides, the fees, the summary and the page's state;
the page acts on them."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
)

from modern_gl.application.conversion import Conversion
from modern_gl.application.posting_preview import PostingPreview
from modern_gl.desktop import icons
from modern_gl.desktop.conversion_page.common import BASE
from modern_gl.desktop.conversion_page.fee_row import FeeRow
from modern_gl.desktop.conversion_page.side_panel import SidePanel, Stat
from modern_gl.desktop.page import PageWidget
from modern_gl.desktop.posting_preview import PostingsPanel
from modern_gl.desktop.rate_note import rate_note
from modern_gl.desktop.session import Session
from modern_gl.desktop.theme import P, fonts
from modern_gl.desktop.widgets import (
    Chip,
    MenuItem,
    button,
    caption,
    more_button,
)
from modern_gl.i18n import tr


class ConversionForm(PageWidget):
    saved = Signal(int)  # the GL document
    close_requested = Signal()
    title_changed = Signal()
    open_gl_document = Signal(int)
    copy_requested = Signal(object)  # ConversionInput

    def __init__(self, session: Session) -> None:
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
        self._build_head(root)
        self._build_rate_note(root)
        self._build_sides(root)
        self._build_fees(root)
        self._build_summary(root)

        self.error = QLabel()
        self.error.setObjectName("error")
        self.error.setWordWrap(True)
        self.error.hide()
        root.addWidget(self.error)
        self.postings = PostingsPanel(session, self.postings_preview)
        root.addWidget(self.postings)
        root.addStretch(1)
        self._build_actions(root)

    def postings_preview(self) -> PostingPreview:
        """What the conversion posts (the page answers)."""
        raise NotImplementedError

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
        self.memo.setPlaceholderText(tr("Конвертация валюты"))
        top.addWidget(self.memo, 1)
        self.status = Chip()
        top.addWidget(self.status, 0, Qt.AlignmentFlag.AlignVCenter)
        top.addWidget(more_button(self.menu_items))
        root.addLayout(top)

    def _build_rate_note(self, root: QVBoxLayout) -> None:
        """No rate of the date: load the Central Bank's rates right from here."""
        self.rate_note, self.rate_text, self.btn_rates = rate_note(tr("Курсы с cbar.az на дату"))
        root.addWidget(self.rate_note)

    def _build_sides(self, root: QVBoxLayout) -> None:
        sides = QHBoxLayout()
        sides.setSpacing(18)
        self.source = SidePanel(self.s, tr("Списано с"), credit=False)
        self.target = SidePanel(self.s, tr("Зачислено на"), credit=True)
        self.date = self.source.date
        self._last_date = self.date.date()
        arrow = QLabel()
        arrow.setPixmap(icons.icon("forward", P.tertiary, 24).pixmap(24, 24))
        sides.addWidget(self.source, 1)
        sides.addWidget(arrow, 0, Qt.AlignmentFlag.AlignVCenter)
        sides.addWidget(self.target, 1)
        root.addLayout(sides)

    def _build_fees(self, root: QVBoxLayout) -> None:
        """Bank fees: any number, each from any money account in its own currency."""
        fees_head = QHBoxLayout()
        fees_caption = caption(tr("Комиссии банка"))
        fees_head.addWidget(fees_caption)
        self.btn_add_fee = button(tr("+ Комиссия"), "flat", tr("Комиссия, которую удержал банк"))
        fees_head.addWidget(self.btn_add_fee)
        fees_head.addStretch(1)
        root.addLayout(fees_head)
        self.fee_rows: list[FeeRow] = []
        self.fees_box = QVBoxLayout()
        self.fees_box.setSpacing(8)
        root.addLayout(self.fees_box)

    def _build_summary(self, root: QVBoxLayout) -> None:
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

    def _build_actions(self, root: QVBoxLayout) -> None:
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

    # ---- what the page asks of the fields ----------------------------------------------

    @property
    def posted(self) -> bool:
        return self.doc is not None and self.doc.status == "posted"

    def show_error(self, message: str) -> None:
        self.error.setText(message)
        self.error.show()

    # ---- made by the page ------------------------------------------------------------

    def menu_items(self) -> list[MenuItem]:
        raise NotImplementedError
