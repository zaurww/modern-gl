"""Report pages: ОСВ, карточка счёта, ОСВ по субконто, анализ счёта, план счетов.

Every report = parameters bar + one calm table + footer. Drill-down by double click.
"""

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
    QCheckBox,
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

from modern_gl.application.catalog import AccountInfo
from modern_gl.desktop.account_dialog import AccountDialog
from modern_gl.desktop.session import Session
from modern_gl.desktop.theme import P, fonts
from modern_gl.desktop.widgets import (
    CLASS_ORDER,
    EmptyState,
    PageHeader,
    balance_text,
    button,
    class_icon,
    class_name,
    date_edit,
    edited_date,
    money,
    ru_date,
    type_choices,
    type_name,
)
from modern_gl.domain.accounts import normal_side
from modern_gl.domain.errors import LedgerError
from modern_gl.domain.invoice import CUSTOMS
from modern_gl.domain.money import format_minor
from modern_gl.i18n import tr
from modern_gl.reporting import reports
from modern_gl.reporting.reports import COMMON, IFRS, TAX, OsvRow, SubcontoRow, Turnovers

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

    def describe(self) -> str:
        return (
            f"{ru_date(self.date_from.isoformat())} — {ru_date(self.date_to.isoformat())}"
            f"   ·   {tr(BOOKS[self.book][0])}"
        )


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
# the chart of accounts: its columns, and the least width of the ones that narrow
TYPE_COLUMN, SIDE_COLUMN, SUBCONTO_COLUMN = 2, 3, 4
CHART_NAME_MIN, CHART_TYPE_MIN, CHART_SUBCONTO_MIN = 240, 180, 200


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
            run = button(tr("Сформировать"), "primary", "F5")
            run.clicked.connect(self.refresh)
            bar.addWidget(run)
            bar.addStretch(1)
            root.addLayout(bar)

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
            self.header.subtitle.setText(self.params.describe())
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


class OsvPage(ReportPage):
    key = ("osv",)

    def __init__(self, session: Session, params: ReportParams | None = None) -> None:
        super().__init__(session, tr("Оборотно-сальдовая ведомость"), params)
        self.top_only = QCheckBox(tr("Только основные счета"))
        self.top_only.setToolTip(tr("Скрыть субсчета; суммы основных счетов не меняются"))
        self.top_only.toggled.connect(self.refresh)
        self.header.add_action(self.top_only)
        self.sections = QCheckBox(tr("По разделам"))
        self.sections.setToolTip(tr("Сгруппировать счета по классам с подытогами"))
        self.sections.toggled.connect(self.refresh)
        self.header.add_action(self.sections)
        self.expand = QCheckBox(tr("Развернуть по субконто"))
        self.expand.setToolTip(tr("Показать остатки по первому субконто под каждым счётом"))
        self.expand.toggled.connect(self.refresh)
        self.header.add_action(self.expand)
        self.in_currency = QCheckBox(tr("В валюте"))
        self.in_currency.setToolTip(tr("Показать под валютными счетами суммы в каждой валюте"))
        self.in_currency.toggled.connect(self.refresh)
        self.in_currency.setVisible(session.catalog.has_currency_accounts)
        self.header.add_action(self.in_currency)
        self.refresh()

    def title(self) -> str:
        return tr("ОСВ")

    @staticmethod
    def _with_subconto(rows: list[OsvRow], subconto) -> list[OsvRow]:
        """Insert a row per subconto value (bank, counterparty…) under each account."""
        result = []
        for r in rows:
            result.append(r)
            if r.is_group:
                continue
            for s in subconto.get(r.account_id, []):
                row = OsvRow(name="      " + s.name, depth=r.depth + 1)
                row.add(s)
                result.append(row)
        return result

    @staticmethod
    def _with_currency(rows: list[OsvRow], currency) -> list[OsvRow]:
        """Insert a row per currency (amounts in that currency) under each currency account."""
        result = []
        for r in rows:
            result.append(r)
            for c in currency.get(r.account_id, []) if r.account_id else []:
                row = OsvRow(name=f"      {c.code}  ·  {tr('в валюте')}", depth=r.depth + 1)
                row.add(c)
                result.append(row)
        return result

    def _by_class(self, rows: list[OsvRow]) -> list[OsvRow]:
        """Reorder top-level accounts (with their subaccounts) under class headers."""
        blocks: list[list[OsvRow]] = []
        for r in rows:
            if r.depth == 0:
                blocks.append([r])
            else:
                blocks[-1].append(r)
        groups: dict[str | None, list[list[OsvRow]]] = {}
        for block in blocks:
            acc = self.s.catalog.accounts.get(block[0].account_id)
            groups.setdefault(acc.account_class if acc else None, []).append(block)
        result = []
        for cls in sorted(groups, key=lambda c: CLASS_ORDER.get(c, len(CLASS_ORDER))):
            header = SectionRow(name=class_name(cls), depth=0, is_group=True, account_class=cls)
            for block in groups[cls]:
                header.add(block[0])
            result.append(header)
            for block in groups[cls]:
                result.extend(block)
        return result

    def build(self) -> None:
        osv = reports.trial_balance(
            self.s.conn,
            self.s.company_id,
            self.params.date_from,
            self.params.date_to,
            self.params.layers,
        )
        total = OsvRow(name=tr("Итого"), depth=-1)
        total.add(osv.total)
        columns = [
            Column(
                tr("Счёт"),
                lambda r: "" if isinstance(r, SectionRow) else "      " * max(r.depth, 0) + r.code,
                width=90,
                icon=lambda r: class_icon(r.account_class) if isinstance(r, SectionRow) else None,
            ),
            Column(tr("Наименование"), lambda r: r.name),
            *turnover_columns(
                warn_opening=lambda r: self._side_warning(r) if r.opening_wrong else None,
                warn_closing=lambda r: self._side_warning(r) if r.closing_wrong else None,
            ),
        ]
        shown = [r for r in osv.rows if r.depth == 0] if self.top_only.isChecked() else osv.rows
        if self.expand.isChecked():
            shown = self._with_subconto(shown, osv.subconto)
        if self.in_currency.isChecked():
            shown = self._with_currency(shown, osv.currency)
        if self.sections.isChecked() and shown:
            shown = self._by_class(shown)
        rows = [*shown, total] if shown else []
        sectioned = self.sections.isChecked()
        self.model.set(
            columns,
            rows,
            emphasis=lambda r: (
                r.depth < 0
                or isinstance(r, SectionRow)
                or (r.is_group and not self.top_only.isChecked() and not sectioned)
            ),
            muted=lambda r: r.depth > 0,
            total=lambda r: r.depth < 0,
            section=lambda r: isinstance(r, SectionRow),
        )
        balanced = osv.total.closing_dt == osv.total.closing_ct
        text = (
            tr("Дебет и кредит сходятся  ✓")
            if balanced
            else tr("Внимание: итоги дебета и кредита не сходятся")
        )
        wrong = osv.wrong_side
        if wrong:
            codes = ", ".join(r.code or r.name for r in wrong[:8]) + ("…" if len(wrong) > 8 else "")
            text += "      " + tr(
                "Сальдо не на своей стороне: {codes} — подсвечено красным", codes=codes
            )
        self.footer.setText(text)
        self.footer.setStyleSheet(f"color: {P.red};" if wrong or not balanced else "")

    def drill(self, row: OsvRow) -> None:
        if row and row.account_id:
            self.open_report.emit("card", row.account_id, self.params)

    def _side_warning(self, row: OsvRow) -> str:
        acc = self.s.catalog.accounts.get(row.account_id)
        if acc is None:
            return ""
        side = normal_side(acc.account_class, acc.contra)
        return tr(
            "Сальдо не на своей стороне: для «{cls}» ожидается {side} сальдо",
            cls=class_name(acc.account_class) + (f" · {tr('контрсчёт')}" if acc.contra else ""),
            side=tr("дебетовое") if side == "debit" else tr("кредитовое"),
        )

    def menu_actions(self, row: OsvRow | None) -> list[MenuAction | None]:
        if not row or not row.account_id:
            return []
        return self._account_actions(row.account_id) + self._class_actions(row.account_id)


class AccountReportPage(ReportPage):
    kind = ""
    caption = ""

    def __init__(self, session: Session, account_id: int, params: ReportParams) -> None:
        self.account_id = account_id
        acc = session.catalog.accounts[account_id]
        super().__init__(session, f"{tr(self.caption)} {acc.short}", params)
        self.header.title.setText(f"{tr(self.caption)} {acc.short}")
        self.header.subtitle.setText(acc.name)
        self.key = (self.kind, account_id)
        self.refresh()

    @property
    def account(self):
        return self.s.catalog.accounts[self.account_id]

    def title(self) -> str:
        return f"{tr(self.caption)} {self.account.short}"

    def refresh(self) -> None:
        super().refresh()
        acc = self.account
        name = acc.name if acc.code else ""  # without a code the name is the title already
        self.header.subtitle.setText(
            "   ·   ".join(part for part in (name, self.params.describe()) if part)
        )


def invoice_text(line: reports.CardLine) -> str:
    """An e-qaimə number; a customs declaration is marked as such."""
    if line.invoice_kind == CUSTOMS:
        return f"{tr('bəyannamə')} {line.invoice}"
    return line.invoice


@dataclass
class CardEdge:
    """The first and last rows of a card: the balances, and the turnovers at the end."""

    memo: str
    balance: int
    debit: int | None = None
    credit: int | None = None
    doc_date: str = ""
    number: int = 0
    document_id: int = 0
    corr_code: str = ""
    currency: str = ""
    currency_debit: int | None = None
    currency_credit: int | None = None
    invoice: str = ""
    invoice_kind: str = ""


class CardPage(AccountReportPage):
    kind, caption = "card", "Карточка счёта"

    def build(self) -> None:
        card = reports.account_card(
            self.s.conn,
            self.s.company_id,
            self.account_id,
            self.params.date_from,
            self.params.date_to,
            self.params.layers,
        )
        # within one year the year is in the period already
        one_year = self.params.date_from.year == self.params.date_to.year
        columns = [
            Column(tr("Дата"), lambda ln: self._date(ln.doc_date, one_year), width=1),
            Column("№", lambda ln: ln.number or "", width=1),
            Column(tr("Содержание"), lambda ln: ln.memo),
            Column(tr("Корр. счёт"), lambda ln: ln.corr_code, width=1),
            Column(tr("Дт"), lambda ln: ln.debit, money=True, group=tr("Обороты")),
            Column(tr("Кт"), lambda ln: ln.credit, money=True, group=tr("Обороты")),
            Column(
                tr("Сальдо"),
                lambda ln: balance_text(ln.balance) if ln.balance else "",
                right=True,
            ),
        ]
        if card.currency_closing or self.account.currency:
            columns[4:4] = [
                Column(tr("Валюта"), lambda ln: ln.currency, width=1),
                Column(tr("Дт"), lambda ln: ln.currency_debit, money=True, group=tr("В валюте")),
                Column(tr("Кт"), lambda ln: ln.currency_credit, money=True, group=tr("В валюте")),
            ]
        if any(ln.invoice for ln in card.lines):
            columns.insert(3, Column(tr("E-qaimə"), invoice_text, width=1))
        opening = CardEdge(tr("Сальдо на начало"), card.opening)
        closing = CardEdge(
            tr("Обороты и сальдо на конец"),
            card.closing,
            sum(ln.debit for ln in card.lines),
            sum(ln.credit for ln in card.lines),
        )
        self.model.set(
            columns,
            [opening, *card.lines, closing] if card.lines else [],
            emphasis=lambda ln: ln is closing,
            muted=lambda ln: ln is opening,
            total=lambda ln: ln is closing,
        )
        text = tr(
            "Сальдо на начало: {start}      Сальдо на конец: {end}",
            start=balance_text(card.opening),
            end=balance_text(card.closing),
        )
        in_currency = [
            f"{code} {balance_text(net)}" for code, net in sorted(card.currency_closing.items())
        ]
        if in_currency:
            text += "      " + tr("В валюте на конец: {amounts}", amounts=",  ".join(in_currency))
        self.footer.setText(text)

    @staticmethod
    def _date(iso: str, one_year: bool) -> str:
        text = ru_date(iso) if iso else ""
        return text[:5] if one_year else text

    def drill(self, row) -> None:
        if row is not None and row.document_id:
            self.open_document.emit(row.document_id)


class SubcontoPage(AccountReportPage):
    kind, caption = "subconto", "ОСВ по субконто"

    def build(self) -> None:
        rows = reports.subconto_balance(
            self.s.conn,
            self.s.company_id,
            self.account_id,
            self.params.date_from,
            self.params.date_to,
            self.params.layers,
        )
        total = SubcontoRow(name=tr("Итого"))
        for r in rows:
            total.add(
                Turnovers(
                    r.opening_dt,
                    r.opening_ct,
                    r.turnover_dt,
                    r.turnover_ct,
                    r.closing_dt,
                    r.closing_ct,
                )
            )
        kind_id = self.account.sc_kinds[0]
        kind = self.s.catalog.kinds[kind_id] if kind_id is not None else ""
        columns = [Column(kind, lambda r: r.name)]
        if any(self._tax_id(r) for r in rows):  # counterparties with a VÖEN
            columns.append(Column(tr("VÖEN"), self._tax_id, width=130))
        columns += turnover_columns()
        if any(r.currency_closing for r in rows):  # a foreign partner: USD and EUR apart
            columns.append(Column(tr("В валюте на конец"), self._in_currency, width=200))
        self.model.set(
            columns,
            [*rows, total] if rows else [],
            emphasis=lambda r: r is total,
            total=lambda r: r is total,
        )
        self.footer.setText("")

    @staticmethod
    def _in_currency(row: SubcontoRow) -> str:
        return ",  ".join(
            f"{code} {balance_text(net)}" for code, net in sorted(row.currency_closing.items())
        )

    def _tax_id(self, row: SubcontoRow) -> str:
        if row.value_id is None:
            return ""
        return self.s.catalog.value(row.value_id).tax_id or ""


class AnalysisPage(AccountReportPage):
    kind, caption = "analysis", "Анализ счёта"

    def build(self) -> None:
        rows = reports.account_analysis(
            self.s.conn,
            self.s.company_id,
            self.account_id,
            self.params.date_from,
            self.params.date_to,
            self.params.layers,
        )
        columns = [
            Column(tr("Корр. счёт"), lambda r: r.corr_code, width=1),
            Column(tr("Наименование"), lambda r: r.corr_name),
            Column(tr("Дт"), lambda r: r.debit, money=True, group=tr("Обороты")),
            Column(tr("Кт"), lambda r: r.credit, money=True, group=tr("Обороты")),
        ]
        dt, ct = sum(r.debit for r in rows), sum(r.credit for r in rows)
        total = reports.CorrRow("", tr("Итого"), dt, ct)
        self.model.set(
            columns,
            [*rows, total] if rows else [],
            emphasis=lambda r: r is total,
            total=lambda r: r is total,
        )
        self.footer.setText(
            tr("Оборот Дт: {dt}      Оборот Кт: {ct}", dt=money(dt, False), ct=money(ct, False))
        )

    def drill(self, row) -> None:
        if row is not None and row.corr_id in self.s.catalog.accounts:
            self.open_report.emit("card", row.corr_id, self.params)


class ChartPage(ReportPage):
    key = ("chart",)
    has_period = False
    summary_on_top = False  # key hints, not a summary

    def __init__(self, session: Session) -> None:
        super().__init__(session, tr("План счетов"))
        self.table.setObjectName("list")  # a list, not a report: no rules under rows
        self.table.verticalHeader().setDefaultSectionSize(32)
        self.model.bands = False
        add = button(tr("+ Новый счёт"), "flat", "Ins")
        add.clicked.connect(lambda: self.edit_account(None))
        self.header.add_action(add)
        for keys, fn in (
            ("Ins", lambda: self.edit_account(None)),
            ("F2", lambda: self.edit_account(self._current())),
        ):
            sc = QShortcut(QKeySequence(keys), self)
            sc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            sc.activated.connect(fn)
        self.refresh()

    def title(self) -> str:
        return tr("План счетов")

    def build(self) -> None:
        cat = self.s.catalog
        self.header.subtitle.setText(tr("{n} счетов", n=len(cat.accounts)))

        def subconto(a) -> str:
            kinds = ", ".join(cat.kinds[k] for k in a.sc_kinds if k)
            return "  ·  ".join(t for t in (kinds, tr("в валюте") if a.currency else "") if t)

        def name(a) -> str:
            return a.name if a.active else f"{a.name}  ·  {tr('скрыт')}"

        # what the account is (the type) reads right after its name; the details follow
        columns = [
            Column(tr("Код"), lambda a: ("      " if a.parent_id else "") + a.code, width=100),
            Column(tr("Наименование"), name),
            Column(
                tr("Тип"), self._type_text, width=290, icon=lambda a: class_icon(a.account_class)
            ),
            Column(tr("Сальдо"), self._side_text, width=110),
            Column(tr("Субконто"), subconto, width=280),
        ]
        self.model.set(
            columns,
            list(cat.accounts.values()),
            emphasis=lambda a: a.is_group,
            muted=lambda a: not a.active,
        )
        self.footer.setText(
            tr("Ins — новый счёт   ·   F2 — изменить   ·   двойной щелчок — карточка счёта")
        )

    def drill(self, row) -> None:
        if row is not None:
            self.open_report.emit("card", row.id, month_of(self.s.working_date))

    def _layout_columns(self) -> None:
        hh = self.table.horizontalHeader()
        for i, col in enumerate(self.model.columns):
            if col.width:
                hh.setSectionResizeMode(i, QHeaderView.ResizeMode.Interactive)
                self.table.setColumnWidth(i, col.width)
            else:
                hh.setSectionResizeMode(i, QHeaderView.ResizeMode.Stretch)
        self._fit_columns()

    def _fit_columns(self) -> None:
        """No sideways scrolling: the type and subconto columns narrow with the window
        (their text cut with "…"), and in a narrow one the subconto column goes first:
        it is the least needed, and the account dialog shows it."""
        width = self.table.viewport().width()
        if width <= 0 or not self.model.columns:
            return
        side = self._content_width(SIDE_COLUMN)
        self.table.setColumnWidth(SIDE_COLUMN, side)
        rest = width - self.model.columns[0].width - side
        narrow = rest < CHART_NAME_MIN + CHART_TYPE_MIN + CHART_SUBCONTO_MIN
        share = rest * 2 // 5 if narrow else rest * 3 // 10  # the subconto's room to the type
        self.table.setColumnWidth(TYPE_COLUMN, max(CHART_TYPE_MIN, min(290, share)))
        self.table.setColumnWidth(SUBCONTO_COLUMN, max(CHART_SUBCONTO_MIN, min(280, rest // 4)))
        self.table.setColumnHidden(SUBCONTO_COLUMN, narrow)

    def _current(self):
        idx = self.table.currentIndex()
        return idx.data(Qt.ItemDataRole.UserRole) if idx.isValid() else None

    @staticmethod
    def _type_text(acc) -> str:
        text = type_name(acc.account_class, acc.account_type)
        return f"{text} · {tr('контрсчёт')}" if acc.contra else text

    @staticmethod
    def _side_text(acc) -> str:
        if acc.is_group:
            return ""
        if acc.two_sided:
            return tr("Дт и Кт")
        side = normal_side(acc.account_class, acc.contra)
        names: dict[str | None, str] = {"debit": tr("Дебет"), "credit": tr("Кредит")}
        return names.get(side, "—")

    def edit_account(self, acc, parent_id: int | None = None) -> None:
        dialog = AccountDialog(self.s, acc, parent_id, self)
        if dialog.exec():
            self.s.catalog.reload()
            saved = self.s.catalog.accounts[dialog.saved_id]
            self._after_change(saved.id, tr("Счёт {code} сохранён", code=saved.short))

    def toggle_hidden(self, acc) -> None:
        self.s.ledger.set_account_active(self.s.company_id, acc.id, not acc.active)
        message = "Счёт {code} снова виден" if not acc.active else "Счёт {code} скрыт"
        self._after_change(acc.id, tr(message, code=acc.short))

    def _after_change(self, account_id: int, message: str) -> None:
        self.s.catalog.reload()
        self.refresh()
        row = next((i for i, a in enumerate(self.model.rows) if a.id == account_id), None)
        if row is not None:
            self.table.setCurrentIndex(self.model.index(row, 0))
            self.table.scrollTo(self.model.index(row, 0))
        self.s.notify(message)

    def menu_actions(self, row: AccountInfo | None) -> list[MenuAction | None]:
        if row is None:
            return []
        edit: list[MenuAction | None] = [
            (tr("Изменить…"), lambda: self.edit_account(row)),
            (tr("Добавить субсчёт…"), lambda: self.edit_account(None, row.id)),
            (tr("Показать") if not row.active else tr("Скрыть"), lambda: self.toggle_hidden(row)),
            None,
        ]
        return edit + self._account_actions(row.id) + self._class_actions(row.id)


REPORTS: dict[str, type[AccountReportPage]] = {
    "card": CardPage,
    "subconto": SubcontoPage,
    "analysis": AnalysisPage,
}
