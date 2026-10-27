"""Journal of documents: quiet list, search, floating "+" for a new document."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    QPersistentModelIndex,
    QSortFilterProxyModel,
    Qt,
    Signal,
)
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QLineEdit,
    QMessageBox,
    QStackedLayout,
    QVBoxLayout,
)

from modern_gl.application.authorship import journal_authors
from modern_gl.application.queries import (
    DocumentSummary,
    document_year,
    document_years,
    list_documents,
)
from modern_gl.desktop.list_table import ListTable
from modern_gl.desktop.page import PageWidget
from modern_gl.desktop.quick_entry_bar import QuickEntryBar
from modern_gl.desktop.reason_dialog import confirm_delete
from modern_gl.desktop.session import Session
from modern_gl.desktop.shortcuts import bind
from modern_gl.desktop.theme import P
from modern_gl.desktop.widgets import (
    EmptyState,
    MenuItem,
    PageHeader,
    button,
    hide_when_viewing,
    menu_button,
    money,
    ru_date,
    trailing_icon,
)
from modern_gl.domain.errors import LedgerError
from modern_gl.i18n import tr
from modern_gl.infrastructure.db import Connection

COLUMNS = ["Дата", "№", "Содержание", "Книга", "Автор", "Сумма", ""]
DATE, NUMBER, MEMO, BOOK, AUTHOR, TOTAL, STATUS = range(7)
RIGHT = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
LEFT = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter


def shown_year(years: list[int], wanted: int | None, working_year: int) -> int | None:
    """The year the journal shows (debt 6: one year, not every document of a large
    company): the one asked for, else the working date's, else the nearest one that has
    documents. `years` — the latest first; none — None (nothing to show)."""
    if not years:
        return None
    for year in (wanted, working_year):
        if year in years:
            return year
    return min(years, key=lambda y: abs(y - working_year))  # the latest of two as near


@dataclass(frozen=True)
class JournalData:
    years: list[int]  # that have documents, the latest first
    year: int | None  # shown; None — every year
    docs: list[DocumentSummary]
    authors: dict[int, str]


class JournalModel(QAbstractTableModel):
    def __init__(self, layer_names: dict[str, str]) -> None:
        super().__init__()
        self.docs: list[DocumentSummary] = []
        self.authors: dict[int, str] = {}  # document → who entered or posted it last (D82)
        self.layer_names = layer_names

    def set_docs(self, docs: list[DocumentSummary], authors: dict[int, str]) -> None:
        self.beginResetModel()
        self.docs = docs
        self.authors = authors
        self.endResetModel()

    def several_authors(self) -> bool:
        """The column «Author» is shown only when more than one person works here."""
        return len(set(self.authors.values())) > 1

    def rowCount(self, parent: QModelIndex | QPersistentModelIndex | None = None) -> int:
        return 0 if parent is not None and parent.isValid() else len(self.docs)

    def columnCount(self, parent: QModelIndex | QPersistentModelIndex | None = None) -> int:
        return 0 if parent is not None and parent.isValid() else len(COLUMNS)

    def headerData(self, section, orientation, role: int = Qt.ItemDataRole.DisplayRole):
        if orientation != Qt.Orientation.Horizontal:
            return None
        if role == Qt.ItemDataRole.DisplayRole:
            return tr(COLUMNS[section]) if COLUMNS[section] else ""
        if role == Qt.ItemDataRole.TextAlignmentRole:
            return RIGHT if section in (NUMBER, TOTAL) else LEFT
        return None

    def data(self, index, role: int = Qt.ItemDataRole.DisplayRole):
        d = self.docs[index.row()]
        col = index.column()
        if role == Qt.ItemDataRole.DisplayRole:
            return {
                DATE: ru_date(d.doc_date),
                NUMBER: str(d.number),
                MEMO: d.memo or "—",
                BOOK: "" if d.layer == "common" else self.layer_names.get(d.layer, d.layer),
                AUTHOR: self.authors.get(d.id, ""),
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
            if col in (DATE, NUMBER, BOOK, AUTHOR):
                return QColor(P.secondary)
            # done is quieter, a draft — still to do — in the full text color (D86)
            if col in (MEMO, TOTAL) and d.status != "draft":
                return QColor(P.muted)
        return None


class JournalPage(PageWidget):
    key = ("journal",)
    open_document = Signal(int)
    new_document = Signal()
    copy_document = Signal(int)
    deleted = Signal(int)
    prefill_document = Signal(object)  # DocumentData typed in the quick entry line
    import_requested = Signal()

    def __init__(self, session: Session) -> None:
        super().__init__()
        self.setObjectName("page")
        self.s = session
        root = QVBoxLayout(self)
        root.setContentsMargins(40, 30, 40, 24)
        root.setSpacing(18)
        root.addWidget(self._build_header(session))
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
        self._build_table(session)

        self.empty = EmptyState(
            "◎",
            tr("Документов пока нет"),
            tr("Нажмите «+ Новый документ» или Ins, чтобы ввести первую операцию."),
        )
        self.stack = QStackedLayout()
        self.stack.addWidget(self.table)
        self.stack.addWidget(self.empty)
        root.addLayout(self.stack, 1)

        hide_when_viewing(session.read_only, self.new_button, self.more, self.quick)
        self._bind_keys()
        self.refresh()

    def _build_header(self, session: Session) -> PageHeader:
        self.header = PageHeader(tr("Журнал"), session.company_name)
        self.search = QLineEdit()
        self.search.setObjectName("search")
        self.search.setPlaceholderText(tr("Поиск по содержанию или номеру   Ctrl+F"))
        self.search.setClearButtonEnabled(True)
        self.header.add_action(self.search)
        self.year: int | None = None  # the year shown; None — every year
        self.all_years = False
        self.years: list[int] = []
        self.year_button = menu_button(
            trailing_icon(button("", "flatMenu", tr("Документы какого года показать"))),
            self._year_items,
        )
        self.header.add_action(self.year_button)
        self.new_button = self.header.primary(
            tr("+ Новый документ"), self.new_document.emit, "Ins, Ctrl+N"
        )
        self.more = self.header.more(lambda: [(tr("Импорт из Excel…"), self.import_requested.emit)])
        return self.header

    def _build_table(self, session: Session) -> None:
        self.table = ListTable(self.proxy, 36, fill=MEMO, wrap=False)
        self.table.setColumnHidden(BOOK, not session.parallel_books)  # one book (D63)
        self.table.doubleClicked.connect(self._open_current)

    def _bind_keys(self) -> None:
        bind(self, "insert", self.new_document.emit)
        bind(self, "refresh", self.refresh)
        bind(self, "find", self.search.setFocus)  # Ctrl+L (quick entry): the main window's
        # only on the list: in the text fields these keys type
        bind(self.table, "open_row", self._open_current)
        bind(self.table, "copy_document", self._copy_current)
        bind(self.table, "delete", self._delete_current)

    def title(self) -> str:
        return tr("Журнал")

    def activated(self) -> None:
        self.refresh()
        self.focus_table()

    def on_postings_changed(self, doc_id: int) -> None:
        self.refresh(select_id=doc_id)

    def refresh(self, select_id: int | None = None) -> None:
        """The documents of the year read (in the background for a large company) and
        shown; a document asked for (just saved) brings its own year."""
        current = select_id or self._current_id()
        cid, wanted, every = self.s.company_id, self.year, self.all_years
        working_year = self.s.working_date.year

        def read(conn: Connection) -> JournalData:
            years = document_years(conn, cid)
            asked = document_year(conn, cid, select_id) if select_id else None
            year = None if every else shown_year(years, asked or wanted, working_year)
            bounds = (f"{year}-01-01", f"{year}-12-31") if year else (None, None)
            docs = list_documents(conn, cid, *bounds)
            return JournalData(years, year, docs, journal_authors(conn, cid))

        self.s.read(
            self,
            read,
            lambda found: self._show(found, current),
            lambda e: self.s.notify(str(e)),
        )

    def show_year(self, year: int | None) -> None:
        """A year from the menu (None — every year)."""
        self.all_years = year is None
        self.year = year
        self.refresh()

    def _year_items(self) -> list[MenuItem]:
        items: list[MenuItem] = [(str(y), lambda y=y: self.show_year(y)) for y in self.years]
        return [*items, None, (tr("Все годы"), lambda: self.show_year(None))]

    def _show(self, data: JournalData, current: int | None) -> None:
        self.years, self.year = data.years, data.year
        self.year_button.setText(str(data.year) if data.year else tr("Все годы"))
        self.year_button.setVisible(len(data.years) > 1 or self.all_years)
        self.model.set_docs(data.docs, data.authors)
        self.table.setColumnHidden(AUTHOR, not self.model.several_authors())
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
        if doc is None or self.s.read_only:
            return
        reason = confirm_delete(self, doc.number, doc.status == "posted")
        if reason is None:
            return
        try:
            self.s.ledger.delete_document(self.s.company_id, doc.id, reason)
        except LedgerError as e:
            QMessageBox.warning(self, tr("Удалить"), str(e))
            return
        self.s.notify(tr("Документ №{n} удалён", n=doc.number))
        self.deleted.emit(doc.id)
        self.refresh()
