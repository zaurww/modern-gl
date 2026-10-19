"""Journal of documents: quiet list, search, floating "+" for a new document."""

from __future__ import annotations

from PySide6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    QSortFilterProxyModel,
    Qt,
    Signal,
)
from PySide6.QtGui import QColor, QFont, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QLineEdit,
    QMessageBox,
    QStackedLayout,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from modern_gl.application.queries import DocumentSummary, list_documents
from modern_gl.desktop.quick_entry_bar import QuickEntryBar
from modern_gl.desktop.session import Session
from modern_gl.desktop.theme import P
from modern_gl.desktop.widgets import EmptyState, PageHeader, button, money, ru_date
from modern_gl.domain.errors import LedgerError
from modern_gl.i18n import tr

COLUMNS = ["Дата", "№", "Содержание", "Книга", "Сумма", ""]
DATE, NUMBER, MEMO, BOOK, TOTAL, STATUS = range(6)
RIGHT = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
LEFT = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter


class JournalModel(QAbstractTableModel):
    def __init__(self, layer_names: dict[str, str]) -> None:
        super().__init__()
        self.docs: list[DocumentSummary] = []
        self.layer_names = layer_names

    def set_docs(self, docs: list[DocumentSummary]) -> None:
        self.beginResetModel()
        self.docs = docs
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: B008
        return 0 if parent.isValid() else len(self.docs)

    def columnCount(self, parent=QModelIndex()) -> int:  # noqa: B008
        return 0 if parent.isValid() else len(COLUMNS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation != Qt.Orientation.Horizontal:
            return None
        if role == Qt.ItemDataRole.DisplayRole:
            return tr(COLUMNS[section]) if COLUMNS[section] else ""
        if role == Qt.ItemDataRole.TextAlignmentRole:
            return RIGHT if section in (NUMBER, TOTAL) else LEFT
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        d = self.docs[index.row()]
        col = index.column()
        if role == Qt.ItemDataRole.DisplayRole:
            return {
                DATE: ru_date(d.doc_date),
                NUMBER: str(d.number),
                MEMO: d.memo or "—",
                BOOK: "" if d.layer == "common" else self.layer_names.get(d.layer, d.layer),
                TOTAL: money(d.total),
                STATUS: d.status_text
                if d.status == "draft" or d.reversal_of_number or d.reversed_by_number
                else "",
            }[col]
        if role == Qt.ItemDataRole.UserRole:
            return d.id
        if role == Qt.ItemDataRole.TextAlignmentRole:
            return RIGHT if col in (NUMBER, TOTAL) else LEFT
        if role == Qt.ItemDataRole.ForegroundRole:
            if col == STATUS:
                if d.status == "draft":
                    return QColor(P.amber)
                if d.reversal_of_number or d.reversed_by_number:
                    return QColor(P.red)
                return QColor(P.tertiary)
            if col == TOTAL and d.reversal_of_number:
                return QColor(P.red)
            if col in (DATE, NUMBER, BOOK):
                return QColor(P.secondary)
        if role == Qt.ItemDataRole.FontRole and d.status == "draft" and col == MEMO:
            f = QFont()
            f.setItalic(True)
            return f
        return None


class JournalPage(QWidget):
    key = ("journal",)
    open_document = Signal(int)
    new_document = Signal()
    copy_document = Signal(int)
    deleted = Signal(int)
    prefill_document = Signal(object)  # DocumentData typed in the quick entry line

    def __init__(self, session: Session) -> None:
        super().__init__()
        self.setObjectName("page")
        self.s = session
        root = QVBoxLayout(self)
        root.setContentsMargins(40, 30, 40, 24)
        root.setSpacing(18)

        self.header = PageHeader(tr("Журнал"), session.company_name)
        self.search = QLineEdit()
        self.search.setObjectName("search")
        self.search.setPlaceholderText(tr("Поиск по содержанию или номеру   Ctrl+F"))
        self.search.setClearButtonEnabled(True)
        self.header.add_action(self.search)
        root.addWidget(self.header)
        self.quick = QuickEntryBar(session)
        self.quick.posted.connect(lambda doc_id: self.refresh(select_id=doc_id))
        self.quick.open_form.connect(self.prefill_document.emit)
        root.addWidget(self.quick)

        self.model = JournalModel(dict(session.layers))
        self.proxy = QSortFilterProxyModel(self)
        self.proxy.setSourceModel(self.model)
        self.proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.proxy.setFilterKeyColumn(-1)
        self.search.textChanged.connect(self.proxy.setFilterFixedString)

        self.table = QTableView()
        self.table.setModel(self.proxy)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setShowGrid(False)
        self.table.setWordWrap(False)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(36)
        hh = self.table.horizontalHeader()
        hh.setHighlightSections(False)
        for col, width in ((DATE, 110), (NUMBER, 60), (BOOK, 190), (TOTAL, 140), (STATUS, 160)):
            self.table.setColumnWidth(col, width)
        hh.setSectionResizeMode(MEMO, QHeaderView.ResizeMode.Stretch)
        self.table.doubleClicked.connect(self._open_current)

        self.empty = EmptyState(
            "◎", tr("Документов пока нет"), tr("Нажмите + или Ins, чтобы ввести первую операцию.")
        )
        self.stack = QStackedLayout()
        self.stack.addWidget(self.table)
        self.stack.addWidget(self.empty)
        root.addLayout(self.stack, 1)

        # Floating "+" in the corner, like Things' Magic Plus.
        self.fab = button("+", "fab", tr("Новый документ (Ins)"))
        self.fab.setParent(self)
        self.fab.setFixedSize(52, 52)
        self.fab.clicked.connect(self.new_document.emit)

        for keys, fn in (
            ("Ins", self.new_document.emit),
            ("F5", self.refresh),
            ("Ctrl+F", self.search.setFocus),  # Ctrl+L (quick entry): the main window's
        ):
            sc = QShortcut(QKeySequence(keys), self)
            sc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            sc.activated.connect(fn)
        for keys, fn in (  # only on the list: in the text fields these keys type
            ("Return", self._open_current),
            ("Enter", self._open_current),
            ("F9", self._copy_current),
            ("Del", self._delete_current),
        ):
            sc = QShortcut(QKeySequence(keys), self.table)
            sc.setContext(Qt.ShortcutContext.WidgetShortcut)
            sc.activated.connect(fn)
        self.refresh()

    def title(self) -> str:
        return tr("Журнал")

    def is_dirty(self) -> bool:
        return False

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.fab.move(self.width() - self.fab.width() - 34, self.height() - self.fab.height() - 30)
        self.fab.raise_()

    def refresh(self, select_id: int | None = None) -> None:
        current = select_id or self._current_id()
        self.model.set_docs(list_documents(self.s.conn, self.s.company_id))
        self.stack.setCurrentWidget(self.table if self.model.docs else self.empty)
        row = next((i for i, d in enumerate(self.model.docs) if d.id == current), None)
        if row is None:
            row = len(self.model.docs) - 1
        if row >= 0:
            idx = self.proxy.mapFromSource(self.model.index(row, MEMO))
            self.table.setCurrentIndex(idx)
            self.table.scrollTo(idx)

    def focus_table(self) -> None:
        self.table.setFocus()

    def focus_quick_entry(self) -> None:
        self.quick.edit.setFocus()
        self.quick.edit.selectAll()

    def _current_id(self) -> int | None:
        idx = self.table.currentIndex()
        return idx.data(Qt.ItemDataRole.UserRole) if idx.isValid() else None

    def _open_current(self) -> None:
        if (doc_id := self._current_id()) is not None:
            self.open_document.emit(doc_id)

    def _copy_current(self) -> None:
        if (doc_id := self._current_id()) is not None:
            self.copy_document.emit(doc_id)

    def _delete_current(self) -> None:
        doc_id = self._current_id()
        doc = next((d for d in self.model.docs if d.id == doc_id), None)
        if doc is None:
            return
        question = (
            tr("Удалить черновик №{n}?", n=doc.number)
            if doc.status == "draft"
            else tr(
                "Удалить проведённый документ №{n}? Его проводки исчезнут из отчётов, "
                "а полная копия останется в журнале действий.",
                n=doc.number,
            )
        )
        if QMessageBox.question(self, tr("Удалить"), question) != QMessageBox.StandardButton.Yes:
            return
        try:
            self.s.ledger.delete_document(self.s.company_id, doc.id)
        except LedgerError as e:
            QMessageBox.warning(self, tr("Удалить"), str(e))
            return
        self.s.notify(tr("Документ №{n} удалён", n=doc.number))
        self.deleted.emit(doc.id)
        self.refresh()
