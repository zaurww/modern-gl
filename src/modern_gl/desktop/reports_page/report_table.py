"""The report table (DESIGN.md §4, D127): one for every report and every module table of
figures — columns as wide as their text, the free room on the right."""

from __future__ import annotations

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QTableView

from modern_gl.desktop.reports_page.table import (
    GROUP_GAP,
    NAME_MAX,
    ROW_HEIGHT,
    GroupHeader,
    ReportDelegate,
    ReportModel,
    fit_rows,
)

SelectionMode = QAbstractItemView.SelectionMode
NAME_MIN = 180  # px an account name keeps before it is cut in a narrow window
SAMPLE = 200  # rows measured for a column's width, besides the totals and the headers


class ReportTable(QTableView):
    """Rows chosen whole, no grid of Qt's own (the delegate draws the pale one), not
    edited; several rows selected — Ctrl+C copies them (D104)."""

    def __init__(
        self,
        model: ReportModel,
        selection: SelectionMode = SelectionMode.ExtendedSelection,
    ) -> None:
        super().__init__()
        self.setObjectName("report")
        self.setHorizontalHeader(GroupHeader(self))
        self.setModel(model)
        self.report = model
        self.setItemDelegate(ReportDelegate(self))
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(selection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setShowGrid(False)
        self.setWordWrap(False)
        self.verticalHeader().hide()
        self.verticalHeader().setDefaultSectionSize(ROW_HEIGHT)
        self.widths: dict[int, int] = {}
        self._measured: dict[int, int] = {}  # content_width of a column, for these rows
        for signal in (
            model.modelReset,
            model.layoutChanged,
            model.dataChanged,
            model.rowsInserted,
            model.rowsRemoved,
        ):
            signal.connect(lambda *_: self._measured.clear())
        # a narrow window: amounts give up some width
        self.viewport().installEventFilter(self)

    def layout_columns(self) -> None:
        """Every column as wide as its widest text, so the amounts stand right after the
        names and the free room stays empty on the right (Jon Moon: the eye must not
        travel across a blank to find the number). A name keeps at most NAME_MAX."""
        hh = self.horizontalHeader()
        hh.setStretchLastSection(False)
        columns = self.report.columns
        self.widths = {}
        for i, col in enumerate(columns):
            hh.setSectionResizeMode(i, QHeaderView.ResizeMode.Interactive)
            width = self.content_width(i)
            if col.money or col.right:
                width += QFontMetrics(self.font()).horizontalAdvance(")")
            if col.group and (i == 0 or columns[i - 1].group != col.group):
                width += GROUP_GAP
            self.widths[i] = width if col.width or col.money or col.right else min(width, NAME_MAX)
        self._fit_groups()
        fit_rows(self, self.report)
        hh.updateGeometry()
        self.fit_columns()

    def _fit_groups(self) -> None:
        """A group caption wider than its columns widens them."""
        columns, metrics = self.report.columns, self.horizontalHeader().fontMetrics()
        for group in {c.group for c in columns if c.group}:
            members = [i for i, c in enumerate(columns) if c.group == group]
            need = metrics.horizontalAdvance(group) + GROUP_GAP + 22
            short = need - sum(self.widths[i] for i in members)
            for i in members:
                self.widths[i] += max(0, short) // len(members) + 1

    def content_width(self, column: int) -> int:
        """The widest text of a column (bold totals included) or its caption. Measured
        on the rows that set it — the first SAMPLE, the totals and the headers — not on
        every row: a year's card has thousands, and they were all measured on each
        refresh. Kept per column until the model changes."""
        if column in self._measured:
            return self._measured[column]
        bold = self.font()
        bold.setBold(True)
        metrics = QFontMetrics(bold)
        widest = self.horizontalHeader().fontMetrics().horizontalAdvance(self.report.title(column))
        icon = self.report.columns[column].icon is not None
        for r in self._sample_rows():
            text = self.report.data(self.report.index(r, column), Qt.ItemDataRole.DisplayRole)
            widest = max(widest, metrics.horizontalAdvance(str(text or "")))
        width = widest + 28 + (24 if icon else 0)  # the cell padding of the theme
        self._measured[column] = width
        return width

    def _sample_rows(self) -> list[int]:
        model = self.report
        first = list(range(min(model.rowCount(), SAMPLE)))
        marked = [
            r
            for r, row in enumerate(model.rows[SAMPLE:], SAMPLE)
            if model.total(row) or model.section(row)
        ]
        return first + marked

    def fit_columns(self) -> None:
        """In a narrow window the names give up width first (cut with "…"), down to
        NAME_MIN; then the table scrolls sideways. In a wide one the free room stays on
        the right."""
        widths = self.widths
        if not widths:
            return
        columns = self.report.columns
        names = [i for i, c in enumerate(columns) if not (c.width or c.money or c.right)]
        others = sum(w for i, w in widths.items() if i not in names)
        room = (self.viewport().width() - others) // max(1, len(names))
        fitted = {
            i: max(min(width, NAME_MIN), min(width, room)) if i in names else width
            for i, width in widths.items()
        }
        for i, width in fitted.items():
            self.setColumnWidth(i, width)

    def eventFilter(self, watched, event) -> bool:
        if watched is self.viewport() and event.type() == QEvent.Type.Resize:
            self.fit_columns()
        return super().eventFilter(watched, event)
