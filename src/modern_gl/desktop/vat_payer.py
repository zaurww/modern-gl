"""«Плательщик ƏDV с…» (D145): the day the company became a payer of ƏDV, asked from
the company's menu; empty — a payer all along. Before that day the ƏDV reports owe and
credit nothing."""

from __future__ import annotations

from datetime import date

from PySide6.QtWidgets import QInputDialog, QMessageBox, QWidget

from modern_gl.application.vat import payer_from
from modern_gl.desktop.session import Session
from modern_gl.domain.dates import ru_date
from modern_gl.domain.errors import LedgerError
from modern_gl.domain.period_input import parse_date
from modern_gl.i18n import N_, tr

TITLE = N_("Плательщик ƏDV")
# the reports that count by the day (page keys)
VAT_REPORTS = ("vat_liability", "vat_credit", "vat_receipts", "vat_payments")


def payer_note(since: str, date_from: date) -> str:
    """What a report of a period says when the company paid ƏDV only from a later day."""
    if not since or since <= date_from.isoformat():
        return ""
    return tr(
        "Плательщик ƏDV с {day}: до этого дня ƏDV не начисляется и не зачитывается",
        day=ru_date(since),
    )


def edit_vat_payer(parent: QWidget, session: Session) -> bool:
    """Ask the day; True when it changed."""
    current = payer_from(session.conn, session.company_id)
    text = ru_date(current) if current else ""
    while True:
        text, ok = QInputDialog.getText(
            parent,
            tr(TITLE),
            tr("Плательщик ƏDV с даты (ДД.ММ.ГГГГ; пусто — с самого начала):"),
            text=text,
        )
        if not ok:
            return False
        day = parse_date(text, session.working_date) if text.strip() else None
        if text.strip() and day is None:
            QMessageBox.warning(parent, tr(TITLE), tr("Не понял дату: {text}", text=text))
            continue
        try:
            session.ledger.set_vat_payer_from(session.company_id, day)
        except LedgerError as e:
            QMessageBox.warning(parent, tr(TITLE), str(e))
            continue
        return (day.isoformat() if day else "") != current
