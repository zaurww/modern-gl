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

from modern_gl.desktop.account_dialog import AccountDialog
from modern_gl.desktop.session import Session
from modern_gl.desktop.theme import P
from modern_gl.desktop.widgets import (
    ACCOUNT_CLASSES,
    CLASS_ORDER,
    EmptyState,
    PageHeader,
    balance_text,
    button,
    class_icon,
    class_name,
    date_edit,
    money,
    ru_date,
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


class ReportModel(QAbstractTableModel):
    def __init__(self) -> None:
        super().__init__()
        self.columns: list[Column] = []
        self.rows: list[Any] = []
        self.emphasis: Callable[[Any], bool] = lambda r: False
        self.muted: Callable[[Any], bool] = lambda r: False

    def set(self, columns, rows, emphasis=None, muted=None, total=None) -> None:
        self.beginResetModel()
        self.columns, self.rows = columns, rows
        self.emphasis = emphasis or (lambda r: False)
        self.muted = muted or (lambda r: False)
        self.total = total or (lambda r: False)  # totals show 0.00 instead of blanks
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
            if col.money:
                return money(value, blank_zero=not self.total(row))
            return "" if value is None else str(value)
        if role == Qt.ItemDataRole.TextAlignmentRole:
            return RIGHT if col.money else LEFT
        if role == Qt.ItemDataRole.FontRole and self.emphasis(row):
            f = QFont()
            f.setWeight(QFont.Weight.DemiBold)
            return f
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

        self.empty = EmptyState("○", tr("Нет данных"), tr("За выбранный период движений не было."))
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
        self._fill_menu(menu, actions)
        menu.exec(self.table.viewport().mapToGlobal(pos))

    def _fill_menu(self, menu: QMenu, actions) -> None:
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

    def _class_actions(self, code: str) -> list:
        """Submenu to change an account's class and contra flag."""
        acc = self.s.catalog.by_code.get(code)
        if acc is None:
            return []

        def mark(on: bool, text: str) -> str:
            return ("✓  " if on else "     ") + text

        def setter(account_class, contra=None):
            def run():
                self.s.ledger.set_account_class(self.s.company_id, code, account_class, contra)
                self.s.catalog.reload()
                self.s.notify(
                    tr("Счёт {code}: класс «{name}»", code=code, name=class_name(account_class))
                )
                self.refresh()

            return run

        items = [
            (mark(acc.account_class == c, tr(name)), setter(c)) for c, name, _ in ACCOUNT_CLASSES
        ]
        items += [
            None,
            (mark(acc.account_class is None, tr("Не задан")), setter(None)),
            None,
            (mark(acc.contra, tr("Контрсчёт")), setter(acc.account_class, not acc.contra)),
        ]
        return [None, (tr("Класс счёта"), items)]

    def _account_actions(self, code: str) -> list[tuple[str, Callable[[], None]]]:
        acc = self.s.catalog.by_code.get(code)
        if acc is None:
            return []
        actions = [
            (tr("Карточка счёта"), lambda: self.open_report.emit("card", code, self.params)),
            (tr("Анализ счёта"), lambda: self.open_report.emit("analysis", code, self.params)),
        ]
        if acc.sc_kinds[0] is not None:
            actions.append(
                (
                    tr("ОСВ по субконто"),
                    lambda: self.open_report.emit("subconto", code, self.params),
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
        self._section_rows: set[int] = set()
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
            acc = self.s.catalog.by_code.get(block[0].code)
            groups.setdefault(acc.account_class if acc else None, []).append(block)
        result = []
        for cls in sorted(groups, key=lambda c: CLASS_ORDER.get(c, len(CLASS_ORDER))):
            header = OsvRow(name=class_name(cls), depth=0, is_group=True)
            header.account_class = cls
            for block in groups[cls]:
                header.add(block[0])
            self._section_rows.add(id(header))
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
        sections = self._section_rows
        sections.clear()
        columns = [
            Column(
                tr("Счёт"),
                lambda r: "" if id(r) in sections else ("      " * max(r.depth, 0)) + r.code,
                width=90,
                icon=lambda r: class_icon(r.account_class) if id(r) in sections else None,
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
        if self.sections.isChecked() and shown:
            shown = self._by_class(shown)
        rows = [*shown, total] if shown else []
        sectioned = self.sections.isChecked()
        self.model.set(
            columns,
            rows,
            emphasis=lambda r: (
                r.depth < 0
                or id(r) in sections
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
            codes = ", ".join(r.code for r in wrong[:8]) + ("…" if len(wrong) > 8 else "")
            text += "      " + tr(
                "Сальдо не на своей стороне: {codes} — подсвечено красным", codes=codes
            )
        self.footer.setText(text)
        self.footer.setStyleSheet(f"color: {P.red};" if wrong or not balanced else "")

    def drill(self, row: OsvRow) -> None:
        if row and row.code:
            self.open_report.emit("card", row.code, self.params)

    def _side_warning(self, row: OsvRow) -> str:
        acc = self.s.catalog.by_code.get(row.code)
        if acc is None:
            return ""
        side = normal_side(acc.account_class, acc.contra)
        return tr(
            "Сальдо не на своей стороне: для «{cls}» ожидается {side} сальдо",
            cls=class_name(acc.account_class) + (f" · {tr('контрсчёт')}" if acc.contra else ""),
            side=tr("дебетовое") if side == "debit" else tr("кредитовое"),
        )

    def menu_actions(self, row: OsvRow):
        if not row or not row.code:
            return []
        return self._account_actions(row.code) + self._class_actions(row.code)


class AccountReportPage(ReportPage):
    kind = ""
    caption = ""

    def __init__(self, session: Session, code: str, params: ReportParams) -> None:
        self.code = code
        acc = session.catalog.by_code[code]
        super().__init__(session, f"{tr(self.caption)} {code}", params)
        self.header.title.setText(f"{tr(self.caption)} {code}")
        self.header.subtitle.setText(acc.name)
        self.key = (self.kind, code)
        self.refresh()

    def title(self) -> str:
        return f"{tr(self.caption)} {self.code}"

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
            Column(tr("Дата"), lambda ln: ru_date(ln.doc_date), width=100),
            Column("№", lambda ln: ln.number, width=60),
            Column(tr("Содержание"), lambda ln: ln.memo),
            Column(tr("Корр. счёт"), lambda ln: ln.corr_code, width=100),
            Column(tr("Дебет"), lambda ln: ln.debit, money=True, width=130),
            Column(tr("Кредит"), lambda ln: ln.credit, money=True, width=130),
            Column(tr("Сальдо"), lambda ln: balance_text(ln.balance), width=150),
        ]
        self.model.set(columns, card.lines)
        self.footer.setText(
            tr(
                "Сальдо на начало: {start}      Сальдо на конец: {end}",
                start=balance_text(card.opening),
                end=balance_text(card.closing),
            )
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
        kind = self.s.catalog.kinds[self.s.catalog.by_code[self.code].sc_kinds[0]]
        columns = [Column(kind, lambda r: r.name), *turnover_columns()]
        self.model.set(
            columns,
            [*rows, total] if rows else [],
            emphasis=lambda r: r is total,
            total=lambda r: r is total,
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
        if row is not None and row.corr_code in self.s.catalog.by_code:
            self.open_report.emit("card", row.corr_code, self.params)


class ChartPage(ReportPage):
    key = ("chart",)
    has_period = False

    def __init__(self, session: Session) -> None:
        super().__init__(session, tr("План счетов"))
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
            return ", ".join(cat.kinds[k] for k in a.sc_kinds if k)

        def name(a) -> str:
            return a.name if a.active else f"{a.name}  ·  {tr('скрыт')}"

        columns = [
            Column(tr("Код"), lambda a: ("      " if a.parent_id else "") + a.code, width=110),
            Column(tr("Наименование"), name),
            Column(tr("Сальдо"), self._side_text, width=150),
            Column(
                tr("Класс"), self._class_text, width=190, icon=lambda a: class_icon(a.account_class)
            ),
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

    def drill(self, acc) -> None:
        if acc is not None:
            self.open_report.emit("card", acc.code, month_of(self.s.working_date))

    def _current(self):
        idx = self.table.currentIndex()
        return idx.data(Qt.ItemDataRole.UserRole) if idx.isValid() else None

    @staticmethod
    def _class_text(acc) -> str:
        text = class_name(acc.account_class)
        return f"{text} · {tr('контрсчёт')}" if acc.contra else text

    @staticmethod
    def _side_text(acc) -> str:
        if acc.is_group:
            return ""
        if acc.two_sided:
            return tr("Дт и Кт")
        side = normal_side(acc.account_class, acc.contra)
        return {"debit": tr("Дебет"), "credit": tr("Кредит")}.get(side, "—")

    def edit_account(self, acc, parent_code: str | None = None) -> None:
        dialog = AccountDialog(self.s, acc, parent_code, self)
        if dialog.exec():
            self._after_change(
                dialog.saved_code, tr("Счёт {code} сохранён", code=dialog.saved_code)
            )

    def toggle_hidden(self, acc) -> None:
        self.s.ledger.set_account_active(self.s.company_id, acc.code, not acc.active)
        message = "Счёт {code} снова виден" if not acc.active else "Счёт {code} скрыт"
        self._after_change(acc.code, tr(message, code=acc.code))

    def _after_change(self, code: str, message: str) -> None:
        self.s.catalog.reload()
        self.refresh()
        row = next((i for i, a in enumerate(self.model.rows) if a.code == code), None)
        if row is not None:
            self.table.setCurrentIndex(self.model.index(row, 0))
            self.table.scrollTo(self.model.index(row, 0))
        self.s.notify(message)

    def menu_actions(self, acc):
        if acc is None:
            return []
        edit = [
            (tr("Изменить…"), lambda: self.edit_account(acc)),
            (tr("Добавить субсчёт…"), lambda: self.edit_account(None, acc.code)),
            (tr("Показать") if not acc.active else tr("Скрыть"), lambda: self.toggle_hidden(acc)),
            None,
        ]
        return edit + self._account_actions(acc.code) + self._class_actions(acc.code)


REPORTS: dict[str, type[AccountReportPage]] = {
    "card": CardPage,
    "subconto": SubcontoPage,
    "analysis": AnalysisPage,
}
