"""The papers of a cash desk from the page (D-new-cash): «⋯ → Кассовая книга в Excel» for
the days shown, «⋯ → Кассовый ордер в Excel» for a line. Reading only: a company open for
viewing prints them too."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QStandardPaths, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QFileDialog, QMessageBox, QWidget

from modern_gl.application.bank import BankPlace
from modern_gl.application.bank.cash_book import cash_book, cash_order
from modern_gl.desktop.reports_page.export import file_name
from modern_gl.desktop.session import Session
from modern_gl.domain.dates import ru_date
from modern_gl.domain.errors import LedgerError
from modern_gl.i18n import tr, trd
from modern_gl.infrastructure.cash_file import write_cash_book_xlsx, write_cash_order_xlsx


def save_cash_book(
    parent: QWidget, s: Session, place: BankPlace, date_from: str, date_to: str
) -> None:
    book = cash_book(s.conn, s.company_id, place, date_from, date_to)
    if not book.days:
        s.notify(tr("В эти дни касса не двигалась"))
        return
    name = f"{trd('Кассовая книга')} {ru_date(date_from)[:5]}-{ru_date(date_to)}.xlsx"
    _save(parent, tr("Кассовая книга в Excel"), name, lambda t: write_cash_book_xlsx(book, t))


def save_cash_order(parent: QWidget, s: Session, place: BankPlace, document_id: int) -> None:
    try:
        order = cash_order(s.conn, s.company_id, place, document_id)
    except LedgerError as e:
        s.notify(str(e))
        return
    kind = trd("Приходный кассовый ордер") if order.incoming else trd("Расходный кассовый ордер")
    name = f"{kind} {order.number}.xlsx"
    _save(parent, tr("Кассовый ордер в Excel"), name, lambda t: write_cash_order_xlsx(order, t))


def _save(parent: QWidget, title: str, name: str, write: Callable[[str], None]) -> None:
    """Ask where, write, open the file in Excel."""
    folder = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation)
    target, _ = QFileDialog.getSaveFileName(
        parent, title, str(Path(folder) / file_name(name)), "Excel (*.xlsx)"
    )
    if not target:
        return
    try:
        write(target)
    except OSError as e:
        QMessageBox.warning(parent, title, tr("Не удалось сохранить файл: {e}", e=e))
        return
    QDesktopServices.openUrl(QUrl.fromLocalFile(target))
