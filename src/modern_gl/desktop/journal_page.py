"""Journal of documents: quiet list, search, floating "+" for a new document."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    QPersistentModelIndex,
    Qt,
    Signal,
)
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QLineEdit,
    QMessageBox,
    QStackedLayout,
    QVBoxLayout,
)

from modern_gl.application.document_kinds import kind_name
from modern_gl.application.journal import (
    JournalFilter,
    Key,
    Rows,
    document_key,
    documents_after,
    documents_before,
    key_of,
    page_authors,
    several_authors,
)
from modern_gl.application.posting_preview import PreviewPosting, gl_postings
from modern_gl.application.queries import DocumentSummary, document_year, document_years
from modern_gl.desktop.list_table import ListTable
from modern_gl.desktop.page import PageWidget
from modern_gl.desktop.posting_peek import bind_peek
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
from modern_gl.i18n import N_, tr
from modern_gl.infrastructure.db import Connection

# the kind and the number the user knows (D213): «Alış 6», not the GL number
COLUMNS = [
    N_("Дата"),
    N_("Вид"),
    N_("№"),
    N_("Содержание"),
    N_("Книга"),
    N_("Автор"),
    N_("Сумма"),
    "",
]
DATE, KIND, NUMBER, MEMO, BOOK, AUTHOR, TOTAL, STATUS = range(8)
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


def year_bounds(year: int | None) -> tuple[str | None, str | None]:
    return (f"{year}-01-01", f"{year}-12-31") if year else (None, None)


@dataclass(frozen=True)
class JournalData:
    years: list[int]  # that have documents, the latest first
    year: int | None  # shown; None — every year
    filter: JournalFilter  # what was read: the pages beyond it are read the same way
    before: Rows  # up to the document shown (the end of the year by default)
    after: Rows  # the documents after it
    authors: dict[int, str]
    several_authors: bool


class JournalModel(QAbstractTableModel):
    """The documents read so far, in the journal's order (D168): a page of
    them around the one shown; older ones come in as the list is scrolled up, newer ones
    (canFetchMore / fetchMore) as it is scrolled down. `fetch(older)` — the page's reader."""

    def __init__(self, layer_names: dict[str, str]) -> None:
        super().__init__()
        self.docs: list[DocumentSummary] = []
        self.authors: dict[int, str] = {}  # document → who entered or posted it last (D82)
        self.layer_names = layer_names
        self._several = False
        self.older = self.newer = False  # more documents beyond the first / the last read
        self.reading = False  # a page is on its way
        self.fetch: Callable[[bool], None] = lambda older: None

    def set_docs(self, data: JournalData) -> None:
        self.beginResetModel()
        self.docs = data.before.docs + data.after.docs
        self.authors = dict(data.authors)
        self.older, self.newer = data.before.more, data.after.more
        self.reading = False
        self._several = data.several_authors
        self.endResetModel()

    def add(self, rows: Rows, authors: dict[int, str], older: bool) -> None:
        """A page read beyond the first document (`older`) or the last."""
        self.reading = False
        self.authors.update(authors)
        if older:
            self.older = rows.more
        else:
            self.newer = rows.more
        if not rows.docs:
            return
        first = 0 if older else len(self.docs)
        self.beginInsertRows(QModelIndex(), first, first + len(rows.docs) - 1)
        self.docs[first:first] = rows.docs
        self.endInsertRows()

    def bounds(self) -> tuple[Key, Key] | None:
        return (key_of(self.docs[0]), key_of(self.docs[-1])) if self.docs else None

    def canFetchMore(self, parent: QModelIndex | QPersistentModelIndex) -> bool:
        return not parent.isValid() and self.newer and not self.reading

    def fetchMore(self, parent: QModelIndex | QPersistentModelIndex) -> None:
        if self.canFetchMore(parent):
            self.fetch_page(older=False)

    def fetch_page(self, older: bool) -> None:
        if self.reading or not (self.older if older else self.newer):
            return
        self.reading = True
        self.fetch(older)

    def several_authors(self) -> bool:
        """The column «Author» is shown only when more than one person works here."""
        return self._several

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
                KIND: kind_name(d.kind),
                NUMBER: str(d.shown_number),
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
            if col in (DATE, KIND, NUMBER, BOOK, AUTHOR):
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
        self.model.fetch = self._fetch
        # searched in the query (all the year, not the rows read): letters folded, İ/ş = i/s
        self.search.textChanged.connect(lambda _text: self.refresh())
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
        self.filter = JournalFilter(session.company_id)
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
        self.table = ListTable(self.model, 36, fill=MEMO, wrap=False)
        self.table.setColumnHidden(BOOK, not session.parallel_books)  # one book (D63)
        self.table.doubleClicked.connect(self._open_current)
        bind_peek(self.table, session, self._current_postings)
        # scrolled to the top: the older documents (the newer ones — the model's fetchMore)
        bar = self.table.verticalScrollBar()
        bar.valueChanged.connect(lambda v: v == bar.minimum() and self.model.fetch_page(True))

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
        """A page of the year's documents read (in the background for a large company)
        around the one shown — just saved, else the current, else the year's end — and
        shown; a document asked for brings its own year."""
        current = select_id or self._current_id()
        cid, wanted, every = self.s.company_id, self.year, self.all_years
        working_year, text = self.s.working_date.year, self.search.text()
        books = tuple(self.model.layer_names.items())

        def read(conn: Connection) -> JournalData:
            years = document_years(conn, cid)
            asked = document_year(conn, cid, select_id) if select_id else None
            year = None if every else shown_year(years, asked or wanted, working_year)
            f = JournalFilter(cid, *year_bounds(year), text, books)
            key = document_key(conn, cid, current) if current else None
            before = documents_before(conn, f, key, including=True)
            after = documents_after(conn, f, key) if key else Rows([], False)
            ids = [d.id for d in before.docs + after.docs]
            authors, several = page_authors(conn, cid, ids), several_authors(conn, cid)
            return JournalData(years, year, f, before, after, authors, several)

        self.model.reading = True  # no page beyond the old rows meanwhile
        self.s.read(self, read, lambda found: self._show(found, current), self._failed)

    def _fetch(self, older: bool) -> None:
        """The page beyond the first document read (`older`) or the last one."""
        bounds, f, cid = self.model.bounds(), self.filter, self.s.company_id
        if bounds is None:
            return

        def read(conn: Connection) -> tuple[Rows, dict[int, str]]:
            if older:
                rows = documents_before(conn, f, bounds[0])
            else:
                rows = documents_after(conn, f, bounds[1])
            return rows, page_authors(conn, cid, [d.id for d in rows.docs])

        self.s.read(self, read, lambda found: self._add(found, older), self._failed)

    def _add(self, found: tuple[Rows, dict[int, str]], older: bool) -> None:
        rows, authors = found
        top = self.table.indexAt(self.table.viewport().rect().topLeft()).row()
        self.model.add(rows, authors, older)
        if older and rows.docs:  # the rows on the screen stay where they were
            self.table.updateGeometries()  # the scroll bar knows the new rows at once
            index = self.model.index(max(top, 0) + len(rows.docs), MEMO)
            self.table.scrollTo(index, QAbstractItemView.ScrollHint.PositionAtTop)

    def _failed(self, error: LedgerError) -> None:
        self.model.reading = False
        self.s.notify(str(error))

    def show_year(self, year: int | None) -> None:
        """A year from the menu (None — every year)."""
        self.all_years = year is None
        self.year = year
        self.refresh()

    def _year_items(self) -> list[MenuItem]:
        items: list[MenuItem] = [(str(y), lambda y=y: self.show_year(y)) for y in self.years]
        return [*items, None, (tr("Все годы"), lambda: self.show_year(None))]

    def _show(self, data: JournalData, current: int | None) -> None:
        self.years, self.year, self.filter = data.years, data.year, data.filter
        self.year_button.setText(str(data.year) if data.year else tr("Все годы"))
        self.year_button.setVisible(len(data.years) > 1 or self.all_years)
        self.model.set_docs(data)
        self.table.setColumnHidden(AUTHOR, not self.model.several_authors())
        searched = bool(self.search.text().strip())
        self.stack.setCurrentWidget(self.table if self.model.docs or searched else self.empty)
        row = next((i for i, d in enumerate(self.model.docs) if d.id == current), None)
        if row is None:
            row = len(self.model.docs) - 1
        if row >= 0:
            idx = self.model.index(row, MEMO)
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

    def _current_postings(self) -> list[PreviewPosting] | None:
        doc_id = self._current_id()
        return None if doc_id is None else gl_postings(self.s.conn, self.s.company_id, doc_id)

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
