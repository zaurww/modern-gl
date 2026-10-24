"""All the warehouse documents, under the stock list: open one, delete one."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHeaderView, QMessageBox, QTableView

from modern_gl.desktop.inventory_page.form import InventoryForm
from modern_gl.desktop.reports_page import Column, ReportModel
from modern_gl.desktop.reports_page.table import ROW_HEIGHT, ReportDelegate
from modern_gl.desktop.widgets import list_table, ru_date
from modern_gl.domain.errors import LedgerError
from modern_gl.i18n import tr
from modern_gl.reporting.inventory import InventoryDocumentSummary, list_inventory_documents


class DocumentsPart(InventoryForm):
    def _build_documents(self) -> QTableView:
        self.documents_model = ReportModel()
        self.documents = list_table(self.documents_model, ROW_HEIGHT, wrap=False)
        self.documents.setItemDelegate(ReportDelegate(self.documents))  # as the stock above
        self.documents.doubleClicked.connect(
            lambda index: self._open_document(index.data(Qt.ItemDataRole.UserRole))
        )
        return self.documents

    def _show_documents(self) -> None:
        """The warehouse documents; the drafts are counted on the switch, not to be lost."""
        documents = list_inventory_documents(self.s.conn, self.s.company_id)
        drafts = sum(d.status != "posted" for d in documents)
        self.documents_button.setText(
            tr("Документы · черновиков: {n}", n=drafts) if drafts else tr("Документы")
        )
        self.documents_model.set(
            [
                Column(tr("Дата"), lambda row: ru_date(row.doc_date), width=110),
                Column(tr("№"), lambda row: row.number, width=65),
                Column(
                    tr("Операция"),
                    lambda row: self._document_type(row.doc_type),
                    width=170,
                ),
                Column(
                    tr("Статус"),
                    lambda row: tr("Проведён") if row.status == "posted" else tr("Черновик"),
                    width=105,
                ),
                Column(tr("Статья расходов"), lambda row: row.cost_type_name, width=160),
                Column(tr("Комментарий"), lambda row: row.memo, width=260),
                Column(tr("Сумма"), lambda row: row.amount, money=True, width=130),
            ],
            documents,
        )
        docs_header = self.documents.horizontalHeader()
        for index, column in enumerate(self.documents_model.columns):
            docs_header.setSectionResizeMode(index, QHeaderView.ResizeMode.Interactive)
            if column.width:
                self.documents.setColumnWidth(index, column.width)
        docs_header.setStretchLastSection(True)

    @staticmethod
    def _document_type(doc_type: str) -> str:
        return {
            "opening": tr("Начальные остатки"),
            "receipt": tr("Покупка"),
            "incoming": tr("Оприходование"),
            "issue": tr("Списание"),
            "sale": tr("Продажа"),
            "transfer": tr("Перемещение"),
            "landed_cost": tr("Дополнительные расходы"),
        }.get(doc_type, doc_type)

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
