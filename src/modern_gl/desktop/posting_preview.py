"""«Проводки» under a module's document form (bank, conversion, warehouse, landed costs):
the postings it makes — or would make, while it is a draft or being edited — to check
them before «Провести» (F7 opens and closes it; open or not is remembered). What would be
posted is the page's own saving and posting, rolled back (`application/posting_preview`).
Not shown in «only the warehouse» (D90): there the books are not seen."""

from __future__ import annotations

from collections.abc import Callable, Collection

from PySide6.QtCore import QSize, QTimer
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from modern_gl.application.posting_preview import (
    PostingPreview,
    PreviewPosting,
    owned_postings,
    preview_postings,
)
from modern_gl.desktop import icons
from modern_gl.desktop.preferences import prefs
from modern_gl.desktop.reports_page.report_table import ReportTable
from modern_gl.desktop.reports_page.table import ROW_HEIGHT, Column, ReportModel
from modern_gl.desktop.session import Session
from modern_gl.desktop.shortcuts import bind, label
from modern_gl.desktop.theme import P
from modern_gl.desktop.widgets import button, caption, money
from modern_gl.domain.dates import ru_date
from modern_gl.domain.errors import LedgerError
from modern_gl.i18n import tr

OPEN_KEY = "postings_preview_open"
SHOWN_ROWS = 8  # more scroll inside the table
DELAY_MS = 300  # typing goes on: the preview waits for a pause

Write = Callable[[], Collection[int]]


def document_postings(
    session: Session, module: str, saved: Collection[int], write: Write | None
) -> PostingPreview:
    """The postings of the module's documents `saved` as stored; `write` given (a draft,
    an edited or a new document) — what posting it would make. A company open for
    viewing writes nothing, not even to undo it: it shows what is stored."""
    if write is None or session.read_only:
        return PostingPreview(owned_postings(session.conn, session.company_id, module, saved))
    return preview_postings(session.conn, session.company_id, module, write)


def _subconto(names: tuple[str, ...]) -> str:
    return ", ".join(names)


def postings_columns(rows: list[PreviewPosting]) -> list[Column]:
    debit, credit = tr("Дебет"), tr("Кредит")
    cols = []
    if len({r.doc_date for r in rows}) > 1:  # a conversion's two days, an accrual's month
        cols.append(Column(tr("Дата"), lambda r: ru_date(r.doc_date), width=1))
    cols += [
        Column(tr("Счёт"), lambda r: r.debit, width=1, group=debit),
        Column(tr("Субконто"), lambda r: _subconto(r.debit_subconto), group=debit),
        Column(tr("Счёт"), lambda r: r.credit, width=1, group=credit),
        Column(tr("Субконто"), lambda r: _subconto(r.credit_subconto), group=credit),
        Column(tr("Сумма"), lambda r: r.amount, money=True),
    ]
    if any(r.currency for r in rows):
        cols.append(
            Column(
                tr("В валюте"),
                lambda r: f"{money(r.currency_amount)} {r.currency}" if r.currency else "",
                right=True,
                tone=lambda r: "currency",
            )
        )
    if any(r.invoice for r in rows):
        cols.append(Column("e-qaimə", lambda r: r.invoice, width=1))
    cols.append(Column(tr("Содержание"), lambda r: r.memo, tone=lambda r: "secondary"))
    return cols


class PostingsPanel(QWidget):
    """The caption line «› Проводки  2 · 1 180,00» and, open, the table of postings.
    `read()` is the page's question — `document_postings` with its documents; the page
    calls `changed()` when its fields change and the panel asks again after a pause."""

    def __init__(self, session: Session, read: Callable[[], PostingPreview]) -> None:
        super().__init__()
        self.s = session
        self.read = read
        self.preview = PostingPreview()
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(DELAY_MS)
        self._timer.timeout.connect(self.refresh)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)
        line = QHBoxLayout()
        line.setSpacing(10)
        tip = f"{tr('Показать проводки документа')} ({label('postings')})"
        self.toggle = button(tr("Проводки"), "flat", tip)
        self.toggle.setIconSize(QSize(14, 14))
        self.toggle.clicked.connect(self.flip)
        line.addWidget(self.toggle)
        self.summary = caption()
        line.addWidget(self.summary)
        line.addStretch(1)
        root.addLayout(line)

        self.error = QLabel()
        self.error.setObjectName("error")
        self.error.setWordWrap(True)
        root.addWidget(self.error)
        self.model = ReportModel()
        self.model.bands = False
        self.table = ReportTable(self.model)
        root.addWidget(self.table)

        self.opened = prefs().flag(OPEN_KEY, False)
        self.setVisible(not session.stock_only)
        self._show_state()

    def bind_key(self, page: QWidget) -> None:
        bind(page, "postings", self.flip)

    def flip(self) -> None:
        if self.s.stock_only:
            return
        self.opened = not self.opened
        prefs().set(OPEN_KEY, self.opened)
        if self.opened:
            self.refresh()
        self._show_state()

    def changed(self) -> None:
        """The page's fields changed: asked again after a pause, only when it is open."""
        if self.opened and not self.s.stock_only:
            self._timer.start()

    def refresh(self) -> None:
        self._timer.stop()
        if not self.opened or self.s.stock_only:
            return
        try:
            self.preview = self.read()
        except (LedgerError, ValueError, TypeError) as e:  # a field the page cannot read
            self.preview = PostingPreview(error=str(e))
        rows = self.preview.postings
        self.model.set(postings_columns(rows), rows)
        self.table.layout_columns()
        self._show_state()

    def _show_state(self) -> None:
        opened = self.opened
        self.toggle.setIcon(icons.icon("down" if opened else "next", P.secondary, 14))
        rows = self.preview.postings
        error = self.preview.error if opened else ""
        self.error.setText(error)
        self.error.setVisible(bool(error))
        self.table.setVisible(opened and bool(rows))
        if opened and rows:
            shown = min(len(rows), SHOWN_ROWS)
            head = self.table.horizontalHeader().sizeHint().height()
            self.table.setFixedHeight(head + shown * ROW_HEIGHT + 2)
        if not opened:
            self.summary.setText("")
        elif error:
            self.summary.setText(tr("не проведётся"))
        elif not rows:
            self.summary.setText(tr("проводок нет"))
        else:
            self.summary.setText(f"{len(rows)}  ·  {money(self.preview.total, False)}")
