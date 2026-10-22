"""«Покупки / Alış» and «Продажи / Satış»: two sections apart from the warehouse (D46).
A purchase is a receipt (goods, services, fixed assets), a sale a sale document; lines with
an item still move stock."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QAbstractItemView, QLineEdit, QMessageBox

from modern_gl.application.inventory import Inventory
from modern_gl.application.trade_batch import BulkPosting, post_drafts
from modern_gl.desktop.eqaime_import_page import EqaimeImportDialog
from modern_gl.desktop.eqaime_reconciliation_page import EqaimeReconciliationDialog
from modern_gl.desktop.reports_page import Column, ReportPage
from modern_gl.desktop.session import Session
from modern_gl.desktop.widgets import EmptyState, button, status_icon
from modern_gl.domain.dates import ru_date
from modern_gl.domain.money import format_minor
from modern_gl.i18n import fold, tr
from modern_gl.reporting.trade import PURCHASE, SALE, TradeDocument, trade_documents


@dataclass(frozen=True)
class TradeKind:
    doc_type: str
    key: tuple
    title: str
    new: str
    counterparty: str
    empty: str
    empty_hint: str
    footer: str


KINDS = {
    PURCHASE: TradeKind(
        PURCHASE,
        ("purchases",),
        "Покупки",
        "+ Покупка",
        "Поставщик",
        "Покупок пока нет",
        "Товары, услуги и ОС от поставщика.",
        "Проведено покупок: {total}",
    ),
    SALE: TradeKind(
        SALE,
        ("sales",),
        "Продажи",
        "+ Продажа",
        "Покупатель",
        "Продаж пока нет",
        "Товары и услуги покупателю.",
        "Проведено продаж: {total}",
    ),
}


class TradePage(ReportPage):
    has_period = False
    open_inventory_document = Signal(int)
    new_inventory_document = Signal(str)
    imported = Signal()  # drafts created from the portal or posted: the other section too

    def __init__(self, session: Session, doc_type: str) -> None:
        self.kind = KINDS[doc_type]
        self.key = self.kind.key
        super().__init__(session, tr(self.kind.title))
        self.search = QLineEdit()
        self.search.setObjectName("search")
        self.search.setPlaceholderText(tr("Контрагент, VÖEN или e-qaimə"))
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(lambda _text: self.refresh())
        self.header.add_action(self.search)
        load = button(tr("E-qaimə с портала…"), "flat")
        load.setToolTip(tr("Вход через ASAN İmza, e-qaimə за период — черновиками"))
        load.clicked.connect(self.import_eqaime)
        self.header.add_action(load)
        check = button(tr("Сверка с порталом…"), "flat")
        check.setToolTip(tr("E-qaimə месяца на портале против книги: что забыто, что изменилось"))
        check.clicked.connect(self.reconcile)
        self.header.add_action(check)
        # drafts of one supplier are booked alike: filter them, post them at once (D73)
        self.post_button = button("", "flat")
        self.post_button.setToolTip(
            tr(
                "Выделенные черновики (Ctrl, Shift) или все черновики списка. Строке без "
                "счёта — счёт, как в прошлой покупке у этого поставщика"
            )
        )
        self.post_button.clicked.connect(self.post_drafts)
        self.header.add_action(self.post_button)
        self.new_button = button(tr(self.kind.new))
        self.new_button.clicked.connect(lambda: self.new_inventory_document.emit(doc_type))
        self.header.add_action(self.new_button)
        self.stack.removeWidget(self.empty)
        self.empty = EmptyState("○", tr(self.kind.empty), tr(self.kind.empty_hint))
        self.stack.addWidget(self.empty)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.selectionModel().selectionChanged.connect(lambda *_: self._show_post_button())
        self.refresh()

    def title(self) -> str:
        return tr(self.kind.title)

    def build(self) -> None:
        rows = trade_documents(self.s.conn, self.s.company_id, self.kind.doc_type)
        needle = fold(self.search.text().strip())
        if needle:
            rows = [
                r for r in rows if needle in fold(f"{r.counterparties} {r.tax_ids} {r.invoice}")
            ]
        self.model.set(
            [
                Column(tr("Дата"), lambda r: ru_date(r.doc_date), width=100),
                Column(tr("№"), lambda r: r.number, width=60),
                Column(tr(self.kind.counterparty), lambda r: r.counterparties),
                Column(tr("E-qaimə"), lambda r: r.invoice, width=150),
                Column(tr("Сумма"), lambda r: r.amount, money=True, width=120),
                Column(tr("ƏDV"), lambda r: r.vat, money=True, width=100),
                Column(tr("Итого"), lambda r: r.total, money=True, width=120),
                Column(
                    tr("Статус"),
                    self._status,
                    width=120,
                    icon=lambda r: status_icon(r.status == "posted"),
                    # what is left to check reads as usual; posted ones go quiet
                    tone=lambda r: "secondary" if r.status == "posted" else None,
                ),
            ],
            rows,
        )
        self.header.subtitle.setText(tr("Документов: {n}", n=len(rows)))
        total = sum(r.total for r in rows if r.status == "posted")
        self.footer.setText(tr(self.kind.footer, total=format_minor(total)))
        self._show_post_button()

    def drafts_to_post(self) -> list[TradeDocument]:
        """The drafts among the selected rows when several are selected, else all the
        drafts of the list (as the search left it)."""
        selected = {i.row() for i in self.table.selectionModel().selectedRows()}
        rows = self.model.rows
        if len(selected) > 1:
            rows = [rows[i] for i in sorted(selected) if i < len(rows)]
        return [r for r in rows if r.status != "posted"]

    def _show_post_button(self) -> None:
        n = len(self.drafts_to_post())
        self.post_button.setText(tr("Провести черновики: {n}", n=n))
        self.post_button.setVisible(n > 0)

    def post_drafts(self) -> None:
        drafts = self.drafts_to_post()
        if not drafts:
            return
        names = ", ".join(sorted({r.counterparties for r in drafts if r.counterparties}))
        question = tr("Провести черновики: {n}?\n{names}", n=len(drafts), names=names)
        if QMessageBox.question(self, tr("Провести"), question) != QMessageBox.StandardButton.Yes:
            return
        inventory = Inventory(self.s.conn, actor=self.s.ledger.actor)
        result = post_drafts(inventory, self.s.company_id, [r.id for r in drafts])
        self.refresh()
        self.imported.emit()
        self._report(result)

    def _report(self, result: BulkPosting) -> None:
        text = tr("Проведено: {n}", n=len(result.posted))
        if result.filled:
            text += " · " + tr("счёт как в прошлый раз — строк: {n}", n=result.filled)
        self.s.notify(text)
        if result.failed:
            reasons = "\n".join(f"№{number}: {why}" for number, why in result.failed)
            QMessageBox.warning(
                self,
                tr("Провести"),
                tr("Остались черновиками: {n}\n\n{reasons}", n=len(result.failed), reasons=reasons),
            )

    @staticmethod
    def _status(r: TradeDocument) -> str:
        return tr("Проведён") if r.status == "posted" else tr("Черновик")

    def import_eqaime(self) -> None:
        dialog = EqaimeImportDialog(self.s, self, direction=self.kind.doc_type)
        if dialog.exec() and dialog.created:
            self.refresh()
            self.imported.emit()
            self.s.notify(
                tr("Создано черновиков: {n} — проверьте и проведите", n=len(dialog.created))
            )

    def reconcile(self) -> None:
        dialog = EqaimeReconciliationDialog(self.s, self, direction=self.kind.doc_type)
        dialog.exec()
        self.refresh()  # drafts may have been made from it
        self.imported.emit()
        if dialog.chosen_document is not None:
            self.open_document.emit(dialog.chosen_document)

    def drill(self, row: TradeDocument | None) -> None:
        if row is not None:
            self.open_inventory_document.emit(row.id)
