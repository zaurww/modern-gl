"""The trial balance (ОСВ) — opened by place as «Интерактивная ОСВ» of 1C 7.7
(D190): → splits a row by its next subconto (then the corr accounts,
the months), Shift+→ asks by what, ← folds it; a click on a caption sorts; «⋯» —
one column of balances, figures in thousands."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMenu

from modern_gl.application.catalog import AccountInfo
from modern_gl.desktop.preferences import OSV_COLUMNS, OSV_SCALE, prefs
from modern_gl.desktop.reports_page.osv_tree import (
    ExpandedRow,
    Layout,
    NodeKey,
    OsvTree,
    assemble,
    kinds_of,
    months_of,
    natural_kind,
    node_of,
    read_nodes,
)
from modern_gl.desktop.reports_page.osv_views import OsvViews
from modern_gl.desktop.reports_page.table import (
    INDENT,
    Column,
    SectionRow,
)
from modern_gl.desktop.reports_page.view import (
    MenuAction,
    ReportPage,
    ReportParams,
    turnover_columns,
)
from modern_gl.desktop.session import Session
from modern_gl.desktop.shortcuts import SEPARATOR, bind, legend
from modern_gl.desktop.theme import P
from modern_gl.desktop.widgets import (
    CLASS_ORDER,
    MenuItem,
    button,
    class_icon,
    class_name,
    segments,
)
from modern_gl.domain.accounts import normal_side
from modern_gl.domain.dates import month_days
from modern_gl.i18n import N_, tr
from modern_gl.infrastructure.db import Connection
from modern_gl.reporting import reports
from modern_gl.reporting.reports import ExpandRow, OsvRow

SCALES = [(1, N_("С копейками")), (1000, N_("В тысячах")), (1_000_000, N_("В миллионах"))]


@dataclass
class CurrencyLine(OsvRow):
    """Amounts of a currency account in one of its currencies: in their own color (D127)."""


def sort_id(col: Column) -> str:
    """What a sort is remembered by: a column's key, else its group and caption."""
    return col.key or (f"{col.group}|{col.title}" if col.group else col.title)


def net_columns(warn_opening, warn_closing) -> list[Column]:
    """Balances in one column each — a credit in brackets — and the turnovers."""
    return [
        Column(
            tr("Сальдо на начало"),
            lambda r: r.opening_dt - r.opening_ct,
            money=True,
            warn=warn_opening,
            key="opening",
            role="opening",
        ),
        Column(
            tr("Дт"), lambda r: r.turnover_dt, money=True, group=tr("Обороты"), role="turnover_dt"
        ),
        Column(
            tr("Кт"), lambda r: r.turnover_ct, money=True, group=tr("Обороты"), role="turnover_ct"
        ),
        Column(
            tr("Сальдо на конец"),
            lambda r: r.closing_dt - r.closing_ct,
            money=True,
            warn=warn_closing,
            key="closing",
            role="closing",
        ),
    ]


class OsvPage(ReportPage):
    key = ("osv",)
    compare_books = Signal()  # «Сравнение книг» (D98)

    def __init__(self, session: Session, params: ReportParams | None = None) -> None:
        super().__init__(session, tr("Оборотно-сальдовая ведомость"), params)
        # how deep, by the period as on every report (DESIGN.md 2): the main accounts,
        # with their subaccounts, or down to every subconto
        detail, buttons = segments(
            [("top", N_("Основные счета")), ("sub", N_("Субсчета")), ("subconto", "Субконто")],
            lambda: None,
        )
        self.top_only, self.sub, self.expand = buttons["top"], buttons["sub"], buttons["subconto"]
        self.top_only.setToolTip(tr("Скрыть субсчета; суммы основных счетов не меняются"))
        self.expand.setToolTip(tr("Показать под каждым счётом остатки по всем его субконто"))
        buttons["sub"].setChecked(True)
        for b in buttons.values():
            b.toggled.connect(lambda on: on and self.redraw())
        self.in_currency = button(tr("В валюте"), "segment")
        self.in_currency.setCheckable(True)
        self.in_currency.setToolTip(tr("Показать под валютными счетами суммы в каждой валюте"))
        self.in_currency.toggled.connect(lambda _on: self.redraw())
        self.in_currency.setVisible(session.catalog.has_currency_accounts)
        self.add_to_bar(detail, self.in_currency)
        # rare: in «⋯»
        self.sections = QAction(tr("По разделам"), self)
        self.sections.setCheckable(True)
        self.sections.toggled.connect(lambda _on: self.redraw())
        self.net = prefs().view(OSV_COLUMNS, "pair") == "net"  # one column of balances
        self.model.scale = prefs().number(OSV_SCALE, 1)
        # what the user opened under the accounts, and the order of rows
        self.osv: reports.Osv | None = None
        self.tree = OsvTree()
        self._wanted: dict[NodeKey, str] = {}  # the nodes a read in progress is for
        self.sort: tuple[str, bool] | None = None  # (sort_id of a column, descending)
        self.views = OsvViews(self)  # «⋯ → Вид „…“», saved in the company's file
        captions = self.table.horizontalHeader()
        captions.setSectionsClickable(True)
        captions.setSortIndicatorShown(True)
        captions.sectionClicked.connect(self.sort_by)
        bind(self.table, "expand", self.expand_current)
        bind(self.table, "collapse", self.collapse_current)
        bind(self.table, "expand_by", self.expand_by_current)
        bind(self.table, "expand_all", self.expand_all)
        bind(self.table, "collapse_all", self.collapse_all)
        self.refresh()

    def more_items(self) -> list[MenuItem]:
        """«⋯»: by account classes, one column, the precision, the books side by side
        (D98), then every report's."""

        def mark(on: bool) -> str:
            return "✓  " if on else "    "

        items: list[MenuItem] = [
            (mark(self.sections.isChecked()) + tr("По разделам"), self.sections.toggle),
            (mark(self.net) + tr("Одной колонкой"), self.toggle_net),
            None,
        ]
        for scale, name in SCALES:
            items.append(
                (mark(self.model.scale == scale) + tr(name), lambda s=scale: self.set_scale(s))
            )
        if self.s.parallel_books:
            items += [None, (tr("Сравнить книги"), self.compare_books.emit)]
        views = self.views.items()
        return [*items, *([None, *views] if views else []), None, *super().more_items()]

    def title(self) -> str:
        return tr("ОСВ")

    def on_postings_changed(self, doc_id: int) -> None:
        self.refresh()

    # ---- reading -----------------------------------------------------------------------

    def job(self):
        """fetch() with the opened nodes taken now, on the window's thread."""
        self._wanted = dict(self.tree.opened)
        return self.fetch

    def fetch(self, conn: Connection) -> tuple[reports.Osv, dict[NodeKey, list[ExpandRow]]]:
        """The trial balance and the rows of every opened node, read together."""
        p, cid = self.params, self.s.company_id
        osv = reports.trial_balance(conn, cid, p.date_from, p.date_to, p.layers)
        found: dict[NodeKey, list[ExpandRow]] = {}
        read_nodes(conn, cid, p, self._wanted, found)
        return osv, found

    def present(self, data: Any) -> None:
        self.osv, self.tree.read = data
        self._show_rows()
        self.show_subtitle()

    def show_subtitle(self) -> None:
        """The period, the book — and the name of the view the page shows."""
        text = self.params.describe(self.s.parallel_books and self.has_book)
        if self.views.current is not None:
            text += SEPARATOR + tr("вид «{name}»", name=self.views.current)
        self.header.subtitle.setText(text)

    def _read_missing(self, then: NodeKey | None = None) -> None:
        """Read the rows of the nodes just opened (one query for nodes alike), then
        show them; the cursor goes to `then`."""
        wanted = self.tree.missing()
        p, cid = self.params, self.s.company_id

        def read(conn: Connection) -> dict[NodeKey, list[ExpandRow]]:
            found: dict[NodeKey, list[ExpandRow]] = {}
            read_nodes(conn, cid, p, wanted, found)
            return found

        def done(found: dict[NodeKey, list[ExpandRow]]) -> None:
            self.tree.read.update(found)
            self.redraw()
            if then is not None:
                self.select(then)

        self.s.read(self, read, done, lambda e: self.s.notify(str(e)))

    # ---- the rows ----------------------------------------------------------------------

    def _columns(self) -> list[Column]:
        def warn_opening(r):
            return self._side_warning(r) if r.opening_wrong else None

        def warn_closing(r):
            return self._side_warning(r) if r.closing_wrong else None

        amounts = (net_columns if self.net else turnover_columns)(warn_opening, warn_closing)
        return [
            Column(
                tr("Счёт"),
                lambda r: "" if isinstance(r, SectionRow) else INDENT * max(r.depth, 0) + r.code,
                width=90,
                icon=lambda r: class_icon(r.account_class) if isinstance(r, SectionRow) else None,
                key="code",
            ),
            Column(tr("Наименование"), lambda r: r.name, key="name"),
            *amounts,
        ]

    def _layout(self, columns: list[Column]) -> Layout:
        layout = Layout(subconto=self.expand.isChecked())
        if self.sort is not None:
            sid, layout.descending = self.sort
            col = next((c for c in columns if sort_id(c) == sid), None)
            layout.sort_value = col.get if col is not None else None
        return layout

    def redraw(self) -> None:
        """The same figures laid out again (a view, a sort, a fold)."""
        self._show_rows()
        self._shown()

    def _show_rows(self) -> None:
        """The table from what was read: the accounts as deep as asked, what the user
        opened under them, the currencies, the sections."""
        osv = self.osv
        if osv is None:
            return
        total = OsvRow(name=tr("Итого"), depth=-1)
        total.add(osv.total)
        columns = self._columns()
        shown = [r for r in osv.rows if r.depth == 0] if self.top_only.isChecked() else osv.rows
        shown = assemble(osv, shown, self.tree, self._layout(columns))
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
            tone=lambda r: "currency" if isinstance(r, CurrencyLine) else None,
        )
        self._show_sort(columns)
        self._show_check(osv)

    def _show_sort(self, columns: list[Column]) -> None:
        captions = self.table.horizontalHeader()
        shown = self.model.columns
        section = -1
        order = Qt.SortOrder.AscendingOrder
        if self.sort is not None:
            sid, descending = self.sort
            section = next((i for i, c in enumerate(shown) if sort_id(c) == sid), -1)
            order = Qt.SortOrder.DescendingOrder if descending else Qt.SortOrder.AscendingOrder
        captions.setSortIndicator(section, order)

    def _show_check(self, osv: reports.Osv) -> None:
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
        text += SEPARATOR + legend("expand", "expand_by", "collapse", "expand_all")
        self.footer.setText(text)
        self.footer.setStyleSheet(f"color: {P.red};" if wrong or not balanced else "")

    @staticmethod
    def _with_currency(rows: list[OsvRow], currency) -> list[OsvRow]:
        """Insert a row per currency (amounts in that currency) under each currency account."""
        result = []
        for r in rows:
            result.append(r)
            if isinstance(r, ExpandedRow) or not r.account_id:
                continue
            for c in currency.get(r.account_id, []):
                row = CurrencyLine(name=f"{INDENT}{c.code}  ·  {tr('в валюте')}", depth=r.depth + 1)
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

    # ---- opening by place --------------------------------------------------------------

    def months(self) -> int:
        """How many months the period spans: by months needs more than one."""
        a, b = self.params.date_from, self.params.date_to
        return (b.year - a.year) * 12 + b.month - a.month + 1

    def node_at_cursor(self) -> tuple[NodeKey, AccountInfo] | None:
        node = node_of(self.current_row())
        acc = self.s.catalog.accounts.get(node[0]) if node else None
        return (node, acc) if node and acc else None

    def kinds_at(self, node: NodeKey, acc: AccountInfo) -> list[tuple[str, str]]:
        return kinds_of(acc, node[1], self.months(), self.s.catalog)

    def open_node(self, node: NodeKey, by: str) -> None:
        self.tree.open(node, by)
        self._read_missing(node)

    def close_node(self, node: NodeKey) -> None:
        self.tree.close(node)
        self.redraw()
        self.select(node)

    def expand_current(self) -> None:
        """→: open the row by what comes next; an open row — step onto its first row."""
        found = self.node_at_cursor()
        if found is None:
            return
        node, acc = found
        if node in self.tree.opened:
            idx = self.table.currentIndex()
            below = self.model.index(idx.row() + 1, 0)
            if below.isValid():
                self.table.setCurrentIndex(below)
            return
        kind = natural_kind(acc, node[1], self.months(), self.s.catalog)
        if kind is not None:
            self.open_node(node, kind)

    def collapse_current(self) -> None:
        """←: fold the row; a folded one — go to the row it is under."""
        found = self.node_at_cursor()
        if found is None:
            return
        node, acc = found
        if node in self.tree.opened:
            self.close_node(node)
        elif node[1]:
            self.select((node[0], node[1][:-1]))
        elif acc.parent_id is not None:
            self.select((acc.parent_id, ()))

    def expand_by_current(self) -> None:
        """Shift+→: a menu of what the row can be split by, under the row."""
        found = self.node_at_cursor()
        if found is None:
            return
        node, acc = found
        menu = self.kinds_menu(node, acc)
        if menu is None:
            return
        rect = self.table.visualRect(self.table.currentIndex())
        menu.exec(self.table.viewport().mapToGlobal(QPoint(rect.left() + 40, rect.bottom())))

    def kinds_menu(self, node: NodeKey, acc: AccountInfo) -> QMenu | None:
        kinds = self.kinds_at(node, acc)
        if not kinds:
            return None
        menu = QMenu(self)
        for kind, name in kinds:
            menu.addAction(name).triggered.connect(lambda _=False, k=kind: self.open_node(node, k))
        return menu

    def expand_all(self) -> None:
        """Ctrl+→: every account row open by what comes next for it (one query)."""
        current = node_of(self.current_row())
        for row in self.model.rows:
            node = node_of(row)
            if node is None or node[1] or node in self.tree.opened:
                continue
            acc = self.s.catalog.accounts.get(node[0])
            kind = natural_kind(acc, (), self.months(), self.s.catalog) if acc else None
            if kind is not None:
                self.tree.open(node, kind)
        self._read_missing(current)

    def collapse_all(self) -> None:
        current = node_of(self.current_row())
        self.tree.clear()
        self.redraw()
        if current is not None:
            self.select((current[0], ()))

    def select(self, node: NodeKey) -> None:
        for i, row in enumerate(self.model.rows):
            if node_of(row) == node:
                self.table.setCurrentIndex(self.model.index(i, 0))
                return

    # ---- the order, the columns ----------------------------------------------------------

    def sort_by(self, section: int) -> None:
        """A click on a caption: up, down, then the chart's own order again; the
        account column — the chart's order at once."""
        col = self.model.columns[section]
        sid = sort_id(col)
        if sid == "code":
            self.sort = None
        elif self.sort is None or self.sort[0] != sid:
            self.sort = (sid, False)
        elif not self.sort[1]:
            self.sort = (sid, True)
        else:
            self.sort = None
        self.redraw()

    def toggle_net(self) -> None:
        self.net = not self.net
        prefs().set_view(OSV_COLUMNS, "net" if self.net else "pair")
        self.redraw()

    def set_scale(self, scale: int) -> None:
        self.model.scale = scale
        prefs().set(OSV_SCALE, scale)
        self.redraw()

    # ---- going deeper --------------------------------------------------------------------

    def drill(self, row: OsvRow) -> None:
        """The card of the account — or of the counterparty (contract) of a row under
        it, in the month of a month row."""
        if not row or not row.account_id:
            return
        params = replace(self.params, subconto=row.subconto)
        month = months_of(row.steps) if isinstance(row, ExpandedRow) else None
        if month:
            first, last = month_days(int(month[:4]), int(month[5:7]))
            params = replace(
                params,
                date_from=max(params.date_from, first),
                date_to=min(params.date_to, last),
            )
        self.open_report.emit("card", row.account_id, params)

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
        actions: list[MenuAction | None] = []
        node = node_of(row)
        acc = self.s.catalog.accounts.get(row.account_id)
        if node is not None and acc is not None:
            key = node
            kinds = self.kinds_at(key, acc)
            if kinds:
                splits: list[MenuAction | None] = [
                    (name, lambda _=False, k=kind: self.open_node(key, k)) for kind, name in kinds
                ]
                actions.append((tr("Развернуть"), splits))
            if key in self.tree.opened:
                actions.append((tr("Свернуть"), lambda: self.close_node(key)))
            actions += [
                None,
                (tr("Развернуть все"), self.expand_all),
                (tr("Свернуть все"), self.collapse_all),
                None,
            ]
        return actions + self._account_actions(row.account_id) + self._class_actions(row.account_id)
