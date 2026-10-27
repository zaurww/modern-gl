"""«Закрытие периода» (D95): up to which day the books are closed — there a posted
document is not changed in place, only reversed (D5). The usual ends of a period are one
click away; drafts that could not be posted afterwards are told before closing."""

from __future__ import annotations

from datetime import date

from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QMessageBox, QVBoxLayout

from modern_gl.application.period import closed_through, drafts_through, period_ends
from modern_gl.desktop.reason_dialog import ask_reason
from modern_gl.desktop.session import Session
from modern_gl.desktop.theme import fonts
from modern_gl.desktop.widgets import button, caption, date_edit, edited_date, ru_date, to_qdate
from modern_gl.domain.dates import iso_date, next_day
from modern_gl.domain.errors import LedgerError
from modern_gl.i18n import tr


def period_text(closed: str | None) -> str:
    """How the period stands, in a word: for the menu and the dialog."""
    if closed is None:
        return tr("Все периоды открыты")
    return tr("Период закрыт по {day}", day=ru_date(closed))


class PeriodDialog(QDialog):
    def __init__(self, session: Session, parent=None) -> None:
        super().__init__(parent)
        self.s = session
        self.closed = closed_through(session.conn, session.company_id)
        self.setWindowTitle(tr("Закрытие периода"))
        self.setMinimumWidth(480)
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 20)
        root.setSpacing(12)
        title = QLabel(period_text(self.closed))
        title.setFont(fonts().heading)
        root.addWidget(title)
        why = caption(
            tr(
                "В закрытом периоде проведённые документы не меняются и не удаляются: "
                "исправление — только сторно датой открытого периода."
            )
        )
        why.setWordWrap(True)
        root.addWidget(why)
        root.addSpacing(6)
        root.addLayout(self._date_row())
        root.addLayout(self._ends_row())
        self.warning = QLabel()
        self.warning.setObjectName("warning")
        self.warning.setWordWrap(True)
        root.addWidget(self.warning)
        root.addStretch(1)
        root.addLayout(self._buttons())
        self.check()

    def _date_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.addWidget(QLabel(tr("Закрыть по")))
        start = period_ends(self.s.working_date)[0].day
        if self.closed is not None and date.fromisoformat(self.closed) > start:
            start = date.fromisoformat(self.closed)
        self.through = date_edit(start)
        self.through.dateChanged.connect(lambda _: self.check())
        row.addWidget(self.through)
        row.addStretch(1)
        return row

    def _ends_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(4)
        for end in period_ends(self.s.working_date):
            b = button(f"{tr(end.title)} · {ru_date(iso_date(end.day))}", "flat")
            b.clicked.connect(lambda _=False, d=end.day: self.through.setDate(to_qdate(d)))
            row.addWidget(b)
        row.addStretch(1)
        return row

    def _buttons(self) -> QHBoxLayout:
        row = QHBoxLayout()
        self.reopen = button(tr("Открыть все периоды"), "danger")
        self.reopen.clicked.connect(self.open_all)
        self.reopen.setVisible(self.closed is not None)
        row.addWidget(self.reopen)
        row.addStretch(1)
        cancel, self.ok = button(tr("Отмена")), button(tr("Закрыть период"), "primary")
        cancel.clicked.connect(self.reject)
        self.ok.clicked.connect(self.close_period)
        row.addWidget(cancel)
        row.addWidget(self.ok)
        return row

    def day(self) -> str:
        return iso_date(edited_date(self.through))

    def check(self) -> None:
        """Drafts that would stay drafts; an earlier day opens part of the closed period."""
        day = self.day()
        notes = []
        drafts = drafts_through(self.s.conn, self.s.company_id, day)
        if drafts:
            notes.append(
                tr(
                    "Черновиков по {day}: {n} — пока период закрыт, их нельзя провести.",
                    day=ru_date(day),
                    n=drafts,
                )
            )
        if self.closed is not None and day < self.closed:
            notes.append(
                tr(
                    "Период с {start} по {end} снова станет открытым.",
                    start=ru_date(next_day(day)),
                    end=ru_date(self.closed),
                )
            )
        self.warning.setText("\n".join(notes))
        self.warning.setVisible(bool(notes))
        opens = self.closed is not None and day < self.closed
        self.ok.setText(tr("Открыть часть периода") if opens else tr("Закрыть период"))
        self.ok.setEnabled(day != self.closed)

    def close_period(self) -> None:
        day = self.day()
        if self.closed is not None and day < self.closed:  # opens a part: why?
            reason = ask_reason(
                self,
                tr("Закрытие периода"),
                tr(
                    "Открыть период после {day}? Проведённые документы в нём снова можно "
                    "будет менять.",
                    day=ru_date(day),
                ),
                tr("Открыть часть периода"),
            )
            if reason is not None:
                self._set(day, reason)
            return
        self._set(day)

    def open_all(self) -> None:
        reason = ask_reason(
            self,
            tr("Закрытие периода"),
            tr("Открыть все периоды? Проведённые документы снова можно будет менять."),
            tr("Открыть все периоды"),
        )
        if reason is not None:
            self._set(None, reason)

    def _set(self, day: str | None, reason: str = "") -> None:
        try:
            self.s.ledger.set_closed_through(self.s.company_id, day, reason)
        except LedgerError as e:
            QMessageBox.warning(self, tr("Закрытие периода"), str(e))
            return
        self.s.notify(period_text(day))
        self.accept()
