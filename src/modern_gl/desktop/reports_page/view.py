"""What every report shares: its columns, model, header, delegate and the page with
period, book and context menu."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Any

from PySide6.QtCore import (
    Qt,
    Signal,
)
from PySide6.QtGui import QAction, QCursor, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QMenu,
    QStackedLayout,
    QVBoxLayout,
    QWidget,
)

from modern_gl.desktop.page import PageWidget
from modern_gl.desktop.period_field import PeriodField
from modern_gl.desktop.reports_page.column_choice import ColumnChoice
from modern_gl.desktop.reports_page.export import copy_to_clipboard, save_to_excel
from modern_gl.desktop.reports_page.report_table import ReportTable
from modern_gl.desktop.reports_page.table import (
    Column,
    ReportModel,
)
from modern_gl.desktop.session import Session
from modern_gl.desktop.widgets import (
    EmptyState,
    MenuItem,
    PageHeader,
    class_name,
    ru_date,
    type_choices,
    type_name,
)
from modern_gl.domain.dates import month_days
from modern_gl.domain.errors import LedgerError
from modern_gl.i18n import tr
from modern_gl.infrastructure.db import Connection
from modern_gl.reporting.reports import COMMON, IFRS, TAX

BOOKS = [("Общий учёт", COMMON), ("МСФО", IFRS), ("Налоговый учёт", TAX)]

# (group over a Dt/Kt pair, side, attribute)
TURNOVER_COLUMNS = [
    ("Сальдо на начало", "Дт", "opening_dt"),
    ("Сальдо на начало", "Кт", "opening_ct"),
    ("Обороты", "Дт", "turnover_dt"),
    ("Обороты", "Кт", "turnover_ct"),
    ("Сальдо на конец", "Дт", "closing_dt"),
    ("Сальдо на конец", "Кт", "closing_ct"),
]


@dataclass
class ReportParams:
    date_from: date
    date_to: date
    book: int = 0  # index in BOOKS
    # a card of one counterparty or contract, opened from ОСВ по субконто: the values
    # from the first subconto on (None = «не указано»)
    subconto: tuple[int | None, ...] = ()
    # and of one e-qaimə of it ("" — the lines without one; D110)
    invoice: str | None = None

    @property
    def layers(self) -> tuple[str, ...]:
        return BOOKS[self.book][1]

    def describe(self, book: bool = True) -> str:
        period = f"{ru_date(self.date_from.isoformat())} — {ru_date(self.date_to.isoformat())}"
        return f"{period}   ·   {tr(BOOKS[self.book][0])}" if book else period


def month_of(d: date) -> ReportParams:
    return ReportParams(*month_days(d.year, d.month))


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


class ReportPage(PageWidget):
    """Base: header, parameters, table/empty state, footer."""

    open_document = Signal(int)
    open_report = Signal(str, int, object)  # kind, account id, ReportParams

    key: tuple[Any, ...] = ("report",)  # what opens the page again; [0] is its kind
    has_period = True
    choosable_columns = True  # «Колонки…»: a page with a choice of its own says no
    has_book = True  # the book choice, when the company keeps parallel books
    summary_on_top = True
    table_class = ReportTable  # the plan of accounts narrows its columns its own way

    def __init__(self, session: Session, title: str, params: ReportParams | None = None) -> None:
        super().__init__()
        self.setObjectName("page")
        self.s = session
        self.params = params or month_of(session.working_date)
        root = QVBoxLayout(self)
        root.setContentsMargins(40, 30, 40, 24)
        root.setSpacing(16)

        self.header = PageHeader(title, "")
        self.header.more(self.more_items)
        root.addWidget(self.header)

        self._build_period_bar(root)
        self._build_table()

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
            ("Ctrl+C", lambda: copy_to_clipboard(self)),
            ("Return", self._drill_current),
            ("Enter", self._drill_current),
        ):
            sc = QShortcut(QKeySequence(keys), self)
            sc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            sc.activated.connect(fn)

    def _build_period_bar(self, root: QVBoxLayout) -> None:
        """Period and book, for the reports that have them."""
        if self.has_period:
            bar = QHBoxLayout()
            bar.setSpacing(8)
            # one field for the period, the same on every report (D105); a new period
            # is shown at once
            self.period = PeriodField(
                (self.params.date_from, self.params.date_to), self.s.working_date
            )
            self.period.changed.connect(self.refresh)
            self.book = QComboBox()
            for name, _ in BOOKS:
                self.book.addItem(tr(name))
            self.book.setCurrentIndex(self.params.book)
            self.book.setFixedWidth(170)
            self.book.currentIndexChanged.connect(lambda _i: self.refresh())
            for caption, w in ((tr("Период"), self.period), (tr("Книга"), self.book)):
                label = QLabel(caption)
                label.setObjectName("secondary")
                bar.addWidget(label)
                bar.addWidget(w)
                bar.addSpacing(6)
                if w is self.book and not (self.s.parallel_books and self.has_book):  # D63
                    label.hide()
                    w.hide()
            bar.addStretch(1)  # no «Сформировать»: a change shows at once, F5 reads again
            root.addLayout(bar)
            self.bar = bar

    def add_to_bar(self, *widgets: QWidget, gap: int = 6) -> None:
        """A page's own choices in the bar, after the period and the book (DESIGN.md 2)."""
        for w in widgets:
            self.bar.insertWidget(self.bar.count() - 1, w)
            self.bar.insertSpacing(self.bar.count() - 1, gap)

    def _build_table(self) -> None:
        self.model = ReportModel()
        self.table = self.table_class(self.model)
        # a right click on the captions: which columns to show
        captions = self.table.horizontalHeader()
        captions.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        captions.customContextMenuRequested.connect(
            lambda pos: self.choose_columns(captions.mapToGlobal(pos))
        )
        if self.choosable_columns:
            self.model.shown = lambda col: self.columns_choice().shown(col)
        self.table.doubleClicked.connect(lambda idx: self.drill(idx.data(Qt.ItemDataRole.UserRole)))
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._context_menu)

    # ---- to implement ----------------------------------------------------------------

    def build(self) -> None:
        """Read and show the report on the window's thread (a page with fetch/show)."""
        self.present(self.fetch(self.s.conn))

    def fetch(self, conn: Connection) -> Any:
        """What the report reads — on `conn`, which is a worker's own connection for a
        large company (desktop.background): only SQL here, no widgets."""
        raise NotImplementedError

    def present(self, data: Any) -> None:
        """Fill the page with what fetch() read."""
        raise NotImplementedError

    def job(self) -> Callable[[Connection], Any]:
        """fetch() with what it needs from the widgets taken now, on the window's thread
        (a worker must not touch them); a page whose fetch reads widgets overrides it."""
        return self.fetch

    def drill(self, row: Any) -> None:
        pass

    def menu_actions(self, row: Any) -> list[MenuAction | None]:
        return []

    def title(self) -> str:
        raise NotImplementedError

    def export_title(self) -> str:
        """The name of the report in Excel (D104): the page's, a page with views — the view's."""
        return self.title()

    def more_items(self) -> list[MenuItem]:
        """«⋯» of every report: to Excel; a page adds its own in front."""
        columns: list[MenuItem] = [
            (tr("Колонки…"), lambda: self.choose_columns(QCursor.pos())),
            None,
        ]
        return [
            *(columns if self.choosable_columns else []),
            (tr("В Excel…"), lambda: save_to_excel(self)),
            (tr("Копировать для Excel  Ctrl+C"), lambda: copy_to_clipboard(self)),
        ]

    # ---- common ----------------------------------------------------------------------

    def columns_choice(self) -> ColumnChoice:
        """Remembered for the kind of report (the first part of its key)."""
        return ColumnChoice(self.key[0], self.refresh)

    def choose_columns(self, at) -> None:
        if self.choosable_columns:
            self.columns_choice().popup(self.model.all_columns, self, at)

    def focus_table(self) -> None:
        self.table.setFocus()

    def refresh(self) -> None:
        if self.has_period:
            self.params = ReportParams(
                *self.period.period(),
                self.book.currentIndex(),
                self.params.subconto,
                self.params.invoice,
            )
            book = self.s.parallel_books and self.has_book
            self.header.subtitle.setText(self.params.describe(book))
        if type(self).fetch is ReportPage.fetch:  # builds by itself (the chart)
            try:
                self.build()
            except LedgerError as e:
                self.s.notify(str(e))
                return
            self._shown()
            return
        self.s.read(self, self.job(), self._show_read, lambda e: self.s.notify(str(e)))

    def _show_read(self, data: Any) -> None:
        try:
            self.present(data)
        except LedgerError as e:
            self.s.notify(str(e))
            return
        self._shown()

    def _shown(self) -> None:
        self.stack.setCurrentWidget(self.table if self.model.rows else self.empty)
        self.table.layout_columns()
        self.footer.setVisible(bool(self.footer.text()))

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
