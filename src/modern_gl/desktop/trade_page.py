"""«Покупки и продажи / Alış və satış»: purchases and sales in one list, apart from the
warehouse. A purchase is a receipt (goods, services, fixed assets), a sale a sale document;
lines with an item still move stock."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QComboBox, QLineEdit, QPushButton

from modern_gl.desktop.eqaime_import_page import EqaimeImportDialog
from modern_gl.desktop.reports_page import Column, ReportPage
from modern_gl.desktop.session import Session
from modern_gl.desktop.widgets import EmptyState, button
from modern_gl.domain.dates import ru_date
from modern_gl.domain.money import format_minor
from modern_gl.i18n import fold, tr
from modern_gl.reporting.trade import PURCHASE, SALE, TradeDocument, trade_documents

KINDS = [(None, "Все"), (PURCHASE, "Покупки"), (SALE, "Продажи")]


class TradePage(ReportPage):
    key = ("trade",)
    has_period = False
    open_inventory_document = Signal(int)
    new_inventory_document = Signal(str)

    def __init__(self, session: Session) -> None:
        super().__init__(session, tr("Покупки и продажи"))
        self.kind = QComboBox()
        for kind, name in KINDS:
            self.kind.addItem(tr(name), kind)
        self.kind.activated.connect(lambda _index: self.refresh())
        self.header.add_action(self.kind)
        self.search = QLineEdit()
        self.search.setObjectName("search")
        self.search.setPlaceholderText(tr("Контрагент, VÖEN или e-qaimə"))
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(lambda _text: self.refresh())
        self.header.add_action(self.search)
        self.new_buttons: dict[str, QPushButton] = {}
        load = button(tr("E-qaimə с портала…"), "flat")
        load.setToolTip(tr("Вход через ASAN İmza, e-qaimə за период — черновиками"))
        load.clicked.connect(self.import_eqaime)
        self.header.add_action(load)
        for title, doc_type, kind in (("+ Покупка", PURCHASE, "flat"), ("+ Продажа", SALE, "")):
            control = button(tr(title), kind)
            control.clicked.connect(lambda _=False, t=doc_type: self.new_inventory_document.emit(t))
            self.header.add_action(control)
            self.new_buttons[doc_type] = control
        self.stack.removeWidget(self.empty)
        self.empty = EmptyState(
            "○",
            tr("Покупок и продаж пока нет"),
            tr("Покупка — товары, услуги и ОС от поставщика; продажа — товары и услуги."),
        )
        self.stack.addWidget(self.empty)
        self.refresh()

    def title(self) -> str:
        return tr("Покупки и продажи")

    def build(self) -> None:
        rows = trade_documents(self.s.conn, self.s.company_id, self.kind.currentData())
        needle = fold(self.search.text().strip())
        if needle:
            rows = [
                r for r in rows if needle in fold(f"{r.counterparties} {r.tax_ids} {r.invoice}")
            ]
        self.model.set(
            [
                Column(tr("Дата"), lambda r: ru_date(r.doc_date), width=100),
                Column(tr("№"), lambda r: r.number, width=60),
                Column(tr("Операция"), self._kind, width=110),
                Column(tr("Контрагент"), lambda r: r.counterparties),
                Column(tr("E-qaimə"), lambda r: r.invoice, width=150),
                Column(tr("Сумма"), lambda r: r.amount, money=True, width=120),
                Column(tr("ƏDV"), lambda r: r.vat, money=True, width=100),
                Column(tr("Итого"), lambda r: r.total, money=True, width=120),
                Column(tr("Статус"), self._status, width=100),
            ],
            rows,
        )
        self.header.subtitle.setText(tr("Документов: {n}", n=len(rows)))
        bought = sum(r.total for r in rows if r.doc_type == PURCHASE and r.status == "posted")
        sold = sum(r.total for r in rows if r.doc_type == SALE and r.status == "posted")
        self.footer.setText(
            tr(
                "Проведено: покупки {bought}   ·   продажи {sold}",
                bought=format_minor(bought),
                sold=format_minor(sold),
            )
        )

    @staticmethod
    def _kind(r: TradeDocument) -> str:
        return tr("Покупка") if r.doc_type == PURCHASE else tr("Продажа")

    @staticmethod
    def _status(r: TradeDocument) -> str:
        return tr("Проведён") if r.status == "posted" else tr("Черновик")

    def import_eqaime(self) -> None:
        dialog = EqaimeImportDialog(self.s, self)
        if dialog.exec() and dialog.created:
            self.refresh()
            self.s.notify(
                tr("Создано черновиков: {n} — проверьте и проведите", n=len(dialog.created))
            )

    def drill(self, row: TradeDocument | None) -> None:
        if row is not None:
            self.open_inventory_document.emit(row.id)
