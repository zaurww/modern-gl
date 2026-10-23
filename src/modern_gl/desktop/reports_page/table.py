"""The table every report shows: its columns, the model, the grouped header and the
delegate that draws the figures."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    QPersistentModelIndex,
    QRect,
    QRectF,
    QSettings,
    QSize,
    Qt,
)
from PySide6.QtGui import QColor, QFontMetrics, QPainter
from PySide6.QtWidgets import (
    QHeaderView,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableView,
)

from modern_gl.desktop.theme import P, fonts
from modern_gl.domain.money import format_minor
from modern_gl.reporting.reports import OsvRow

RIGHT = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter

LEFT = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter

# Reports follow Jon Moon (Clarity & Impact): a table as wide as its content, so the
# amounts stand next to the names; whitespace instead of rules (soft zebra rows only
# when the user turns them on, D103); a dash under the units for nothing; negatives in
# brackets that hang right.
DASH = "–"

NAME_MAX = 380  # px: a longer name is cut with "…" (the whole of it shows under the mouse)

GROUP_GAP = 24  # px of air in front of each Dt/Kt pair

BAND = 1  # rows in a band: plain zebra

ZEBRA_SETTING = "reports/zebra"  # «Оформление → Полосы в таблицах», off by default (D103)

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
    fill: bool = False  # takes the free room: the table reaches the right edge (bank)
    # the amount (minor units) behind a column of text, for Excel (D104); a money column
    # needs none
    value: Callable[[Any], int | None] | None = None
    # a figure of one period beside others (a month): the row is selected whole, the
    # current cell of such a column is outlined — a double click opens that period
    cell: bool = False


def zebra() -> bool:
    return bool(QSettings().value(ZEBRA_SETTING, False, type=bool))


def set_zebra(on: bool) -> None:
    QSettings().setValue(ZEBRA_SETTING, on)


def figure(minor: int | None) -> str:
    """An amount in a report: nothing is a dash, a negative is in brackets."""
    if minor is None:
        return ""
    if minor == 0:
        return DASH
    return f"({format_minor(-minor)})" if minor < 0 else format_minor(minor)


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
        run, bands = 0, self.bands and zebra()
        for r in rows:
            if not bands or self.total(r) or self.section(r):
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
            if col.cell and index == self.table.currentIndex():
                painter.setPen(QColor(P.accent))
                painter.setRenderHint(QPainter.RenderHint.Antialiasing)
                painter.drawRoundedRect(QRectF(opt.rect).adjusted(2.5, 2.5, -2.5, -2.5), 4, 4)
            painter.restore()
        else:
            super().paint(painter, option, index)
        if model.total(row):
            painter.save()
            painter.setPen(QColor(P.text))
            painter.drawLine(option.rect.topLeft(), option.rect.topRight())
            painter.restore()
