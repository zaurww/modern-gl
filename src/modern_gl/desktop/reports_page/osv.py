"""The trial balance (ОСВ)."""

from __future__ import annotations

from dataclasses import dataclass, replace

from PySide6.QtCore import Signal
from PySide6.QtGui import QAction

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
    MenuItem,
    button,
    class_icon,
    class_name,
    segments,
)
from modern_gl.domain.accounts import normal_side
from modern_gl.i18n import tr
from modern_gl.infrastructure.db import Connection
from modern_gl.reporting import reports
from modern_gl.reporting.reports import OsvRow


@dataclass
class CurrencyLine(OsvRow):
    """Amounts of a currency account in one of its currencies: in their own color (D127)."""


class OsvPage(ReportPage):
    key = ("osv",)
    compare_books = Signal()  # «Сравнение книг» (D98)

    def __init__(self, session: Session, params: ReportParams | None = None) -> None:
        super().__init__(session, tr("Оборотно-сальдовая ведомость"), params)
        # how deep, by the period as on every report (DESIGN.md 2): the main accounts,
        # with their subaccounts, or down to every subconto
        detail, buttons = segments(
            [("top", "Основные счета"), ("sub", "Субсчета"), ("subconto", "Субконто")],
            lambda: None,
        )
        self.top_only, self.expand = buttons["top"], buttons["subconto"]
        self.top_only.setToolTip(tr("Скрыть субсчета; суммы основных счетов не меняются"))
        self.expand.setToolTip(tr("Показать под каждым счётом остатки по всем его субконто"))
        buttons["sub"].setChecked(True)
        for b in buttons.values():
            b.toggled.connect(lambda on: on and self.refresh())
        self.in_currency = button(tr("В валюте"), "segment")
        self.in_currency.setCheckable(True)
        self.in_currency.setToolTip(tr("Показать под валютными счетами суммы в каждой валюте"))
        self.in_currency.toggled.connect(lambda _on: self.refresh())
        self.in_currency.setVisible(session.catalog.has_currency_accounts)
        self.add_to_bar(detail, self.in_currency)
        # rare: in «⋯»
        self.sections = QAction(tr("По разделам"), self)
        self.sections.setCheckable(True)
        self.sections.toggled.connect(lambda _on: self.refresh())
        self.refresh()

    def more_items(self) -> list[MenuItem]:
        """«⋯»: by account classes, the books side by side (D98), then every report's."""
        mark = "✓  " if self.sections.isChecked() else "    "
        items: list[MenuItem] = [(mark + tr("По разделам"), self.sections.toggle)]
        if self.s.parallel_books:
            items.append((tr("Сравнить книги"), self.compare_books.emit))
        return [*items, None, *super().more_items()]

    def title(self) -> str:
        return tr("ОСВ")

    @staticmethod
    def _with_subconto(rows: list[OsvRow], subconto) -> list[OsvRow]:
        """Insert the rows of every subconto under each account, as in 1C: a counterparty,
        its contracts under it (D110)."""
        result = []
        for r in rows:
            result.append(r)
            if r.is_group:
                continue
            for s in subconto.get(r.account_id, []):
                row = OsvRow(
                    account_id=r.account_id,
                    name="      " * (s.depth + 1) + s.name,
                    depth=r.depth + 1,
                    subconto=s.path,
                )
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
                row = CurrencyLine(name=f"      {c.code}  ·  {tr('в валюте')}", depth=r.depth + 1)
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
            tone=lambda r: "currency" if isinstance(r, CurrencyLine) else None,
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
        """The card of the account — or of the counterparty (contract) of a subconto row."""
        if row and row.account_id:
            params = replace(self.params, subconto=row.subconto)
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
        return self._account_actions(row.account_id) + self._class_actions(row.account_id)
