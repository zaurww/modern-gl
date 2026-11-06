"""The chart of accounts."""

from __future__ import annotations

from PySide6.QtCore import (
    Qt,
)
from PySide6.QtWidgets import (
    QHeaderView,
    QMessageBox,
)

from modern_gl.application.catalog import AccountInfo
from modern_gl.desktop.account_dialog import AccountDialog
from modern_gl.desktop.reports_page.report_table import ReportTable
from modern_gl.desktop.reports_page.table import INDENT, NAME_MAX
from modern_gl.desktop.reports_page.view import (
    Column,
    MenuAction,
    ReportPage,
    usual_period,
)
from modern_gl.desktop.session import Session
from modern_gl.desktop.shortcuts import bind
from modern_gl.desktop.split_account_dialog import SplitAccountDialog
from modern_gl.desktop.widgets import (
    class_icon,
    hide_when_viewing,
    type_name,
)
from modern_gl.domain.accounts import normal_side
from modern_gl.domain.errors import LedgerError
from modern_gl.i18n import N_, tr

# the columns that narrow in a narrow window, in this order, and how far
NARROWING = (("subconto", 200), ("type", 180), ("name", 240))


class ChartTable(ReportTable):
    """No sideways scrolling in the plan of accounts: columns narrow in NARROWING order."""

    def layout_columns(self) -> None:
        hh = self.horizontalHeader()
        hh.setStretchLastSection(False)
        self.widths = {}
        for i in range(len(self.report.columns)):
            hh.setSectionResizeMode(i, QHeaderView.ResizeMode.Interactive)
            self.widths[i] = self.content_width(i)
        self.remembered_widths()
        self.fit_columns()

    def fit_columns(self) -> None:
        """Every column as wide as its text (a name at most NAME_MAX), the free room on
        the right, as in a report. No sideways scrolling: in a narrow window the subconto,
        the type and the name narrow (their text cut with "…"), and then the subconto
        column goes: it is the least needed, and the account dialog shows it."""
        room = self.viewport().width()
        if room <= 0 or not self.widths:
            return
        keys = [c.key for c in self.report.columns]
        subconto = keys.index("subconto") if "subconto" in keys else None
        widths = self._fitted(room, keys, None)
        narrow = subconto is not None and sum(widths.values()) > room
        if narrow:
            widths = self._fitted(room, keys, subconto)
        if subconto is not None:
            self.setColumnHidden(subconto, narrow)
        for i, width in widths.items():
            self.setColumnWidth(i, width)

    def _fitted(self, room: int, keys: list[str], hidden: int | None) -> dict[int, int]:
        widths = {i: w for i, w in self.widths.items() if i != hidden}
        if "name" in keys:  # the user may hide even the name
            name = keys.index("name")
            widths[name] = min(widths[name], NAME_MAX)
        over = sum(widths.values()) - room
        for key, least in NARROWING:
            i = keys.index(key) if key in keys else None
            if i is None or i not in widths or over <= 0:
                continue
            give = min(over, max(0, widths[i] - least))
            widths[i] -= give
            over -= give
        return widths


class ChartPage(ReportPage):
    key = ("chart",)
    table_class = ChartTable
    has_period = False
    summary_on_top = False  # key hints, not a summary

    def __init__(self, session: Session) -> None:
        super().__init__(session, tr("План счетов"))
        self.table.setObjectName("list")  # a list, not a report: no rules under rows
        self.table.verticalHeader().setDefaultSectionSize(32)
        self.model.bands = False
        add = self.header.primary(tr("+ Новый счёт"), lambda: self.edit_account(None), "Ins")
        hide_when_viewing(session.read_only, add)
        bind(self, "insert", lambda: self.edit_account(None))
        bind(self, "edit", lambda: self.edit_account(self._current()))
        bind(self.table, "delete", lambda: self.delete_account(self._current()))
        self.refresh()

    def title(self) -> str:
        return tr("План счетов")

    def on_postings_changed(self, doc_id: int) -> None:
        self.refresh()

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
            Column(tr("Код"), lambda a: (INDENT if a.parent_id else "") + a.code, key="code"),
            Column(tr("Наименование"), name, key="name"),
            Column(
                tr("Тип"), self._type_text, icon=lambda a: class_icon(a.account_class), key="type"
            ),
            Column(tr("Сальдо"), self._side_text, key="side"),
            Column(tr("Субконто"), subconto, key="subconto"),
        ]
        self.model.set(
            columns,
            list(cat.accounts.values()),
            emphasis=lambda a: a.is_group,
            muted=lambda a: not a.active,
        )
        self.footer.setText(
            tr(
                "Ins — новый счёт   ·   F2 — изменить   ·   Del — удалить   ·   "
                "двойной щелчок — карточка счёта"
            )
        )

    def drill(self, row) -> None:
        if row is not None:
            self.open_report.emit("card", row.id, usual_period(self.s))

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

    def add_subaccount(self, acc: AccountInfo) -> None:
        """A subaccount of a group; an account that is not one becomes a group first, its
        history going on as the first subaccount — then the next one is added."""
        if not acc.is_group:
            dialog = SplitAccountDialog(self.s, acc, self)
            if not dialog.exec() or dialog.group_id is None:
                return
            self.s.catalog.reload()
            self._after_change(dialog.group_id, tr("Счёт {code} стал группой", code=acc.short))
            self.edit_account(None, dialog.group_id)
            return
        self.edit_account(None, acc.id)

    def toggle_hidden(self, acc) -> None:
        self.s.ledger.set_account_active(self.s.company_id, acc.id, not acc.active)
        message = N_("Счёт {code} снова виден") if not acc.active else N_("Счёт {code} скрыт")
        self._after_change(acc.id, tr(message, code=acc.short))

    def delete_account(self, acc: AccountInfo | None) -> None:
        """An account entered by mistake; a used one stays, the message says where it is."""
        if acc is None:
            return
        question = tr("Удалить счёт {code}?", code=acc.label)
        if QMessageBox.question(self, tr("Удалить"), question) != QMessageBox.StandardButton.Yes:
            return
        try:
            self.s.ledger.delete_account(self.s.company_id, acc.id)
        except LedgerError as e:
            self.s.notify(str(e))
            return
        self.s.catalog.reload()
        self.refresh()
        self.s.notify(tr("Счёт {code} удалён", code=acc.short))

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
            (tr("Добавить субсчёт…"), lambda: self.add_subaccount(row)),
            (tr("Показать") if not row.active else tr("Скрыть"), lambda: self.toggle_hidden(row)),
            (tr("Удалить"), lambda: self.delete_account(row)),
            None,
        ]
        return edit + self._account_actions(row.id) + self._class_actions(row.id)
