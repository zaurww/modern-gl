"""«На дату курс не загружен» under a currency form (a document, a bank operation, a
conversion) and its button: the Central Bank's rates of the date loaded right from there."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton

from modern_gl.desktop.session import Session
from modern_gl.desktop.widgets import button
from modern_gl.domain.dates import ru_date
from modern_gl.domain.errors import LedgerError
from modern_gl.i18n import tr


def rate_note(tooltip: str) -> tuple[QFrame, QLabel, QPushButton]:
    """The note (hidden until a rate is missing), its text and «Загрузить курс ЦБА»."""
    frame = QFrame()
    frame.setObjectName("note")
    row = QHBoxLayout(frame)
    row.setContentsMargins(14, 8, 8, 8)
    text = QLabel()
    text.setWordWrap(True)
    row.addWidget(text, 1)
    load = button(tr("Загрузить курс ЦБА"), "flat", tooltip)
    row.addWidget(load)
    frame.hide()
    return frame, text, load


def load_day_rates(session: Session, day: date, show_error: Callable[[str], None]) -> bool:
    """The Central Bank's rates of `day` into the company, told in a toast; an error goes
    to `show_error`. Whether they were loaded — then the form takes them."""
    QGuiApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
    try:
        count = session.ledger.import_rates(session.company_id, day, session.fetch_rates(day))
    except LedgerError as e:
        show_error(str(e))
        return False
    finally:
        QGuiApplication.restoreOverrideCursor()
    session.notify(tr("Курсы ЦБА на {date} загружены: {n}", date=ru_date(day.isoformat()), n=count))
    return True
