"""Анализ субконто (D125): a directory's elements across every account that carries it —
a counterparty on 60, 62 and 76 at once, an order or a project on the client's, the
suppliers' and the revenue accounts. The directory, one element and «Только с остатком»
are chosen on the page itself; a double click on an account opens its card."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QCheckBox, QComboBox

from modern_gl.desktop.pick import PickBox
from modern_gl.desktop.reports_page.view import Column, ReportPage, ReportParams, turnover_columns
from modern_gl.desktop.session import Session
from modern_gl.desktop.widgets import balance_text, caption
from modern_gl.i18n import tr
from modern_gl.infrastructure.db import Connection
from modern_gl.reporting import reports
from modern_gl.reporting.reports import SubcontoAnalysisRow

KIND_SETTING = "reports/subconto_analysis_kind"  # the directory asked last
INDENT = "      "


class SubcontoAnalysisPage(ReportPage):
    key = ("subconto_analysis",)

    def __init__(
        self, session: Session, params: ReportParams | None = None, kind_id: int | None = None
    ) -> None:
        super().__init__(session, tr("Анализ субконто"), params)
        self._add_choices(kind_id)
        self.refresh()

    # ---- the choices of the page -------------------------------------------------------

    def _add_choices(self, kind_id: int | None) -> None:
        """«Справочник» — the directories some account carries; «Элемент» — all of them or
        one; «Только с остатком» — the elements still owed or holding something."""
        self.kind = QComboBox()
        self.kind.setMinimumWidth(190)
        cat = self.s.catalog
        offered = sorted(
            (k for k in cat.kinds if cat.accounts_using(k)), key=lambda k: cat.kinds[k].casefold()
        )
        for k in offered:
            self.kind.addItem(cat.kinds[k], k)
        remembered = QSettings().value(KIND_SETTING, -1, type=int)
        counterparties = [k for k in offered if cat.kind_codes.get(k) == "counterparty"]
        for wanted in (kind_id, remembered, *counterparties):  # asked, last time, 60 / 62
            if wanted is not None and (at := self.kind.findData(wanted)) >= 0:
                self.kind.setCurrentIndex(at)
                break
        self.element = PickBox(tr("Все элементы"))
        self.element.setMinimumWidth(220)
        self.only_open = QCheckBox(tr("Только с остатком"))
        self.only_open.setToolTip(
            tr("Остаток на балансовых счетах; выручка и расходы остатком не считаются")
        )
        self.add_to_bar(caption(tr("Справочник")), self.kind, caption(tr("Элемент")), gap=0)
        self.add_to_bar(self.element)
        self.header.add_action(self.only_open)
        self._fill_elements()
        self.kind.activated.connect(self._choose_kind)
        self.element.activated.connect(lambda _i: self.refresh())
        self.only_open.toggled.connect(self.refresh)

    def _choose_kind(self, _index: int) -> None:
        QSettings().setValue(KIND_SETTING, self.kind_id)
        self._fill_elements()
        self.refresh()

    def _fill_elements(self) -> None:
        self.element.clear()
        self.element.addItem(tr("Все элементы"), None)
        if self.kind_id is not None:
            for v in self.s.catalog.values(self.kind_id):
                self.element.addItem(v.label, v.id, v.name)
        self.element.setCurrentIndex(0)

    @property
    def kind_id(self) -> int | None:
        return self.kind.currentData()

    @property
    def value_id(self) -> int | None:
        return self.element.currentData()

    # ---- the report ----------------------------------------------------------------

    def title(self) -> str:
        name = self.kind.currentText()
        return f"{tr('Анализ субконто')} · {name}" if name else tr("Анализ субконто")

    def refresh(self) -> None:
        self.header.title.setText(self.title())
        super().refresh()

    def job(self) -> Callable[[Connection], list[SubcontoAnalysisRow]]:
        cid, p = self.s.company_id, self.params
        kind_id, value_id, only_open = self.kind_id, self.value_id, self.only_open.isChecked()

        def read(conn: Connection) -> list[SubcontoAnalysisRow]:
            if kind_id is None:
                return []
            return reports.subconto_analysis(
                conn, cid, kind_id, p.date_from, p.date_to, p.layers, value_id, only_open
            )

        return read

    def fetch(self, conn: Connection) -> list[SubcontoAnalysisRow]:
        return self.job()(conn)

    def present(self, data: list[SubcontoAnalysisRow]) -> None:
        rows = data
        total = SubcontoAnalysisRow(name=tr("Итого"))
        for r in rows:
            if r.depth == 0:
                total.add(r)
        columns = [
            Column(self.kind.currentText() or tr("Элемент"), self._name),
            *turnover_columns(),
        ]
        if any(r.currency_closing for r in rows):
            columns.append(Column(tr("В валюте на конец"), self._in_currency, width=200))
        self.model.set(
            columns,
            [*rows, total] if rows else [],
            emphasis=lambda r: r is total or r.depth == 0,
            muted=lambda r: r.depth > 0,
            total=lambda r: r is total,
        )
        elements = sum(1 for r in rows if r.depth == 0)
        self.footer.setText(
            tr("Элементов с остатком: {n}", n=elements)
            if self.only_open.isChecked()
            else tr("Элементов: {n}", n=elements)
        )

    @staticmethod
    def _name(row: SubcontoAnalysisRow) -> str:
        if row.depth == 0:
            return row.name
        return INDENT + (f"{row.code} {row.name}" if row.code else row.name)

    @staticmethod
    def _in_currency(row: SubcontoAnalysisRow) -> str:
        return ",  ".join(
            f"{code} {balance_text(net)}" for code, net in sorted(row.currency_closing.items())
        )

    def drill(self, row) -> None:
        """The card of the element (D126): across every account from its own row, on one
        account from the account's row under it."""
        if row is not None and row.value_id is not None:
            params = replace(self.params, subconto=(row.value_id,))
            self.open_report.emit("subconto_card", row.account_id or 0, params)
