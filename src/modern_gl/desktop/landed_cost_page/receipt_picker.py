"""The purchases a batch is made of: a declaration of seventy goods is one row, found by its
number; lines one by one only when a part of a purchase is wanted."""

from __future__ import annotations

from modern_gl.application.inventory import format_quantity
from modern_gl.desktop.landed_cost_page.pickers import PickerDialog
from modern_gl.desktop.reports_page import Column
from modern_gl.desktop.session import Session
from modern_gl.domain.dates import ru_date
from modern_gl.i18n import fold, tr
from modern_gl.reporting.inventory import (
    ReceiptDocumentChoice,
    receipt_documents,
    receipt_line_choices,
)


def _basis(row) -> str:
    """«İdxal · YGB 0126…», «e-qaimə MT26…», as the warehouse says it."""
    if not row.invoice:
        return ""
    if row.invoice_kind == "customs":
        return tr("Импорт · ГТД {n}", n=row.invoice)
    return f"e-qaimə {row.invoice}"


def _letters(text: str) -> str:
    return "".join(fold(text).split())


class ReceiptPicker(PickerDialog):
    def __init__(self, session: Session, parent=None) -> None:
        self.lines = receipt_line_choices(session.conn, session.company_id)
        self.documents = receipt_documents(self.lines)
        self.document_columns = [
            Column(tr("Дата"), lambda r: ru_date(r.doc_date), width=96),
            Column("№", lambda r: r.number, width=56),
            Column(tr("Источник"), _basis, width=250),
            Column(tr("Поставщик"), lambda r: r.party or ""),
            Column(tr("Строк"), lambda r: len(r.lines), width=70, right=True),
            Column(tr("Стоимость"), lambda r: r.amount, money=True, width=120),
            Column(tr("Комментарий"), lambda r: r.memo, width=180),
        ]
        self.line_columns = [
            Column(tr("Дата"), lambda r: ru_date(r.doc_date), width=96),
            Column("№", lambda r: r.number, width=56),
            Column(tr("Товар"), lambda r: r.item_name),
            Column(tr("Склад"), lambda r: r.warehouse_name, width=130),
            Column(
                tr("Количество"),
                lambda r: format_quantity(r.quantity, r.precision),
                width=100,
                right=True,
            ),
            Column(tr("Стоимость"), lambda r: r.amount, money=True, width=110),
            Column(tr("Комментарий"), lambda r: r.memo, width=180),
        ]
        super().__init__(
            tr("Партия: поступления"),
            tr(
                "Выберите покупку: в партию войдут все её строки (Ctrl / Shift — несколько). "
                "Поиск — по номеру ГТД, e-qaimə, поставщику, товару."
            ),
            self.document_columns,
            self.documents,
            session,
            parent,
            usual=lambda _row: True,  # the tick switches to the lines, see `_filter`
            all_title=tr("По строкам"),
        )
        self.resize(980, 520)

    def _filter(self, text: str) -> None:
        by_lines = self.show_all.isChecked()
        self.all_rows = self.lines if by_lines else self.documents
        self.columns = self.line_columns if by_lines else self.document_columns
        super()._filter(text)

    def _matches(self, row, needle: str) -> bool:
        if super()._matches(row, needle):
            return True
        words = [_basis(row), row.invoice or "", row.party or ""]
        if isinstance(row, ReceiptDocumentChoice):
            words += [line.item_name for line in row.lines]
        wanted = _letters(needle)  # a number typed without its space: YGB0126…
        return any(wanted in _letters(word) for word in words) or self._customs(row, wanted)

    @staticmethod
    def _customs(row, wanted: str) -> bool:
        """The declaration by its name in either language, whichever the interface has."""
        if row.invoice_kind != "customs" or not row.invoice:
            return False
        return wanted in {_letters(f"{name}{row.invoice}") for name in ("YGB", "ГТД")}

    def chosen(self) -> list:
        """Lines for the batch: a purchase gives all of its own."""
        rows = super().chosen()
        if self.show_all.isChecked():
            return rows
        return [line for document in rows for line in document.lines]


def receipt_picker(session: Session, parent=None) -> ReceiptPicker:
    return ReceiptPicker(session, parent)
