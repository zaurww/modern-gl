"""Report pages: ОСВ, карточка счёта, ОСВ по субконто, анализ счёта, план счетов.

Every report = parameters bar + one calm table + footer. Drill-down by double click.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Any

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, Signal
from PySide6.QtGui import QAction, QColor, QFont, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMenu,
    QStackedLayout,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from modern_gl.desktop.session import Session
from modern_gl.desktop.theme import P
from modern_gl.desktop.widgets import (
    EmptyState,
    PageHeader,
    balance_text,
    button,
    date_edit,
    money,
    ru_date,
)
from modern_gl.domain.errors import LedgerError
from modern_gl.reporting import reports
from modern_gl.reporting.reports import COMMON, IFRS, TAX, OsvRow, SubcontoRow, Turnovers

BOOKS = [("Общий учёт", COMMON), ("МСФО", IFRS), ("Налоговый учёт", TAX)]
RIGHT = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
LEFT = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
TURNOVER_COLUMNS = [
    ("Сальдо нач. Дт", "opening_dt"),
    ("Сальдо нач. Кт", "opening_ct"),
    ("Оборот Дт", "turnover_dt"),
    ("Оборот Кт", "turnover_ct"),
    ("Сальдо кон. Дт", "closing_dt"),
    ("Сальдо кон. Кт", "closing_ct"),
]


@dataclass
class Column:
    title: str
    get: Callable[[Any], Any]
    money: bool = False
    width: int = 0  # 0 = stretch


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
            f"   ·   {BOOKS[self.book][0]}"
        )


def month_of(d: date) -> ReportParams:
    nxt = date(d.year + d.month // 12, d.month % 12 + 1, 1)
    return ReportParams(date(d.year, d.month, 1), date.fromordinal(nxt.toordinal() - 1))


def turnover_columns() -> list[Column]:
    return [
        Column(t, (lambda r, a=a: getattr(r, a)), money=True, width=120)
        for t, a in TURNOVER_COLUMNS
    ]


class ReportModel(QAbstractTableModel):
    def __init__(self) -> None:
        super().__init__()
        self.columns: list[Column] = []
        self.rows: list[Any] = []
        self.emphasis: Callable[[Any], bool] = lambda r: False
        self.muted: Callable[[Any], bool] = lambda r: False

    def set(self, columns, rows, emphasis=None, muted=None) -> None:
        self.beginResetModel()
        self.columns, self.rows = columns, rows
        self.emphasis = emphasis or (lambda r: False)
        self.muted = muted or (lambda r: False)
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: B008
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()) -> int:  # noqa: B008
        return 0 if parent.isValid() else len(self.columns)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation != Qt.Orientation.Horizontal:
            return None
        if role == Qt.ItemDataRole.DisplayRole:
            return self.columns[section].title
        if role == Qt.ItemDataRole.TextAlignmentRole:
            return RIGHT if self.columns[section].money else LEFT
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        row, col = self.rows[index.row()], self.columns[index.column()]
        if role == Qt.ItemDataRole.DisplayRole:
            value = col.get(row)
            return money(value) if col.money else ("" if value is None else str(value))
        if role == Qt.ItemDataRole.TextAlignmentRole:
            return RIGHT if col.money else LEFT
        if role == Qt.ItemDataRole.FontRole and self.emphasis(row):
            f = QFont()
            f.setWeight(QFont.Weight.DemiBold)
            return f
        if role == Qt.ItemDataRole.ForegroundRole:
            if self.muted(row):
                return QColor(P.secondary)
            if col.money and isinstance(v := col.get(row), int) and v < 0:
                return QColor(P.red)
        if role == Qt.ItemDataRole.UserRole:
            return row
        return None


class ReportPage(QWidget):
    """Base: header, parameters, table/empty state, footer."""

    open_document = Signal(int)
    open_report = Signal(str, str, object)  # kind, account code, ReportParams

    has_period = True

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
                self.book.addItem(name)
            self.book.setCurrentIndex(self.params.book)
            for caption, w, width in (
                ("Период с", self.date_from, 130),
                ("по", self.date_to, 130),
                ("Книга", self.book, 170),
            ):
                label = QLabel(caption)
                label.setObjectName("secondary")
                w.setFixedWidth(width)
                bar.addWidget(label)
                bar.addWidget(w)
                bar.addSpacing(6)
            run = button("Сформировать", "primary", "F5")
            run.clicked.connect(self.refresh)
            bar.addWidget(run)
            bar.addStretch(1)
            root.addLayout(bar)

        self.model = ReportModel()
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setShowGrid(False)
        self.table.setWordWrap(False)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(32)
        self.table.horizontalHeader().setHighlightSections(False)
        self.table.doubleClicked.connect(lambda idx: self.drill(idx.data(Qt.ItemDataRole.UserRole)))
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._context_menu)

        self.empty = EmptyState("○", "Нет данных", "За выбранный период движений не было.")
        self.stack = QStackedLayout()
        self.stack.addWidget(self.table)
        self.stack.addWidget(self.empty)
        root.addLayout(self.stack, 1)

        self.footer = QLabel()
        self.footer.setObjectName("secondary")
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

    def menu_actions(self, row: Any) -> list[tuple[str, Callable[[], None]]]:
        return []

    # ---- common ----------------------------------------------------------------------

    def is_dirty(self) -> bool:
        return False

    def focus_table(self) -> None:
        self.table.setFocus()

    def refresh(self) -> None:
        if self.has_period:
            self.params = ReportParams(
                self.date_from.date().toPython(),
                self.date_to.date().toPython(),
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

    def _layout_columns(self) -> None:
        hh = self.table.horizontalHeader()
        for i, col in enumerate(self.model.columns):
            if col.width:
                hh.setSectionResizeMode(i, QHeaderView.ResizeMode.Interactive)
                self.table.setColumnWidth(i, col.width)
            else:
                hh.setSectionResizeMode(i, QHeaderView.ResizeMode.Stretch)

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
        for text, fn in actions:
            act = QAction(text, menu)
            act.triggered.connect(fn)
            menu.addAction(act)
        menu.exec(self.table.viewport().mapToGlobal(pos))

    def _account_actions(self, code: str) -> list[tuple[str, Callable[[], None]]]:
        acc = self.s.catalog.by_code.get(code)
        if acc is None:
            return []
        actions = [
            ("Карточка счёта", lambda: self.open_report.emit("card", code, self.params)),
            ("Анализ счёта", lambda: self.open_report.emit("analysis", code, self.params)),
        ]
        if acc.sc_kinds[0] is not None:
            actions.append(
                ("ОСВ по субконто", lambda: self.open_report.emit("subconto", code, self.params))
            )
        return actions


class OsvPage(ReportPage):
    key = ("osv",)

    def __init__(self, session: Session, params: ReportParams | None = None) -> None:
        super().__init__(session, "Оборотно-сальдовая ведомость", params)
        self.refresh()

    def title(self) -> str:
        return "ОСВ"

    def build(self) -> None:
        osv = reports.trial_balance(
            self.s.conn,
            self.s.company_id,
            self.params.date_from,
            self.params.date_to,
            self.params.layers,
        )
        total = OsvRow(name="Итого", depth=-1)
        total.add(osv.total)
        columns = [
            Column("Счёт", lambda r: ("      " * max(r.depth, 0)) + r.code, width=90),
            Column("Наименование", lambda r: r.name),
            *turnover_columns(),
        ]
        rows = [*osv.rows, total] if osv.rows else []
        self.model.set(
            columns, rows, emphasis=lambda r: r.is_group or r.depth < 0, muted=lambda r: r.depth > 0
        )
        balanced = osv.total.closing_dt == osv.total.closing_ct
        self.footer.setText(
            "Дебет и кредит сходятся  ✓"
            if balanced
            else "Внимание: итоги дебета и кредита не сходятся"
        )

    def drill(self, row: OsvRow) -> None:
        if row and row.code:
            self.open_report.emit("card", row.code, self.params)

    def menu_actions(self, row: OsvRow):
        return self._account_actions(row.code) if row and row.code else []


class AccountReportPage(ReportPage):
    kind = ""
    caption = ""

    def __init__(self, session: Session, code: str, params: ReportParams) -> None:
        self.code = code
        acc = session.catalog.by_code[code]
        super().__init__(session, f"{self.caption} {code}", params)
        self.header.title.setText(f"{self.caption} {code}")
        self.header.subtitle.setText(acc.name)
        self.key = (self.kind, code)
        self.refresh()

    def title(self) -> str:
        return f"{self.caption} {self.code}"

    def refresh(self) -> None:
        super().refresh()
        acc = self.s.catalog.by_code[self.code]
        self.header.subtitle.setText(f"{acc.name}   ·   {self.params.describe()}")


class CardPage(AccountReportPage):
    kind, caption = "card", "Карточка счёта"

    def build(self) -> None:
        card = reports.account_card(
            self.s.conn,
            self.s.company_id,
            self.code,
            self.params.date_from,
            self.params.date_to,
            self.params.layers,
        )
        columns = [
            Column("Дата", lambda ln: ru_date(ln.doc_date), width=100),
            Column("№", lambda ln: ln.number, width=60),
            Column("Содержание", lambda ln: ln.memo),
            Column("Корр. счёт", lambda ln: ln.corr_code, width=100),
            Column("Дебет", lambda ln: ln.debit, money=True, width=130),
            Column("Кредит", lambda ln: ln.credit, money=True, width=130),
            Column("Сальдо", lambda ln: balance_text(ln.balance), width=150),
        ]
        self.model.set(columns, card.lines)
        self.footer.setText(
            f"Сальдо на начало: {balance_text(card.opening)}"
            f"      Сальдо на конец: {balance_text(card.closing)}"
        )

    def drill(self, line) -> None:
        if line is not None:
            self.open_document.emit(line.document_id)


class SubcontoPage(AccountReportPage):
    kind, caption = "subconto", "ОСВ по субконто"

    def build(self) -> None:
        rows = reports.subconto_balance(
            self.s.conn,
            self.s.company_id,
            self.code,
            self.params.date_from,
            self.params.date_to,
            self.params.layers,
        )
        total = SubcontoRow(name="Итого")
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
        kind = self.s.catalog.kinds[self.s.catalog.by_code[self.code].sc_kinds[0]]
        columns = [Column(kind, lambda r: r.name), *turnover_columns()]
        self.model.set(
            columns,
            [*rows, total] if rows else [],
            emphasis=lambda r: r.value_id is None and r.name == "Итого",
        )
        self.footer.setText("")


class AnalysisPage(AccountReportPage):
    kind, caption = "analysis", "Анализ счёта"

    def build(self) -> None:
        rows = reports.account_analysis(
            self.s.conn,
            self.s.company_id,
            self.code,
            self.params.date_from,
            self.params.date_to,
            self.params.layers,
        )
        columns = [
            Column("Корр. счёт", lambda r: r.corr_code, width=110),
            Column("Наименование", lambda r: r.corr_name),
            Column("С кредита счетов (Дт)", lambda r: r.debit, money=True, width=170),
            Column("В дебет счетов (Кт)", lambda r: r.credit, money=True, width=170),
        ]
        self.model.set(columns, rows)
        dt, ct = sum(r.debit for r in rows), sum(r.credit for r in rows)
        self.footer.setText(f"Оборот Дт: {money(dt, False)}      Оборот Кт: {money(ct, False)}")

    def drill(self, row) -> None:
        if row is not None and row.corr_code in self.s.catalog.by_code:
            self.open_report.emit("card", row.corr_code, self.params)


class ChartPage(ReportPage):
    key = ("chart",)
    has_period = False
    KIND = {"A": "Активный", "P": "Пассивный", "AP": "Активно-пассивный"}

    def __init__(self, session: Session) -> None:
        super().__init__(session, "План счетов")
        self.header.subtitle.setText(f"{len(session.catalog.accounts)} счетов")
        self.refresh()

    def title(self) -> str:
        return "План счетов"

    def build(self) -> None:
        cat = self.s.catalog

        def subconto(a) -> str:
            return ", ".join(cat.kinds[k] for k in a.sc_kinds if k)

        columns = [
            Column("Код", lambda a: ("      " if a.parent_id else "") + a.code, width=110),
            Column("Наименование", lambda a: a.name),
            Column("Вид", lambda a: self.KIND[a.kind], width=150),
            Column("Субконто", subconto, width=300),
        ]
        self.model.set(columns, list(cat.accounts.values()), emphasis=lambda a: a.is_group)
        self.footer.setText("Двойной щелчок — карточка счёта за текущий месяц")

    def drill(self, acc) -> None:
        if acc is not None:
            self.open_report.emit("card", acc.code, month_of(self.s.working_date))

    def menu_actions(self, acc):
        return self._account_actions(acc.code) if acc is not None else []


REPORTS: dict[str, type[AccountReportPage]] = {
    "card": CardPage,
    "subconto": SubcontoPage,
    "analysis": AnalysisPage,
}
