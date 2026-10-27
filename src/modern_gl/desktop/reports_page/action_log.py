"""«Журнал действий» (D178): who did what in the company, when and why — the
company opened and closed, on which computer, too (`application/action_log`). A double
click opens the document of an event; the period and «Кто» narrow the list."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtWidgets import QComboBox

from modern_gl.application.action_log import LIMIT, LogEvent, LogFilter, action_log, log_actors
from modern_gl.application.authorship import local_time
from modern_gl.desktop.reports_page.view import Column, ReportPage, ReportParams
from modern_gl.desktop.session import Session
from modern_gl.desktop.widgets import EmptyState, caption
from modern_gl.i18n import tr
from modern_gl.infrastructure.db import Connection


def subject_text(e: LogEvent) -> str:
    return f"{tr(e.kind)} {e.subject}".strip()


class ActionLogPage(ReportPage):
    key = ("action_log",)
    has_book = False  # events, not the books

    def __init__(self, session: Session, params: ReportParams | None = None) -> None:
        super().__init__(session, tr("Журнал действий"), params)
        self.actor = QComboBox()
        self.actor.setMinimumWidth(180)
        self.fill_actors()
        self.actor.currentIndexChanged.connect(lambda _i: self.refresh())
        self.add_to_bar(caption(tr("Кто")), self.actor)
        self.stack.removeWidget(self.empty)
        self.empty = EmptyState(
            "○",
            tr("За период действий нет"),
            tr("Здесь — кто открывал компанию, что вводил, проводил, исправлял и удалял."),
        )
        self.stack.addWidget(self.empty)
        self.refresh()

    def fill_actors(self) -> None:
        """«Все» and everybody the company's log names."""
        chosen = self.actor.currentData() or ""
        self.actor.blockSignals(True)
        self.actor.clear()
        self.actor.addItem(tr("Все"), "")
        for name in log_actors(self.s.conn, self.s.company_id):
            self.actor.addItem(name, name)
        self.actor.setCurrentIndex(max(0, self.actor.findData(chosen)))
        self.actor.blockSignals(False)

    def title(self) -> str:
        return tr("Журнал действий")

    def job(self) -> Callable[[Connection], list[LogEvent]]:
        flt = LogFilter(
            self.s.company_id,
            self.params.date_from,
            self.params.date_to,
            str(self.actor.currentData() or ""),
        )
        return lambda conn: action_log(conn, flt)

    def fetch(self, conn: Connection) -> list[LogEvent]:
        return self.job()(conn)

    def present(self, data: list[LogEvent]) -> None:
        columns = [
            Column(tr("Когда"), lambda e: local_time(e.at), width=130),
            Column(tr("Кто"), lambda e: e.actor),
            Column(tr("Что"), lambda e: tr(e.action)),
            Column(tr("Объект"), subject_text),
            Column(tr("Причина"), lambda e: e.reason),
        ]
        if any(e.computer for e in data):
            columns.append(Column(tr("Компьютер"), lambda e: e.computer, key="computer"))
        self.model.set(columns, data)
        more = tr("Показаны последние {n} — сузьте период или выберите, кто", n=LIMIT)
        self.footer.setText(more if len(data) >= LIMIT else "")

    def drill(self, row: LogEvent | None) -> None:
        if row is None or row.document_id is None:
            return
        if self.s.stock_only and row.entity == "document":  # D90: no GL documents
            return
        self.open_document.emit(row.document_id)
