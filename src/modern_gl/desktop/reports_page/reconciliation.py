"""Акт сверки (üzləşmə aktı): the settlements with one counterparty over the period, a
line per document — the counterparty is chosen on the page; «⋯ → Акт в Excel» writes
the form both sides sign, «Акты всем контрагентам» — a file for each one that owed,
was owed or moved. A line leads to its document."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QStandardPaths, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QFileDialog, QMessageBox

from modern_gl.application.posting_preview import PreviewPosting, gl_postings
from modern_gl.desktop.pick import PickBox
from modern_gl.desktop.preferences import RECONCILIATION_PARTNER, prefs
from modern_gl.desktop.reports_page.account import document_text
from modern_gl.desktop.reports_page.export import file_name
from modern_gl.desktop.reports_page.subconto_card import Edge
from modern_gl.desktop.reports_page.view import Column, ReportPage, ReportParams
from modern_gl.desktop.session import Session
from modern_gl.desktop.widgets import MenuItem, balance_text, caption, ru_date
from modern_gl.domain.accounts import SETTLEMENT_TYPES
from modern_gl.i18n import tr
from modern_gl.infrastructure.act_file import write_act_xlsx
from modern_gl.infrastructure.db import Connection
from modern_gl.reporting import reports
from modern_gl.reporting.reconciliation_form import act_file_name, act_sheet, debt_text
from modern_gl.reporting.reports import ActLine, ReconciliationAct


class ReconciliationActPage(ReportPage):
    key = ("reconciliation_act",)

    def __init__(
        self, session: Session, params: ReportParams | None = None, value_id: int | None = None
    ) -> None:
        super().__init__(session, tr("Акт сверки"), params)
        self.act: ReconciliationAct | None = None
        self.partner = PickBox(tr("Контрагент"))
        self.partner.setMinimumWidth(260)
        self.kinds = self._kinds()
        for kind_id in self.kinds:
            for v in self.s.catalog.values(kind_id):
                self.partner.addItem(v.label, v.id, v.name)
        wanted = prefs().chosen_id(RECONCILIATION_PARTNER) if value_id is None else value_id
        if (at := self.partner.findData(wanted)) >= 0:
            self.partner.setCurrentIndex(at)
        self.add_to_bar(caption(tr("Контрагент")), self.partner, gap=0)
        self.partner.activated.connect(self._choose_partner)
        self.empty.say(tr("Выберите контрагента"), tr("Акт собирается по счетам расчётов с ним."))
        self.refresh()

    def _kinds(self) -> list[int]:
        """The directories an act is made for: the counterparties — or, without such a
        directory, whatever the settlement accounts carry first."""
        cat = self.s.catalog
        kinds = [k for k, code in cat.kind_codes.items() if code == "counterparty"]
        if not kinds:
            kinds = sorted(
                {
                    a.sc_kinds[0]
                    for a in cat.accounts.values()
                    if a.account_type in SETTLEMENT_TYPES and a.sc_kinds[0] is not None
                }
            )
        return kinds

    @property
    def value_id(self) -> int | None:
        return self.partner.currentData()

    def _choose_partner(self, _index: int) -> None:
        prefs().set_chosen_id(RECONCILIATION_PARTNER, self.value_id)
        self.refresh()

    def title(self) -> str:
        title = tr("Акт сверки")
        if self.value_id is None:
            return title
        return f"{title} · {self.s.catalog.value(self.value_id).name}"

    # ---- the report ------------------------------------------------------------------

    def fetch(self, conn: Connection) -> ReconciliationAct | None:
        if self.value_id is None:
            return None
        p = self.params
        return reports.reconciliation_act(
            conn, self.s.company_id, self.value_id, p.date_from, p.date_to, p.layers
        )

    def present(self, data: ReconciliationAct | None) -> None:
        self.act = act = data
        self.header.title.setText(self.title())
        self.title_changed.emit()
        if act is None:
            self.model.set(self._columns(False), [])
            self.footer.setText("")
            return
        opening = Edge(tr("Сальдо на начало"), act.opening)
        closing = Edge(tr("Обороты и сальдо на конец"), act.closing, act.debit, act.credit)
        self.model.set(
            self._columns(any(ln.invoice for ln in act.lines)),
            [opening, *act.lines, closing] if act.lines else [],
            emphasis=lambda ln: ln is closing,
            muted=lambda ln: ln is opening,
            total=lambda ln: ln is closing,
        )
        self.footer.setText(debt_text(act, tr))

    def _columns(self, invoices: bool) -> list[Column]:
        one_year = self.params.date_from.year == self.params.date_to.year
        columns = [
            Column(tr("Дата"), lambda ln: self._date(ln.doc_date, one_year), width=1),
            Column(tr("Документ"), document_text, width=1),
            Column(tr("Содержание"), lambda ln: ln.memo),
            Column(tr("Дт"), lambda ln: ln.debit, money=True, group=tr("По нашим данным")),
            Column(tr("Кт"), lambda ln: ln.credit, money=True, group=tr("По нашим данным")),
            Column(
                tr("Сальдо"),
                lambda ln: balance_text(ln.balance) if ln.balance else "",
                right=True,
                value=lambda ln: ln.balance,  # in Excel: Dt +, Kt −
            ),
        ]
        if invoices:
            columns.insert(3, Column(tr("E-qaimə"), lambda ln: ln.invoice, width=1))
        return columns

    @staticmethod
    def _date(iso: str, one_year: bool) -> str:
        text = ru_date(iso) if iso else ""
        return text[:5] if one_year else text

    def drill(self, row) -> None:
        if row is not None and row.document_id:
            self.open_document.emit(row.document_id)

    def row_postings(self) -> list[PreviewPosting] | None:
        row = self.current_row()
        if not isinstance(row, ActLine):
            return None
        return gl_postings(self.s.conn, self.s.company_id, row.document_id)

    # ---- the form ------------------------------------------------------------------

    def more_items(self) -> list[MenuItem]:
        return [
            (tr("Акт в Excel…"), self.save_act),
            (tr("Акты всем контрагентам…"), self.save_all_acts),
            None,
            *super().more_items(),
        ]

    def save_act(self) -> None:
        """The act of the chosen counterparty as the form to sign — a file of its own."""
        act = self.act
        if act is None:
            self.s.notify(tr("Выберите контрагента"))
            return
        target, _ = QFileDialog.getSaveFileName(
            self,
            tr("Акт в Excel"),
            str(Path(_documents()) / file_name(act_file_name(act))),
            "Excel (*.xlsx)",
        )
        if target and self._write(lambda: write_act_xlsx(act_sheet(act), target)):
            QDesktopServices.openUrl(QUrl.fromLocalFile(target))

    def save_all_acts(self) -> None:
        """A file for each counterparty that owed, was owed or moved by the end of the
        period — into a folder chosen; the folder opens after."""
        folder = QFileDialog.getExistingDirectory(self, tr("Акты всем контрагентам"), _documents())
        if not folder:
            return
        p, cid = self.params, self.s.company_id
        partners = [
            partner
            for kind_id in self.kinds
            for partner in reports.act_partners(
                self.s.conn, cid, kind_id, p.date_from, p.date_to, p.layers
            )
        ]

        def write_all() -> None:
            for partner in partners:
                act = reports.reconciliation_act(
                    self.s.conn, cid, partner.value_id, p.date_from, p.date_to, p.layers
                )
                write_act_xlsx(act_sheet(act), Path(folder) / file_name(act_file_name(act)))

        if self._write(write_all):
            self.s.notify(tr("Сохранено актов: {n}", n=len(partners)))
            QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

    def _write(self, write: Callable[[], None]) -> bool:
        try:
            write()
        except OSError as e:
            QMessageBox.warning(self, tr("Акт в Excel"), tr("Не удалось сохранить файл: {e}", e=e))
            return False
        return True


def _documents() -> str:
    return QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation)
