"""The chart of accounts."""

from __future__ import annotations

from PySide6.QtCore import (
    Qt,
)
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QHeaderView,
    QMessageBox,
)

from modern_gl.application.catalog import AccountInfo
from modern_gl.desktop.account_dialog import AccountDialog
from modern_gl.desktop.reports_page.view import (
    Column,
    MenuAction,
    ReportPage,
    month_of,
)
from modern_gl.desktop.session import Session
from modern_gl.desktop.widgets import (
    button,
    class_icon,
    hide_when_viewing,
    type_name,
)
from modern_gl.domain.accounts import normal_side
from modern_gl.domain.errors import LedgerError
from modern_gl.i18n import tr

# the chart of accounts: its columns, and the least width of the ones that narrow
TYPE_COLUMN, SIDE_COLUMN, SUBCONTO_COLUMN = 2, 3, 4
CHART_NAME_MIN, CHART_TYPE_MIN, CHART_SUBCONTO_MIN = 240, 180, 200


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
        hide_when_viewing(session.read_only, add)
        for keys, fn in (
            ("Ins", lambda: self.edit_account(None)),
            ("F2", lambda: self.edit_account(self._current())),
        ):
            sc = QShortcut(QKeySequence(keys), self)
            sc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            sc.activated.connect(fn)
        delete = QShortcut(QKeySequence("Del"), self.table)  # not while typing a search
        delete.setContext(Qt.ShortcutContext.WidgetShortcut)
        delete.activated.connect(lambda: self.delete_account(self._current()))
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
            tr(
                "Ins — новый счёт   ·   F2 — изменить   ·   Del — удалить   ·   "
                "двойной щелчок — карточка счёта"
            )
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
            (tr("Добавить субсчёт…"), lambda: self.edit_account(None, row.id)),
            (tr("Показать") if not row.active else tr("Скрыть"), lambda: self.toggle_hidden(row)),
            (tr("Удалить"), lambda: self.delete_account(row)),
            None,
        ]
        return edit + self._account_actions(row.id) + self._class_actions(row.id)
