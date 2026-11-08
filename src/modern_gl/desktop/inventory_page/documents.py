"""All the warehouse documents, under the stock list: open one, delete one."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox, QTableView

from modern_gl.application.document_kinds import kind_name
from modern_gl.application.posting_preview import PreviewPosting, owned_postings
from modern_gl.desktop.inventory_page.form import InventoryForm
from modern_gl.desktop.list_table import ListTable
from modern_gl.desktop.posting_peek import bind_peek
from modern_gl.desktop.reports_page import Column, ReportModel
from modern_gl.desktop.reports_page.table import ROW_HEIGHT, ReportDelegate
from modern_gl.desktop.table_sort import sortable
from modern_gl.desktop.widgets import ru_date
from modern_gl.domain.errors import LedgerError
from modern_gl.i18n import tr
from modern_gl.reporting.inventory import (
    InventoryDocumentSummary,
    inventory_document_kinds,
    list_inventory_documents,
)


class DocumentsPart(InventoryForm):
    def _build_documents(self) -> QTableView:
        self.documents_model = ReportModel()
        self.documents = ListTable(self.documents_model, ROW_HEIGHT, wrap=False)
        self.documents.setItemDelegate(ReportDelegate(self.documents))  # as the stock above
        sortable(self.documents)
        self.documents.doubleClicked.connect(
            lambda index: self._open_document(index.data(Qt.ItemDataRole.UserRole))
        )
        bind_peek(self.documents, self.s, self._document_postings)
        return self.documents

    def _document_postings(self) -> list[PreviewPosting] | None:
        row = self._selected_document()
        if row is None:
            return None
        return owned_postings(self.s.conn, self.s.company_id, "inventory", [row.id])

    def _show_documents(self) -> None:
        """The latest warehouse documents, or all of the chosen kind; the drafts of the
        latest are counted on the switch, not to be lost."""
        conn, company_id = self.s.conn, self.s.company_id
        kind = self._fill_document_kinds()
        latest = list_inventory_documents(conn, company_id)
        documents = (
            latest if kind is None else list_inventory_documents(conn, company_id, None, kind)
        )
        drafts = sum(d.status != "posted" for d in latest)
        self.documents_button.setText(
            tr("Документы · черновиков: {n}", n=drafts) if drafts else tr("Документы")
        )
        self.documents_model.set(
            [
                Column(
                    tr("Дата"),
                    lambda row: ru_date(row.doc_date),
                    width=110,
                    sort=lambda row: (row.doc_date, row.number),
                ),
                Column(tr("№"), lambda row: row.number, width=65),
                Column(
                    tr("Операция"),
                    lambda row: kind_name(row.doc_type),
                    width=170,
                ),
                Column(
                    tr("Статус"),
                    lambda row: tr("Проведён") if row.status == "posted" else tr("Черновик"),
                    width=105,
                ),
                Column(tr("Статья расходов"), lambda row: row.cost_type_name, width=160),
                Column(tr("Комментарий"), lambda row: row.memo),
                Column(tr("Сумма"), lambda row: row.amount, money=True, width=130),
            ],
            documents,
        )

    def _fill_document_kinds(self) -> str | None:
        """The kinds that exist, the choice kept; the chosen kind (None: all of them)."""
        box = self.document_kind
        chosen = box.currentData()
        kinds = inventory_document_kinds(self.s.conn, self.s.company_id)
        box.blockSignals(True)
        box.clear()
        box.addItem(tr("Все операции"), None)
        for kind in sorted(kinds, key=kind_name):
            box.addItem(kind_name(kind), kind)
        box.setCurrentIndex(max(box.findData(chosen), 0))
        box.blockSignals(False)
        return box.currentData()

    def _selected_document(self) -> InventoryDocumentSummary | None:
        index = self.documents.currentIndex()
        return index.data(Qt.ItemDataRole.UserRole) if index.isValid() else None

    def _open_document(self, row: InventoryDocumentSummary | None) -> None:
        if row is not None:
            self.open_inventory_document.emit(row.id)

    def delete_document(self) -> None:
        row = self._selected_document()
        if row is None:
            self.s.notify(tr("Выберите складской документ"))
            return
        answer = QMessageBox.question(
            self,
            tr("Удалить складской документ"),
            tr("Удалить складской документ №{n}?", n=row.number),
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self.inventory.delete_document(self.s.company_id, row.id)
        except LedgerError as exc:
            self.s.notify(str(exc))
            return
        self.s.notify(tr("Складской документ №{n} удалён", n=row.number))
        self.refresh()
