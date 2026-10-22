"""The trial balance (ОСВ)."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
)

from modern_gl.desktop.reports_page.table import (
    SectionRow,
)
from modern_gl.desktop.reports_page.view import (
    Column,
    MenuAction,
    ReportPage,
    ReportParams,
    turnover_columns,
)
from modern_gl.desktop.session import Session
from modern_gl.desktop.theme import P
from modern_gl.desktop.widgets import (
    CLASS_ORDER,
    button,
    class_icon,
    class_name,
)
from modern_gl.domain.accounts import normal_side
from modern_gl.i18n import tr
from modern_gl.infrastructure.db import Connection
from modern_gl.reporting import reports
from modern_gl.reporting.reports import OsvRow


class OsvPage(ReportPage):
    key = ("osv",)
    compare_books = Signal()  # «Сравнение книг» (D98)

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
        if session.parallel_books:  # D98: the three books side by side
            compare = button(tr("Сравнить книги"), "flat")
            compare.clicked.connect(lambda _=False: self.compare_books.emit())
            self.header.add_action(compare)
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

    def fetch(self, conn: Connection) -> reports.Osv:
        p = self.params
        return reports.trial_balance(conn, self.s.company_id, p.date_from, p.date_to, p.layers)

    def present(self, data: reports.Osv) -> None:
        osv = data
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
            section=lambda r: isinstance(r, SectionRow),
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
