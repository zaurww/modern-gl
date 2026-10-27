"""A journal document's form: its fields and the page's state, and what every part of the
page asks of them. The parts that act on the fields are groups in their own modules, put
together by the page."""

from __future__ import annotations

from fractions import Fraction

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QTableView,
    QVBoxLayout,
)

from modern_gl.application.currencies import rate_on
from modern_gl.application.queries import (
    DocumentData,
    last_memo,
    list_templates,
    recent_subconto,
)
from modern_gl.desktop.grid_editing import EditableRows, GridEditing
from modern_gl.desktop.page import PageWidget
from modern_gl.desktop.postings import (
    DT,
    EntryHints,
    PostingsDelegate,
    PostingsModel,
    PostingsTable,
)
from modern_gl.desktop.rate_note import rate_note
from modern_gl.desktop.session import Session
from modern_gl.desktop.shortcuts import legend
from modern_gl.desktop.theme import fonts
from modern_gl.desktop.widgets import (
    Chip,
    MenuItem,
    button,
    date_edit,
    edited_date,
    money,
    more_button,
)
from modern_gl.i18n import tr

HINT = (  # the keys of the page, under its table
    "next_field",
    "previous_field",
    "insert",
    "duplicate_row",
    "delete",
    "template",
    "paste_rows",
    "save",
    "post",
    "post_and_new",
)


class DocumentForm(GridEditing, PageWidget):
    saved = Signal(int)  # document id
    open_document = Signal(int)
    copy_requested = Signal(object)  # DocumentData to prefill a new document
    template_saved = Signal(int)  # entry template made from this document
    close_requested = Signal()
    title_changed = Signal()
    new_requested = Signal()  # posted with Ctrl+Shift+Enter: the next document, please
    open_inventory_document = Signal(int)  # the warehouse document that made this one

    INSERT_COLUMN = DT  # a new line: its debit account, typed at once
    EDIT_INSERTED = True

    def _grid(self) -> QTableView:
        return self.table

    def _rows(self) -> EditableRows:
        return self.model

    def __init__(self, session: Session) -> None:
        super().__init__()
        self.setObjectName("page")
        self.s = session
        self.doc: DocumentData | None = None
        self.dirty = False

        root = QVBoxLayout(self)
        root.setContentsMargins(40, 30, 40, 22)
        root.setSpacing(14)
        self._build_head(root)
        self._build_meta(root)
        self._build_table(root)
        self._build_rate_note(root)

        self.error = QLabel()
        self.error.setObjectName("error")
        self.error.setWordWrap(True)
        self.error.hide()
        root.addWidget(self.error)
        self._build_total(root)
        self._build_actions(root)

    # ---- the fields ------------------------------------------------------------------

    def _build_head(self, root: QVBoxLayout) -> None:
        """Title row: the memo is the document's title, like a task name in Things."""
        top = QHBoxLayout()
        self.number = QLabel()
        self.number.setObjectName("tertiary")
        self.number.setFont(fonts().heading)
        top.addWidget(self.number)
        self.memo = self._title_edit()
        top.addWidget(self.memo, 1)
        self.status = Chip()
        top.addWidget(self.status, 0, Qt.AlignmentFlag.AlignVCenter)
        root.addLayout(top)

    def _build_meta(self, root: QVBoxLayout) -> None:
        meta = QHBoxLayout()
        meta.setSpacing(8)
        self.date = date_edit(self.s.working_date)
        self.date.setFixedWidth(130)
        self.layer = QComboBox()
        for code, name in self.s.layers:
            self.layer.addItem(name, code)
        self.layer.setFixedWidth(230)
        # A document from an entry template asks for the operation amount once (S);
        # lines with a formula follow it.
        self.amount = QLineEdit()
        self.amount.setFixedWidth(150)
        self.amount.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.amount.setPlaceholderText("0.00")
        self.amount_caption = QLabel(tr("Сумма операции"))
        for label, w in ((tr("Дата"), self.date), (tr("Книга"), self.layer)):
            caption = QLabel(label)
            caption.setObjectName("secondary")
            meta.addWidget(caption)
            meta.addWidget(w)
            meta.addSpacing(10)
            # one book until parallel books are turned on (D63): no field to pass by
            if w is self.layer and not self.s.parallel_books:
                caption.hide()
                w.hide()
        self.amount_caption.setObjectName("secondary")
        meta.addWidget(self.amount_caption)
        meta.addWidget(self.amount)
        self.amount_caption.hide()
        self.amount.hide()
        meta.addStretch(1)
        # who entered and who posted it, quietly on the right (D82); a new one: nobody yet
        self.authors = QLabel()
        self.authors.setObjectName("tertiary")
        self.authors.setFont(fonts().small)
        self.authors.hide()
        meta.addWidget(self.authors)
        root.addLayout(meta)

    def _build_table(self, root: QVBoxLayout) -> None:
        session = self.s
        self.model = PostingsModel(session.catalog)
        self.model.rate_for = self._rate_for
        cid = session.company_id
        self.delegate = PostingsDelegate(
            session.catalog,
            self,
            EntryHints(
                recent=lambda account, pos: recent_subconto(session.conn, cid, account, pos),
                memo=lambda dt, ct: last_memo(session.conn, cid, dt, ct),
                templates=lambda: [(t.id, t.name) for t in list_templates(session.conn, cid)],
            ),
        )
        self.table = PostingsTable(self.model, self.delegate)
        root.addWidget(self.table, 1)

    def _build_rate_note(self, root: QVBoxLayout) -> None:
        """No rate of the document date: load the Central Bank's rates right from here."""
        self.rate_note, self.rate_text, self.btn_rates = rate_note(
            tr("Курсы с cbar.az на дату документа")
        )
        root.addWidget(self.rate_note)

    def _build_total(self, root: QVBoxLayout) -> None:
        bottom = QHBoxLayout()
        self.hint = QLabel(legend(*HINT))
        self.hint.setObjectName("tertiary")
        self.hint.setFont(fonts().small)
        self.hint.setWordWrap(True)  # never widens the window
        keep = self.hint.sizePolicy()
        keep.setRetainSizeWhenHidden(True)  # a posted document: "Итого" stays by the total
        self.hint.setSizePolicy(keep)
        bottom.addWidget(self.hint, 1)
        total_caption = QLabel(tr("Итого"))
        total_caption.setObjectName("secondary")
        bottom.addWidget(total_caption)
        self.total = QLabel()
        self.total.setFont(fonts().total)
        self.total.setMinimumWidth(130)
        self.total.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        bottom.addWidget(self.total)
        root.addLayout(bottom)

    def _build_actions(self, root: QVBoxLayout) -> None:
        actions = QHBoxLayout()
        actions.setSpacing(8)
        # The rest of what can be done with the document waits in "⋯" (see menu_items).
        self.btn_more = more_button(self.menu_items, tr("Действия с документом"))
        actions.addWidget(self.btn_more)
        # Postings made by a warehouse document are corrected there: one click away.
        self.btn_source = button("", "flat", tr("Проводки сформированы складским документом"))
        self.btn_source.hide()
        actions.addWidget(self.btn_source)
        actions.addStretch(1)
        self.btn_save = button(tr("Сохранить черновик"), tooltip="Ctrl+S")
        self.btn_post = button(tr("Провести"), "primary", "Ctrl+Enter")
        self.btn_post.setMinimumWidth(130)
        actions.addWidget(self.btn_save)
        actions.addWidget(self.btn_post)
        root.addLayout(actions)

    # ---- what the parts ask of the fields --------------------------------------------

    @property
    def doc_id(self) -> int | None:
        return self.doc.id if self.doc else None

    def _title_edit(self) -> QLineEdit:
        edit = QLineEdit()
        edit.setObjectName("titleEdit")
        edit.setFont(fonts().title)
        edit.setPlaceholderText(tr("Содержание операции"))
        return edit

    def _rate_for(self, currency_id: int) -> Fraction | None:
        """Manat per unit of a currency on the document date (the latest one before it)."""
        rate = rate_on(self.s.conn, self.s.company_id, currency_id, edited_date(self.date))
        return rate.per_unit if rate else None

    def _update_total(self) -> None:
        self.total.setText(money(self.model.total(), blank_zero=False))

    def _select_layer(self, code: str) -> None:
        i = self.layer.findData(code)
        if i >= 0:
            self.layer.setCurrentIndex(i)

    def _shown(self, col: int) -> bool:
        return not self.table.isColumnHidden(col)

    def _focus_grid(self) -> None:
        self.table.setCurrentIndex(self.model.index(0, DT))
        self.table.setFocus(Qt.FocusReason.TabFocusReason)  # the cell opens for typing

    def show_error(self, message: str) -> None:
        self.error.setText(message)
        self.error.show()

    # ---- made by the groups of the page; each group may call the others --------------

    def menu_items(self) -> list[MenuItem]:  # the page
        raise NotImplementedError
