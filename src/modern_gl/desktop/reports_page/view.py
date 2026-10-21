"""What every report shares: its columns, model, header, delegate and the page with
period, book and context menu."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Any

from PySide6.QtCore import (
    QAbstractTableModel,
    QEvent,
    QModelIndex,
    QPersistentModelIndex,
    QRect,
    QSize,
    Qt,
    Signal,
)
from PySide6.QtGui import QAction, QColor, QFontMetrics, QKeySequence, QPainter, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMenu,
    QStackedLayout,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from modern_gl.desktop.session import Session
from modern_gl.desktop.theme import P, fonts
from modern_gl.desktop.widgets import (
    EmptyState,
    PageHeader,
    button,
    class_name,
    date_edit,
    edited_date,
    ru_date,
    type_choices,
    type_name,
)
from modern_gl.domain.errors import LedgerError
from modern_gl.domain.money import format_minor
from modern_gl.i18n import tr
from modern_gl.reporting.reports import COMMON, IFRS, TAX, OsvRow

BOOKS = [("Общий учёт", COMMON), ("МСФО", IFRS), ("Налоговый учёт", TAX)]
RIGHT = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
LEFT = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
# (group over a Dt/Kt pair, side, attribute)
TURNOVER_COLUMNS = [
    ("Сальдо на начало", "Дт", "opening_dt"),
    ("Сальдо на начало", "Кт", "opening_ct"),
    ("Обороты", "Дт", "turnover_dt"),
    ("Обороты", "Кт", "turnover_ct"),
    ("Сальдо на конец", "Дт", "closing_dt"),
    ("Сальдо на конец", "Кт", "closing_ct"),
]
# Reports follow Jon Moon (Clarity & Impact): a table as wide as its content, so the
# amounts stand next to the names; whitespace and soft bands of three rows instead of
# rules; a dash under the units for nothing; negatives in brackets that hang right.
DASH = "–"
NAME_MAX = 380  # px: a longer name is cut with "…" (the whole of it shows under the mouse)
GROUP_GAP = 24  # px of air in front of each Dt/Kt pair
BAND = 3  # rows in a band
ROW_HEIGHT = 24
SECTION_HEIGHT = 34  # a class header in the trial balance: air above it
TOTAL_HEIGHT = 28


@dataclass
class Column:
    title: str
    get: Callable[[Any], Any]
    money: bool = False
    # 0 = a name: as wide as its text (at most NAME_MAX), the first to narrow; otherwise
    # a report fits the column to its text, the chart of accounts keeps this width
    width: int = 0
    icon: Callable[[Any], Any] | None = None  # optional QIcon in front of the text
    warn: Callable[[Any], str | None] | None = None  # text -> red cell with a tooltip
    right: bool = False  # a number that is not money ("7 000.00 Dt"): aligned like one
    tone: Callable[[Any], str | None] | None = None  # a palette color of the text (status)
    group: str = ""  # a caption over the columns next to each other that share it


def figure(minor: int | None) -> str:
    """An amount in a report: nothing is a dash, a negative is in brackets."""
    if minor is None:
        return ""
    if minor == 0:
        return DASH
    return f"({format_minor(-minor)})" if minor < 0 else format_minor(minor)


@dataclass
class ReportParams:
    date_from: date
    date_to: date
    book: int = 0  # index in BOOKS

    @property
    def layers(self) -> tuple[str, ...]:
        return BOOKS[self.book][1]

    def describe(self, book: bool = True) -> str:
        period = f"{ru_date(self.date_from.isoformat())} — {ru_date(self.date_to.isoformat())}"
        return f"{period}   ·   {tr(BOOKS[self.book][0])}" if book else period


def month_of(d: date) -> ReportParams:
    nxt = date(d.year + d.month // 12, d.month % 12 + 1, 1)
    return ReportParams(date(d.year, d.month, 1), date.fromordinal(nxt.toordinal() - 1))


def turnover_columns(warn_opening=None, warn_closing=None) -> list[Column]:
    warns = {"opening": warn_opening, "closing": warn_closing}
    return [
        Column(
            tr(side),
            (lambda r, a=a: getattr(r, a)),
            money=True,
            warn=warns.get(a.split("_")[0]),
            group=tr(group),
        )
        for group, side, a in TURNOVER_COLUMNS
    ]


# A context menu entry: text and what it does, or text and a submenu; None is a separator.
type MenuAction = tuple[str, Callable[[], None] | list[MenuAction | None]]


@dataclass
class SectionRow(OsvRow):
    """An account class header that groups top-level accounts in the trial balance."""

    account_class: str | None = None


class ReportModel(QAbstractTableModel):
    def __init__(self) -> None:
        super().__init__()
        self.columns: list[Column] = []
        self.rows: list[Any] = []
        self.emphasis: Callable[[Any], bool] = lambda r: False
        self.muted: Callable[[Any], bool] = lambda r: False
        self.total: Callable[[Any], bool] = lambda r: False
        self.section: Callable[[Any], bool] = lambda r: False
        self.banded: list[bool] = []
        self.bands = True  # a list (the chart of accounts) goes without

    def set(self, columns, rows, emphasis=None, muted=None, total=None, section=None) -> None:
        self.beginResetModel()
        self.columns, self.rows = columns, rows
        self.emphasis = emphasis or (lambda r: False)
        self.muted = muted or (lambda r: False)
        self.total = total or (lambda r: False)  # a rule above it
        self.section = section or (lambda r: False)  # a header: air above, bands restart
        self.banded = []
        run = 0
        for r in rows:
            if not self.bands or self.total(r) or self.section(r):
                self.banded.append(False)
                run = 0
            else:
                self.banded.append(run // BAND % 2 == 1)
                run += 1
        self.endResetModel()

    def rowCount(self, parent: QModelIndex | QPersistentModelIndex | None = None) -> int:
        return 0 if parent is not None and parent.isValid() else len(self.rows)

    def columnCount(self, parent: QModelIndex | QPersistentModelIndex | None = None) -> int:
        return 0 if parent is not None and parent.isValid() else len(self.columns)

    def title(self, section: int) -> str:
        return self.columns[section].title

    def headerData(self, section, orientation, role: int = Qt.ItemDataRole.DisplayRole):
        if orientation != Qt.Orientation.Horizontal:
            return None
        if role == Qt.ItemDataRole.DisplayRole:
            return self.title(section)
        if role == Qt.ItemDataRole.TextAlignmentRole:
            return RIGHT if self.columns[section].money or self.columns[section].right else LEFT
        return None

    def data(self, index, role: int = Qt.ItemDataRole.DisplayRole):
        row, col = self.rows[index.row()], self.columns[index.column()]
        if role == Qt.ItemDataRole.DisplayRole:
            return self._text(row, col)
        if role == Qt.ItemDataRole.TextAlignmentRole:
            return RIGHT if col.money or col.right else LEFT
        if role == Qt.ItemDataRole.FontRole and self.emphasis(row):
            return fonts().cell_bold
        if role in (Qt.ItemDataRole.ForegroundRole, Qt.ItemDataRole.ToolTipRole) and col.warn:
            message = col.warn(row)
            if message and col.get(row):
                return QColor(P.red) if role == Qt.ItemDataRole.ForegroundRole else message
        if role == Qt.ItemDataRole.ForegroundRole:
            return self._foreground(row, col)
        if role == Qt.ItemDataRole.DecorationRole and col.icon is not None:
            return col.icon(row)
        if role == Qt.ItemDataRole.UserRole:
            return row
        return None

    @staticmethod
    def _text(row, col: Column) -> str:
        value = col.get(row)
        if col.money:
            return figure(value)
        if col.right and value == "":
            return DASH
        return "" if value is None else str(value)

    def _foreground(self, row, col: Column) -> QColor | None:
        if col.tone and (tone := col.tone(row)):
            return QColor(getattr(P, tone))
        if (col.money and col.get(row) == 0) or (col.right and col.get(row) == ""):
            return QColor(P.tertiary)  # the dash: there, but quiet
        if self.muted(row):
            return QColor(P.secondary)
        if col.money and isinstance(v := col.get(row), int) and v < 0:
            return QColor(P.red)
        return None


class GroupHeader(QHeaderView):
    """Column captions; a group caption ("İlkin qalıq") spans its Dt and Kt below it,
    with a hairline under it that leaves the gap in front of the pair open."""

    def __init__(self, parent=None) -> None:
        super().__init__(Qt.Orientation.Horizontal, parent)
        self.setHighlightSections(False)
        self.setSectionsClickable(False)

    def _columns(self) -> list[Column]:
        model = self.model()
        return model.columns if isinstance(model, ReportModel) else []

    def _band(self) -> int:
        """Height of the group captions' line; 0 without groups."""
        if not any(c.group for c in self._columns()):
            return 0
        return self.fontMetrics().height() + 8

    def sizeHint(self) -> QSize:
        hint = super().sizeHint()
        return QSize(hint.width(), hint.height() + self._band())

    def paintSection(self, painter, rect, logicalIndex) -> None:
        columns = self._columns()
        number = logicalIndex < len(columns) and (
            columns[logicalIndex].money or columns[logicalIndex].right
        )
        hang = self.fontMetrics().horizontalAdvance(")") if number else 0  # as the digits
        super().paintSection(painter, rect.adjusted(0, self._band(), -hang, 0), logicalIndex)

    def paintEvent(self, e) -> None:
        super().paintEvent(e)
        band = self._band()
        if not band:
            return
        columns = self._columns()
        painter = QPainter(self.viewport())
        # the rule under the captions in one piece (the sections' own end short of
        # their right edge: the captions of amounts stand over the digits)
        last = len(columns) - 1
        bottom = self.height() - 1
        painter.setPen(QColor(P.hairline))
        painter.drawLine(
            self.sectionViewportPosition(0),
            bottom,
            self.sectionViewportPosition(last) + self.sectionSize(last),
            bottom,
        )
        painter.setFont(self.font())
        i = 0
        while i < len(columns):
            group = columns[i].group
            j = i
            while j + 1 < len(columns) and group and columns[j + 1].group == group:
                j += 1
            if group:
                left = self.sectionViewportPosition(i) + GROUP_GAP
                right = self.sectionViewportPosition(j) + self.sectionSize(j) - 11
                area = QRect(left, 2, right - left, band - 6)
                painter.setPen(QColor(P.secondary))
                painter.drawText(area, Qt.AlignmentFlag.AlignCenter, group)
                painter.setPen(QColor(P.hairline))
                painter.drawLine(left, band - 2, right, band - 2)
            i = j + 1
        painter.end()


class ReportDelegate(QStyledItemDelegate):
    """Amounts drawn so that the units stand in one line: a negative's ")" hangs to the
    right of it, a dash sits under the units; a rule above a total."""

    def __init__(self, table: QTableView) -> None:
        super().__init__(table)
        self.table = table

    def paint(self, painter, option, index) -> None:
        model = index.model()
        assert isinstance(model, ReportModel)
        col, row = model.columns[index.column()], model.rows[index.row()]
        if model.section(row):  # a class header: the air above it, the caption below
            option = QStyleOptionViewItem(option)
            option.rect.adjust(0, SECTION_HEIGHT - ROW_HEIGHT, 0, 0)
        # the band under the style's hover and selection (a stylesheet item hides
        # the model's background)
        if model.banded[index.row()]:
            painter.fillRect(option.rect, QColor(P.subtle))
        if col.money or col.right:
            opt = QStyleOptionViewItem(option)
            self.initStyleOption(opt, index)
            text, opt.text = opt.text, ""
            style = self.table.style()
            style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, self.table)
            metrics = QFontMetrics(opt.font)
            hang = 0 if text.endswith(")") else metrics.horizontalAdvance(")")
            painter.save()
            painter.setFont(opt.font)
            pen = index.data(Qt.ItemDataRole.ForegroundRole)
            painter.setPen(pen if isinstance(pen, QColor) else QColor(P.text))
            align = index.data(Qt.ItemDataRole.TextAlignmentRole)
            painter.drawText(opt.rect.adjusted(0, 0, -(11 + hang), 0), align, text)
            painter.restore()
        else:
            super().paint(painter, option, index)
        if model.total(row):
            painter.save()
            painter.setPen(QColor(P.text))
            painter.drawLine(option.rect.topLeft(), option.rect.topRight())
            painter.restore()


NAME_MIN = 180  # px an account name keeps before it is cut in a narrow window


class ReportPage(QWidget):
    """Base: header, parameters, table/empty state, footer."""

    open_document = Signal(int)
    open_report = Signal(str, int, object)  # kind, account id, ReportParams

    has_period = True
    summary_on_top = True

    def __init__(self, session: Session, title: str, params: ReportParams | None = None) -> None:
        super().__init__()
        self.setObjectName("page")
        self.s = session
        self.params = params or month_of(session.working_date)
        root = QVBoxLayout(self)
        root.setContentsMargins(40, 30, 40, 24)
        root.setSpacing(16)

        self.header = PageHeader(title, "")
        root.addWidget(self.header)

        if self.has_period:
            bar = QHBoxLayout()
            bar.setSpacing(8)
            self.date_from = date_edit(self.params.date_from)
            self.date_to = date_edit(self.params.date_to)
            self.book = QComboBox()
            for name, _ in BOOKS:
                self.book.addItem(tr(name))
            self.book.setCurrentIndex(self.params.book)
            for caption, w, width in (
                (tr("Период с"), self.date_from, 130),
                (tr("по"), self.date_to, 130),
                (tr("Книга"), self.book, 170),
            ):
                label = QLabel(caption)
                label.setObjectName("secondary")
                w.setFixedWidth(width)
                bar.addWidget(label)
                bar.addWidget(w)
                bar.addSpacing(6)
                if w is self.book and not session.parallel_books:  # one book (D63)
                    label.hide()
                    w.hide()
            run = button(tr("Сформировать"), "primary", "F5")
            run.clicked.connect(self.refresh)
            bar.addWidget(run)
            bar.addStretch(1)
            root.addLayout(bar)
            self.bar = bar

        self.model = ReportModel()
        self.table = QTableView()
        self.table.setObjectName("report")
        self.table.setHorizontalHeader(GroupHeader(self.table))
        self.table.setModel(self.model)
        self.table.setItemDelegate(ReportDelegate(self.table))
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setShowGrid(False)
        self.table.setWordWrap(False)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(ROW_HEIGHT)
        self.table.doubleClicked.connect(lambda idx: self.drill(idx.data(Qt.ItemDataRole.UserRole)))
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._context_menu)
        # a narrow window: amounts give up some width
        self._viewport = self.table.viewport()
        self._viewport.installEventFilter(self)
        self._widths: dict[int, int] = {}

        self.empty = EmptyState("○", tr("Нет данных"), tr("За выбранный период движений не было."))
        self.stack = QStackedLayout()
        self.stack.addWidget(self.table)
        self.stack.addWidget(self.empty)

        # a report's message (totals, "Dt and Kt agree") is read before its detail
        self.footer = QLabel()
        self.footer.setObjectName("secondary")
        self.footer.setWordWrap(True)  # a long hint must not keep the window wide
        if self.summary_on_top:
            root.addWidget(self.footer)
            root.addLayout(self.stack, 1)
        else:
            root.addLayout(self.stack, 1)
            root.addWidget(self.footer)

        for keys, fn in (
            ("F5", self.refresh),
            ("Return", self._drill_current),
            ("Enter", self._drill_current),
        ):
            sc = QShortcut(QKeySequence(keys), self)
            sc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            sc.activated.connect(fn)

    # ---- to implement ----------------------------------------------------------------

    def build(self) -> None:
        raise NotImplementedError

    def drill(self, row: Any) -> None:
        pass

    def menu_actions(self, row: Any) -> list[MenuAction | None]:
        return []

    # ---- common ----------------------------------------------------------------------

    def is_dirty(self) -> bool:
        return False

    def focus_table(self) -> None:
        self.table.setFocus()

    def refresh(self) -> None:
        if self.has_period:
            self.params = ReportParams(
                edited_date(self.date_from),
                edited_date(self.date_to),
                self.book.currentIndex(),
            )
            self.header.subtitle.setText(self.params.describe(self.s.parallel_books))
        try:
            self.build()
        except LedgerError as e:
            self.s.notify(str(e))
            return
        self.stack.setCurrentWidget(self.table if self.model.rows else self.empty)
        self._layout_columns()
        self.footer.setVisible(bool(self.footer.text()))

    def _layout_columns(self) -> None:
        """Every column as wide as its widest text, so the amounts stand right after the
        names and the free room stays empty on the right (Jon Moon: the eye must not
        travel across a blank to find the number). A name keeps at most NAME_MAX."""
        hh = self.table.horizontalHeader()
        hh.setStretchLastSection(False)
        columns = self.model.columns
        self._widths: dict[int, int] = {}
        for i, col in enumerate(columns):
            hh.setSectionResizeMode(i, QHeaderView.ResizeMode.Interactive)
            width = self._content_width(i)
            if col.money or col.right:
                width += QFontMetrics(self.table.font()).horizontalAdvance(")")
            if col.group and (i == 0 or columns[i - 1].group != col.group):
                width += GROUP_GAP
            self._widths[i] = width if col.width or col.money or col.right else min(width, NAME_MAX)
        self._fit_groups()
        for r, row in enumerate(self.model.rows):
            if self.model.section(row):
                self.table.setRowHeight(r, SECTION_HEIGHT)
            elif self.model.total(row):
                self.table.setRowHeight(r, TOTAL_HEIGHT)
        self.table.horizontalHeader().updateGeometry()
        self._fit_columns()

    def _fit_groups(self) -> None:
        """A group caption wider than its columns widens them."""
        columns, metrics = self.model.columns, self.table.horizontalHeader().fontMetrics()
        for group in {c.group for c in columns if c.group}:
            members = [i for i, c in enumerate(columns) if c.group == group]
            need = metrics.horizontalAdvance(group) + GROUP_GAP + 22
            short = need - sum(self._widths[i] for i in members)
            for i in members:
                self._widths[i] += max(0, short) // len(members) + 1

    def _content_width(self, column: int) -> int:
        """The widest text of a column (bold totals included) or its caption."""
        bold = self.table.font()
        bold.setBold(True)
        metrics = QFontMetrics(bold)
        widest = (
            self.table.horizontalHeader().fontMetrics().horizontalAdvance(self.model.title(column))
        )
        icon = self.model.columns[column].icon is not None
        for r in range(min(self.model.rowCount(), 2000)):
            text = self.model.data(self.model.index(r, column), Qt.ItemDataRole.DisplayRole)
            widest = max(widest, metrics.horizontalAdvance(str(text or "")))
        return widest + 28 + (24 if icon else 0)  # the cell padding of the theme

    def _fit_columns(self) -> None:
        """In a narrow window the names give up width first (cut with "…"), down to
        NAME_MIN; then the table scrolls sideways."""
        widths = self._widths
        if not widths:
            return
        columns = self.model.columns
        names = [i for i, c in enumerate(columns) if not (c.width or c.money or c.right)]
        others = sum(w for i, w in widths.items() if i not in names)
        room = (self.table.viewport().width() - others) // max(1, len(names))
        for i, width in widths.items():
            if i in names:
                width = max(min(width, NAME_MIN), min(width, room))
            self.table.setColumnWidth(i, width)

    def eventFilter(self, watched, event) -> bool:
        if watched is self._viewport and event.type() == QEvent.Type.Resize:
            self._fit_columns()
        return super().eventFilter(watched, event)

    def _drill_current(self) -> None:
        idx = self.table.currentIndex()
        if idx.isValid():
            self.drill(idx.data(Qt.ItemDataRole.UserRole))

    def _context_menu(self, pos) -> None:
        idx = self.table.indexAt(pos)
        if not idx.isValid():
            return
        actions = self.menu_actions(idx.data(Qt.ItemDataRole.UserRole))
        if not actions:
            return
        menu = QMenu(self)
        self._fill_menu(menu, actions)
        menu.exec(self.table.viewport().mapToGlobal(pos))

    def _fill_menu(self, menu: QMenu, actions: list[MenuAction | None]) -> None:
        """(text, callable) = action, (text, [...]) = submenu, None = separator."""
        for entry in actions:
            if entry is None:
                menu.addSeparator()
                continue
            text, target = entry
            if isinstance(target, list):
                self._fill_menu(menu.addMenu(text), target)
            else:
                act = QAction(text, menu)
                act.triggered.connect(target)
                menu.addAction(act)

    def _class_actions(self, account_id: int) -> list[MenuAction | None]:
        """Submenu to change an account's type (and so class) and contra flag."""
        acc = self.s.catalog.accounts.get(account_id)
        if acc is None:
            return []

        def mark(on: bool, text: str) -> str:
            return ("✓  " if on else "     ") + text

        def done() -> None:
            self.s.catalog.reload()
            changed = self.s.catalog.accounts[acc.id]
            self.s.notify(
                tr(
                    "Счёт {code}: тип «{name}»",
                    code=acc.short,
                    name=type_name(changed.account_class, changed.account_type),
                )
            )
            self.refresh()

        def setter(account_class, account_type):
            def run():
                led, cid = self.s.ledger, self.s.company_id
                if account_class != acc.account_class:
                    led.set_account_class(cid, acc.id, account_class)
                if account_type != acc.account_type:
                    led.set_account_type(cid, acc.id, account_type)
                done()

            return run

        def toggle_contra():
            self.s.ledger.set_account_class(
                self.s.company_id, acc.id, acc.account_class, not acc.contra
            )
            done()

        items: list[MenuAction | None] = []
        by_class: dict[str | None, list[MenuAction | None]] = {}
        for cls, t, text in type_choices():
            entry = (mark((acc.account_class, acc.account_type) == (cls, t), text), setter(cls, t))
            if cls is None:
                items += [None, entry]
            elif t is None:
                by_class[cls] = [entry, None]
                items.append((mark(acc.account_class == cls, class_name(cls)), by_class[cls]))
            else:
                by_class[cls].append(entry)
        items += [None, (mark(acc.contra, tr("Контрсчёт")), toggle_contra)]
        return [None, (tr("Тип счёта"), items)]

    def _account_actions(self, account_id: int) -> list[MenuAction | None]:
        acc = self.s.catalog.accounts.get(account_id)
        if acc is None:
            return []
        actions: list[MenuAction | None] = [
            (tr("Карточка счёта"), lambda: self.open_report.emit("card", acc.id, self.params)),
            (tr("Анализ счёта"), lambda: self.open_report.emit("analysis", acc.id, self.params)),
        ]
        if acc.sc_kinds[0] is not None:
            actions.append(
                (
                    tr("ОСВ по субконто"),
                    lambda: self.open_report.emit("subconto", acc.id, self.params),
                )
            )
        return actions
