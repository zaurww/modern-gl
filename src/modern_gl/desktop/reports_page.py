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
    Qt,
    Signal,
)
from PySide6.QtGui import QAction, QColor, QFontMetrics, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
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
from modern_gl.i18n import tr
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
    icon: Callable[[Any], Any] | None = None  # optional QIcon in front of the text
    warn: Callable[[Any], str | None] | None = None  # text -> red cell with a tooltip
    right: bool = False  # a number that is not money ("7 000.00 Dt"): aligned like one


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
            tr(t),
            (lambda r, a=a: getattr(r, a)),
            money=True,
            width=120,
            warn=warns.get(a.split("_")[0]),
        )
        for t, a in TURNOVER_COLUMNS
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
        self.two_lines = False
        self.emphasis: Callable[[Any], bool] = lambda r: False
        self.muted: Callable[[Any], bool] = lambda r: False

    def set(self, columns, rows, emphasis=None, muted=None, total=None) -> None:
        self.beginResetModel()
        self.columns, self.rows = columns, rows
        self.emphasis = emphasis or (lambda r: False)
        self.muted = muted or (lambda r: False)
        self.total = total or (lambda r: False)  # totals show 0.00 instead of blanks
        self.endResetModel()

    def rowCount(self, parent: QModelIndex | QPersistentModelIndex | None = None) -> int:
        return 0 if parent is not None and parent.isValid() else len(self.rows)

    def columnCount(self, parent: QModelIndex | QPersistentModelIndex | None = None) -> int:
        return 0 if parent is not None and parent.isValid() else len(self.columns)

    def title(self, section: int, two_lines: bool | None = None) -> str:
        """A narrow window puts the amounts' headers in two lines: "İlkin qalıq / Dt"."""
        title = self.columns[section].title
        if self.columns[section].money and (self.two_lines if two_lines is None else two_lines):
            return "\n".join(title.rsplit(" ", 1))
        return title

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
            value = col.get(row)
            if col.money:
                return money(value, blank_zero=not self.total(row))
            return "" if value is None else str(value)
        if role == Qt.ItemDataRole.TextAlignmentRole:
            return RIGHT if col.money or col.right else LEFT
        if role == Qt.ItemDataRole.FontRole and self.emphasis(row):
            return fonts().cell_bold
        if role in (Qt.ItemDataRole.ForegroundRole, Qt.ItemDataRole.ToolTipRole) and col.warn:
            message = col.warn(row)
            if message and col.get(row):
                return QColor(P.red) if role == Qt.ItemDataRole.ForegroundRole else message
        if role == Qt.ItemDataRole.ForegroundRole:
            if self.muted(row):
                return QColor(P.secondary)
            if col.money and isinstance(v := col.get(row), int) and v < 0:
                return QColor(P.red)
        if role == Qt.ItemDataRole.DecorationRole and col.icon is not None:
            return col.icon(row)
        if role == Qt.ItemDataRole.UserRole:
            return row
        return None


NAME_MIN = 180  # px an account name keeps before the amounts give up width
# the chart of accounts: its columns, and the least width of the ones that narrow
TYPE_COLUMN, SIDE_COLUMN, SUBCONTO_COLUMN = 2, 3, 4
CHART_NAME_MIN, CHART_TYPE_MIN, CHART_SUBCONTO_MIN = 240, 180, 200


class ReportPage(QWidget):
    """Base: header, parameters, table/empty state, footer."""

    open_document = Signal(int)
    open_report = Signal(str, int, object)  # kind, account id, ReportParams

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
        # a narrow window: amounts give up some width
        self._viewport = self.table.viewport()
        self._viewport.installEventFilter(self)
        self._floors: dict[int, int] = {}

        self.empty = EmptyState("○", tr("Нет данных"), tr("За выбранный период движений не было."))
        self.stack = QStackedLayout()
        self.stack.addWidget(self.table)
        self.stack.addWidget(self.empty)
        root.addLayout(self.stack, 1)

        self.footer = QLabel()
        self.footer.setObjectName("secondary")
        self.footer.setWordWrap(True)  # a long hint must not keep the window wide
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

    def _layout_columns(self) -> None:
        hh = self.table.horizontalHeader()
        for i, col in enumerate(self.model.columns):
            if col.width:
                hh.setSectionResizeMode(i, QHeaderView.ResizeMode.Interactive)
                self.table.setColumnWidth(i, col.width)
            else:
                hh.setSectionResizeMode(i, QHeaderView.ResizeMode.Stretch)
        self._floors = {
            i: self._content_width(i) for i, col in enumerate(self.model.columns) if col.money
        }
        self._fit_columns()

    def _content_width(self, column: int) -> int:
        """The widest amount of a column (bold totals included) or line of its header
        put in two lines."""
        bold = self.table.font()
        bold.setBold(True)
        metrics = QFontMetrics(bold)
        lines = self.model.title(column, two_lines=True).split("\n")
        widest = max(metrics.horizontalAdvance(line) for line in lines)
        for r in range(min(self.model.rowCount(), 2000)):
            text = self.model.data(self.model.index(r, column), Qt.ItemDataRole.DisplayRole)
            widest = max(widest, metrics.horizontalAdvance(str(text or "")))
        return widest + 28  # the cell padding of the theme

    def _fit_columns(self) -> None:
        """Amounts are 120 px wide while the window allows; in a narrow one they shrink
        to their widest number, so the names keep at least NAME_MIN px."""
        if not self._floors:
            return
        columns = self.model.columns
        fixed = sum(c.width for i, c in enumerate(columns) if c.width and i not in self._floors)
        names = sum(1 for c in columns if not c.width)
        spare = self.table.viewport().width() - fixed - NAME_MIN * names
        each = spare // len(self._floors)
        metrics = QFontMetrics(self.table.horizontalHeader().font())
        two_lines = False
        for i, floor in self._floors.items():
            width = max(floor, min(columns[i].width, each))
            self.table.setColumnWidth(i, width)
            title = metrics.horizontalAdvance(self.model.title(i, False))
            two_lines |= width < columns[i].width and title + 24 > width
        if two_lines != self.model.two_lines:
            self.model.two_lines = two_lines
            self.model.headerDataChanged.emit(Qt.Orientation.Horizontal, 0, len(columns) - 1)

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
        columns = [
            Column(tr("Дата"), lambda ln: ru_date(ln.doc_date), width=100),
            Column("№", lambda ln: ln.number, width=60),
            Column(tr("Содержание"), lambda ln: ln.memo),
            Column(tr("Корр. счёт"), lambda ln: ln.corr_code, width=100),
            Column(tr("Дебет"), lambda ln: ln.debit, money=True, width=130),
            Column(tr("Кредит"), lambda ln: ln.credit, money=True, width=130),
            Column(tr("Сальдо"), lambda ln: balance_text(ln.balance), width=150, right=True),
        ]
        if card.currency_closing or self.account.currency:
            columns[4:4] = [
                Column(tr("Валюта"), lambda ln: ln.currency, width=64),
                Column(tr("Дт в валюте"), lambda ln: ln.currency_debit, money=True, width=110),
                Column(tr("Кт в валюте"), lambda ln: ln.currency_credit, money=True, width=110),
            ]
        self.model.set(columns, card.lines)
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

    def drill(self, row) -> None:
        if row is not None:
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
        self.model.set(
            columns,
            [*rows, total] if rows else [],
            emphasis=lambda r: r is total,
            total=lambda r: r is total,
        )
        self.footer.setText("")

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
            Column(tr("Корр. счёт"), lambda r: r.corr_code, width=110),
            Column(tr("Наименование"), lambda r: r.corr_name),
            Column(tr("С кредита счетов (Дт)"), lambda r: r.debit, money=True, width=190),
            Column(tr("В дебет счетов (Кт)"), lambda r: r.credit, money=True, width=190),
        ]
        self.model.set(columns, rows)
        dt, ct = sum(r.debit for r in rows), sum(r.credit for r in rows)
        self.footer.setText(
            tr("Оборот Дт: {dt}      Оборот Кт: {ct}", dt=money(dt, False), ct=money(ct, False))
        )

    def drill(self, row) -> None:
        if row is not None and row.corr_id in self.s.catalog.accounts:
            self.open_report.emit("card", row.corr_id, self.params)


class ChartPage(ReportPage):
    key = ("chart",)
    has_period = False

    def __init__(self, session: Session) -> None:
        super().__init__(session, tr("План счетов"))
        self.table.setObjectName("list")  # a list, not a report: no rules under rows
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
