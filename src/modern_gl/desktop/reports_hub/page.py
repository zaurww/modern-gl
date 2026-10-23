"""«Отчёты» (D111): every report on one page, by group — a name and a line of what it
shows; a search on top (ə = e: `fold`), Enter opens the first found; «Недавние» beside;
a star pins a report to the sidebar. The page reads nothing from the company and writes
nothing to it: what is pinned and opened lately is the user's (`QSettings`)."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from modern_gl.desktop.home_page.rows import Line, Section, heading
from modern_gl.desktop.reports_hub import catalog
from modern_gl.desktop.reports_hub.catalog import Report
from modern_gl.desktop.reports_hub.tiles import ReportTile
from modern_gl.desktop.session import Session
from modern_gl.desktop.widgets import PageHeader
from modern_gl.i18n import tr

COLUMNS = 2  # tiles side by side in a group
CATALOG_WIDTH, SIDE_WIDTH = 720, 240
NEXT = (Qt.Key.Key_Down, Qt.Key.Key_Right)
BACK = (Qt.Key.Key_Up, Qt.Key.Key_Left)


def place(grid: QGridLayout, tiles: list[ReportTile]) -> None:
    """The tiles not hidden side by side, row by row: found ones close up."""
    for tile in tiles:
        grid.removeWidget(tile)
    for i, tile in enumerate(t for t in tiles if t.matched):
        grid.addWidget(tile, i // COLUMNS, i % COLUMNS)
    for tile in tiles:  # in the group's box by now: none of them shows as a window
        tile.setVisible(tile.matched)


class ReportsPage(QWidget):
    key = catalog.HUB
    open_report = Signal(str)  # a report's id: the window opens it (and remembers it)
    pins_changed = Signal()

    def __init__(self, session: Session) -> None:
        super().__init__()
        self.setObjectName("page")
        self.s = session
        self.reports = catalog.shown(session.stock_only, session.read_only, session.parallel_books)
        self.tiles: list[ReportTile] = []
        self.groups: list[tuple[QWidget, QGridLayout, list[ReportTile]]] = []
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        outer.addWidget(scroll)
        sheet = QWidget()
        sheet.setObjectName("page")
        scroll.setWidget(sheet)
        row = QHBoxLayout(sheet)
        row.setContentsMargins(40, 30, 40, 24)
        row.setSpacing(48)
        row.addStretch(1)
        row.addWidget(self._build_catalog(), 6)
        row.addWidget(self._build_side(), 0, Qt.AlignmentFlag.AlignTop)
        row.addStretch(1)
        self.refresh()

    def title(self) -> str:
        return tr("Отчёты")

    def is_dirty(self) -> bool:
        return False

    # ---- the parts ---------------------------------------------------------------------

    def _build_catalog(self) -> QWidget:
        column = QWidget()
        column.setMaximumWidth(CATALOG_WIDTH)
        column.setMinimumWidth(min(CATALOG_WIDTH, 460))
        lay = QVBoxLayout(column)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.header = PageHeader(tr("Отчёты"), tr("Отчётов: {n}", n=len(self.reports)))
        self.search = QLineEdit()
        self.search.setObjectName("search")
        self.search.setPlaceholderText(tr("Найти отчёт"))
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(lambda _text: self._filter())
        self.search.returnPressed.connect(self.open_first)
        self.search.installEventFilter(self)
        self.header.add_action(self.search)
        lay.addWidget(self.header)
        pinned = set(catalog.pinned())
        for group in catalog.GROUPS:
            reports = [r for r in self.reports if r.group == group]
            if reports:
                lay.addWidget(self._group(group, reports, pinned))
        self.nothing = QLabel(tr("Такого отчёта нет — попробуйте другое слово"))
        self.nothing.setObjectName("secondary")
        self.nothing.setContentsMargins(0, 24, 0, 0)
        self.nothing.hide()
        lay.addWidget(self.nothing)
        lay.addStretch(1)
        return column

    def _group(self, group: str, reports: list[Report], pinned: set[str]) -> QWidget:
        box = QWidget()
        lay = QVBoxLayout(box)
        lay.setContentsMargins(0, 8, 0, 0)
        lay.setSpacing(4)
        lay.addWidget(heading(tr(group)))
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(2)
        for c in range(COLUMNS):
            grid.setColumnStretch(c, 1)
        tiles = []
        for report in reports:
            tile = ReportTile(report, report.id in pinned)
            tile.opened.connect(self.open_report.emit)
            tile.pin_toggled.connect(self._pin)
            tiles.append(tile)
        lay.addLayout(grid)
        place(grid, tiles)
        self.tiles += tiles
        self.groups.append((box, grid, tiles))
        return box

    def _build_side(self) -> QWidget:
        side = QWidget()
        side.setFixedWidth(SIDE_WIDTH)
        self.side = QVBoxLayout(side)
        self.side.setContentsMargins(0, 64, 0, 0)  # level with the first group
        self.side.setSpacing(0)
        self.recent_section: Section | None = None
        return side

    # ---- what is shown -----------------------------------------------------------------

    def refresh(self) -> None:
        """«Недавние» read again (a report opened elsewhere is in it too)."""
        if self.recent_section is not None:
            self.side.removeWidget(self.recent_section)
            self.recent_section.hide()
            self.recent_section.deleteLater()
        section = Section(tr("Недавние"))
        shown = {r.id: r for r in self.reports}
        recent = [shown[i] for i in catalog.recent() if i in shown]
        for report in recent:
            line = Line(tr(report.title))
            line.opens(lambda r=report.id: self.open_report.emit(r))
            section.add(line)
        if not recent:
            section.empty(tr("Здесь будут отчёты, открытые последними"))
            section.lines[0].text.setWordWrap(True)
        self.side.addWidget(section)
        self.recent_section = section

    def show_pins(self) -> None:
        """The stars as the sidebar has them (unpinned there, or from another window)."""
        pinned = set(catalog.pinned())
        for tile in self.tiles:
            if tile.pinned != (tile.report.id in pinned):
                tile.pinned = not tile.pinned
                tile.show_star()

    def found(self) -> list[ReportTile]:
        return [t for t in self.tiles if t.matched]

    def _filter(self) -> None:
        query = self.search.text()
        for box, grid, tiles in self.groups:
            for tile in tiles:
                tile.matched = catalog.matches(tile.report, query)
            place(grid, tiles)
            box.setVisible(any(t.matched for t in tiles))
        self.nothing.setVisible(not self.found())

    def open_first(self) -> None:
        found = self.found()
        if found:
            self.open_report.emit(found[0].report.id)

    def _pin(self, report_id: str, on: bool) -> None:
        catalog.set_pinned(report_id, on)
        self.pins_changed.emit()

    # ---- the keyboard ------------------------------------------------------------------

    def focus_table(self) -> None:
        """Shown: the cursor in the search, a few letters and Enter open a report."""
        self.search.setFocus()
        self.search.selectAll()

    def eventFilter(self, watched, event) -> bool:
        """↓ in the search: the first report found."""
        if (
            watched is self.search
            and isinstance(event, QKeyEvent)
            and event.type() == QKeyEvent.Type.KeyPress
            and event.key() == Qt.Key.Key_Down
            and self.found()
        ):
            self.found()[0].setFocus()
            return True
        return super().eventFilter(watched, event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        """↓ → the next tile, ↑ ← the one before; above the first — the search."""
        found = self.found()
        current = next((i for i, t in enumerate(found) if t.hasFocus()), None)
        if current is not None and event.key() in NEXT + BACK:
            step = 1 if event.key() in NEXT else -1
            at = current + step
            if at < 0:
                self.search.setFocus()
            elif at < len(found):
                found[at].setFocus()
            return
        super().keyPressEvent(event)
