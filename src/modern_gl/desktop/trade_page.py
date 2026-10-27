"""«Покупки / Alış» and «Продажи / Satış»: two sections apart from the warehouse (D46).
A purchase is a receipt (goods, services, fixed assets), a sale a sale document; lines with
an item still move stock."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QAbstractItemView, QLineEdit, QMessageBox

from modern_gl.application.inventory import Inventory
from modern_gl.application.trade_batch import BulkPosting, open_lines, post_drafts
from modern_gl.desktop.batch_post_dialog import BatchPostDialog
from modern_gl.desktop.eqaime_import_page import EqaimeImportDialog
from modern_gl.desktop.eqaime_reconciliation_page import EqaimeReconciliationDialog
from modern_gl.desktop.reports_page import Column, ReportPage
from modern_gl.desktop.session import Session
from modern_gl.desktop.widgets import (
    EmptyState,
    MenuItem,
    button,
    hide_when_viewing,
    status_icon,
)
from modern_gl.domain.dates import ru_date
from modern_gl.domain.errors import LedgerError
from modern_gl.domain.money import format_minor
from modern_gl.i18n import fold, tr
from modern_gl.reporting.trade import (
    PURCHASE,
    RETURNS_OF,
    SALE,
    TradeDocument,
    trade_documents,
)


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
        # drafts of one supplier are booked alike: filter them, post them at once (D73)
        self.post_button = button("", "flat")
        self.post_button.setToolTip(
            tr(
                "Выделенные черновики (Ctrl, Shift) или все черновики списка. Строкам без "
                "счёта — выбранный счёт или как в прошлой покупке у этого поставщика"
            )
        )
        self.post_button.clicked.connect(self.post_drafts)
        self.header.add_action(self.post_button)
        self.new_button = self.header.primary(
            tr(self.kind.new), lambda: self.new_inventory_document.emit(doc_type)
        )
        hide_when_viewing(session.read_only, self.new_button)
        self.stack.removeWidget(self.empty)
        self.empty = EmptyState("○", tr(self.kind.empty), tr(self.kind.empty_hint))
        self.stack.addWidget(self.empty)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.selectionModel().selectionChanged.connect(lambda *_: self._show_post_button())
        delete = QShortcut(QKeySequence("Del"), self.table)  # not while typing a search
        delete.setContext(Qt.ShortcutContext.WidgetShortcut)
        delete.activated.connect(self.delete_selected)
        self.refresh()

    def more_items(self) -> list[MenuItem]:
        """The portal (ASAN İmza): e-qaimə of a period as drafts; the month against the
        book — in the report's own «⋯», not in a second one."""
        returns = RETURNS_OF[self.kind.doc_type]
        portal: list[MenuItem] = [
            (
                tr("+ Возврат поставщику")
                if self.kind.doc_type == PURCHASE
                else tr("+ Возврат от покупателя"),
                lambda: self.new_inventory_document.emit(returns),
            ),
            None,
            (tr("E-qaimə с портала…"), self.import_eqaime),
            (tr("Сверка с порталом…"), self.reconcile),
            None,
            (tr("Удалить отмеченные…  Del"), self.delete_selected),
            None,
        ]
        return ([] if self.s.read_only else portal) + super().more_items()

    def title(self) -> str:
        return tr(self.kind.title)

    def build(self) -> None:
        rows = trade_documents(self.s.conn, self.s.company_id, self.kind.doc_type)
        needle = fold(self.search.text().strip())
        if needle:
            rows = [
                r
                for r in rows
                if needle in fold(f"{r.counterparties} {r.tax_ids} {self._invoice(r)}")
            ]
        self.model.set(
            [
                Column(tr("Дата"), lambda r: ru_date(r.doc_date), width=100),
                Column(tr("№"), lambda r: r.number, width=60),
                Column(tr(self.kind.counterparty), self._counterparty),
                Column(
                    tr("E-qaimə"),
                    self._invoice,
                    width=150,
                    # goods came before their e-qaimə (D119): what is left to do, louder
                    tone=lambda r: "amber" if r.awaits_invoice else None,
                ),
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
        return [r for r in rows if r.status != "posted" and not r.is_return]

    def _show_post_button(self) -> None:
        n = len(self.drafts_to_post())
        self.post_button.setText(tr("Провести черновики: {n}", n=n))
        self.post_button.setVisible(n > 0 and not self.s.read_only)

    def post_drafts(self) -> None:
        drafts = self.drafts_to_post()
        if not drafts:
            return
        names = ", ".join(sorted({r.counterparties for r in drafts if r.counterparties}))
        inventory = Inventory(self.s.conn, actor=self.s.ledger.actor)
        ids = [r.id for r in drafts]
        # where the lines without an account go: chosen once for all of them (D87)
        lines = open_lines(inventory, self.s.company_id, ids)
        kinds = inventory.sale_kinds(self.s.company_id)
        dialog = BatchPostDialog(self.s, len(drafts), names, lines, kinds, self)
        if not dialog.exec():
            return
        result = post_drafts(inventory, self.s.company_id, ids, dialog.booking)
        self.refresh()
        self.imported.emit()
        self._report(result, chosen=dialog.booking is not None)

    def marked(self) -> list[TradeDocument]:
        """The rows marked (Ctrl or Shift + click), or the one under the cursor."""
        rows = self.model.rows
        selected = {i.row() for i in self.table.selectionModel().selectedRows()}
        return [rows[i] for i in sorted(selected) if i < len(rows)]

    def delete_selected(self) -> None:
        """The marked documents deleted at once — drafts from the portal not needed, say:
        all of them or none (one in the closed period or with its goods sold keeps them
        all). A posted one leaves its full copy in the audit trail."""
        if self.s.read_only:
            return
        marked = self.marked()
        if not marked:
            self.s.notify(tr("Отметьте документы (Ctrl или Shift + щелчок)"))
            return
        question = tr("Удалить отмеченные документы: {n}?", n=len(marked))
        posted = sum(r.status == "posted" for r in marked)
        if posted:
            question += "\n\n" + tr(
                "Проведённых среди них: {n} — их проводки и движение товаров уйдут.", n=posted
            )
        if QMessageBox.question(self, tr("Удалить"), question) != QMessageBox.StandardButton.Yes:
            return
        inventory = Inventory(self.s.conn, actor=self.s.ledger.actor)
        try:
            inventory.delete_documents(self.s.company_id, [r.id for r in marked])
        except LedgerError as e:
            QMessageBox.warning(self, tr("Удалить"), tr("Ничего не удалено: {e}", e=str(e)))
            return
        self.refresh()
        self.imported.emit()
        self.s.notify(tr("Удалено документов: {n}", n=len(marked)))

    def _report(self, result: BulkPosting, chosen: bool = False) -> None:
        text = tr("Проведено: {n}", n=len(result.posted))
        if result.filled and chosen:
            text += " · " + tr("выбранный счёт — строк: {n}", n=result.filled)
        elif result.filled:
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
    def _counterparty(r: TradeDocument) -> str:
        """A return says so before whose it is: «Возврат · Alfa»."""
        return f"{tr('Возврат')} · {r.counterparties}" if r.is_return else r.counterparties

    @staticmethod
    def _invoice(r: TradeDocument) -> str:
        return tr("ждёт e-qaimə") if r.awaits_invoice else r.invoice

    @staticmethod
    def _status(r: TradeDocument) -> str:
        return tr("Проведён") if r.status == "posted" else tr("Черновик")

    def import_eqaime(self) -> None:
        dialog = EqaimeImportDialog(self.s, self, direction=self.kind.doc_type)
        if dialog.exec() and (dialog.created or dialog.attached):
            self.refresh()
            self.imported.emit()
            self.s.notify(dialog.outcome())

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
