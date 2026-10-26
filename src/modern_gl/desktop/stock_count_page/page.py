"""The page «Инвентаризация»: a warehouse and a day → what the books hold, already put in
as counted; the user types what differs and posts the difference with one button."""

from __future__ import annotations

from PySide6.QtCore import QSettings, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from modern_gl.application.default_accounts import COST_OF_GOODS, default_account
from modern_gl.application.inventory import Inventory, StockCountResult
from modern_gl.desktop.landed_cost_page.table import CellDelegate, LinesTable
from modern_gl.desktop.pick import PickBox
from modern_gl.desktop.session import Session
from modern_gl.desktop.stock_count_page.model import (
    AMOUNT,
    BOOK,
    DIFFERENCE,
    ITEM,
    QUANTITY,
    UNIT,
    CountModel,
    CountRow,
)
from modern_gl.desktop.widgets import (
    PageHeader,
    button,
    date_edit,
    edited_date,
    enter_goes_on,
    money,
)
from modern_gl.domain.errors import LedgerError
from modern_gl.i18n import tr
from modern_gl.reporting.inventory import item_choices, stock_balances, warehouse_choices

WAREHOUSE_SETTING = "stock_count/warehouse"  # the warehouse counted last
WIDTHS = {ITEM: 320, UNIT: 70, BOOK: 120, QUANTITY: 120, DIFFERENCE: 120, AMOUNT: 140}


class StockCountPage(QWidget):
    key = ("stock_count",)
    posted = Signal()  # the stock changed: «Склад» reads it again
    open_inventory_document = Signal(int)

    def __init__(self, session: Session) -> None:
        super().__init__()
        self.setObjectName("page")
        self.s = session
        self.inventory = Inventory(session.conn, actor=session.ledger.actor)
        root = QVBoxLayout(self)
        root.setContentsMargins(40, 30, 40, 24)
        root.setSpacing(14)
        self.header = PageHeader(
            tr("Инвентаризация"),
            tr("Учёт уже подставлен как факт — впишите количество там, где оно другое"),
        )
        self.post_button = self.header.primary(tr("Провести разницу"), self.post, "Ctrl+Enter")
        root.addWidget(self.header)
        self._build_bar(root)
        self.model = CountModel()
        self.delegate = CellDelegate()
        self.delegate.error.connect(self._show_error)
        self.table = LinesTable(self.model, self.delegate)
        for column, key in enumerate(self.model.columns):
            self.table.setColumnWidth(column, WIDTHS[key])
        root.addWidget(self.table, 1)
        self.error = QLabel()
        self.error.setObjectName("error")
        self.error.setWordWrap(True)
        self.error.hide()
        root.addWidget(self.error)
        self._build_footer(root)
        self.model.changed.connect(self._show_totals)
        for keys in ("Ctrl+Return", "Ctrl+Enter"):
            QShortcut(QKeySequence(keys), self).activated.connect(self.post)
        self.refresh()

    def _build_bar(self, root: QVBoxLayout) -> None:
        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.warehouse = PickBox()
        self.warehouse.setFixedWidth(200)
        for choice in warehouse_choices(self.s.conn, self.s.company_id):
            self.warehouse.addItem(choice.label, choice.id)
        remembered = QSettings().value(WAREHOUSE_SETTING, -1, type=int)
        self.warehouse.setCurrentIndex(max(self.warehouse.findData(remembered), 0))
        self.date = date_edit(self.s.working_date)
        self.date.setFixedWidth(130)
        self.account = PickBox()
        self.account.setFixedWidth(230)
        for account in self.s.catalog.leaf_accounts:
            self.account.addItem(account.label, account.id)
        shortage = default_account(self.s.ledger, self.s.company_id, COST_OF_GOODS)
        self.account.setCurrentIndex(max(self.account.findData(shortage), 0))
        self.add_item = PickBox(tr("Добавить товар…"))
        self.add_item.setFixedWidth(220)
        self.add_item.setToolTip(tr("Товар, которого по учёту на складе нет, а нашёлся"))
        for item in item_choices(self.s.conn, self.s.company_id):
            self.add_item.addItem(item.label, item.id)
        account_caption = self._caption(tr("Недостача — на счёт"))
        for widget in (
            self._caption(tr("Склад")),
            self.warehouse,
            self._caption(tr("Дата")),
            self.date,
            account_caption,
            self.account,
        ):
            bar.addWidget(widget)
        bar.addStretch(1)
        root.addLayout(bar)
        # a warehouse-only company does not see its books (D90): the account goes by itself
        account_caption.setVisible(not self.s.stock_only)
        self.account.setVisible(not self.s.stock_only)
        self.warehouse.activated.connect(lambda _i: self._warehouse_chosen())
        self.date.dateChanged.connect(lambda _d: self.refresh())
        self.add_item.activated.connect(lambda _i: self._add_item())

    @staticmethod
    def _caption(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("secondary")
        return label

    def _build_footer(self, root: QVBoxLayout) -> None:
        footer = QHBoxLayout()
        footer.addWidget(self.add_item)  # under the lines: one more line
        footer.addSpacing(16)
        self.totals = QLabel()
        self.totals.setObjectName("secondary")
        footer.addWidget(self.totals, 1)
        # the documents the last count made: quiet links to them
        self.made: dict[str, int | None] = {"surplus": None, "shortage": None}
        self.open_surplus = button("", "flat")
        self.open_shortage = button("", "flat")
        for which, made in (("surplus", self.open_surplus), ("shortage", self.open_shortage)):
            made.hide()
            made.clicked.connect(lambda _=False, w=which: self._open_made(w))
            footer.addWidget(made)
        root.addLayout(footer)

    def keyPressEvent(self, event) -> None:
        """Enter in the bar goes on as Tab does (D55)."""
        if not enter_goes_on(self, event):
            super().keyPressEvent(event)

    # ---- the page's frame (open pages) ----------------------------------------------

    def title(self) -> str:
        return tr("Инвентаризация")

    def is_dirty(self) -> bool:
        """A count is not kept as a draft: there is nothing to save on closing."""
        return False

    def focus_table(self) -> None:
        self.table.setFocus()

    # ---- the count ---------------------------------------------------------------------

    def _warehouse_chosen(self) -> None:
        QSettings().setValue(WAREHOUSE_SETTING, self.warehouse.currentData())
        self.refresh()

    def refresh(self) -> None:
        """The books on the chosen day, each item as counted at first."""
        warehouse_id = self.warehouse.currentData()
        rows = []
        if warehouse_id is not None:
            rows = [
                CountRow(
                    b.item_id,
                    f"{b.item_code}  {b.item_name}" if b.item_code else b.item_name,
                    b.unit_code,
                    b.precision,
                    b.quantity,
                    b.amount,
                    max(b.quantity, 0),
                )
                for b in stock_balances(
                    self.s.conn,
                    self.s.company_id,
                    edited_date(self.date),
                    warehouse_id=warehouse_id,
                )
            ]
        self.model.set_rows(rows)
        self.error.hide()

    def _add_item(self) -> None:
        item_id = self.add_item.currentData()
        chosen = next(
            (i for i in item_choices(self.s.conn, self.s.company_id) if i.id == item_id), None
        )
        if chosen is None:
            return
        at = self.model.add_row(
            CountRow(chosen.id, chosen.label, chosen.unit, chosen.precision, 0, 0, 0)
        )
        self.add_item.setCurrentIndex(-1)  # the field is empty again for the next one
        self.table.setCurrentIndex(self.model.index(at, self.model.columns.index(QUANTITY)))
        self.table.setFocus()

    def _show_totals(self) -> None:
        surplus, surplus_value, short, short_value = self.model.totals()
        parts = []
        if surplus:
            parts.append(tr("Излишки: {n} на {sum}", n=surplus, sum=money(surplus_value)))
        if short:
            parts.append(tr("Недостача: {n} на {sum}", n=short, sum=money(short_value)))
        self.totals.setText("   ·   ".join(parts) or tr("Факт совпадает с учётом"))
        self.post_button.setEnabled(bool(surplus or short) and not self.s.read_only)

    def _show_error(self, text: str) -> None:
        self.error.setText(text)
        self.error.show()

    def post(self) -> None:
        if self.s.read_only or self.warehouse.currentData() is None:
            return
        self.error.hide()
        try:
            result = self.inventory.post_stock_count(
                self.s.company_id,
                edited_date(self.date),
                self.warehouse.currentData(),
                self.model.counted(),
                self.account.currentData(),
            )
        except (LedgerError, ValueError) as exc:
            self._show_error(str(exc))
            return
        self._show_made(result)
        self.s.notify(tr("Разница инвентаризации проведена"))
        self.refresh()
        self.posted.emit()

    def _show_made(self, result: StockCountResult) -> None:
        self.made = {
            "surplus": result.surplus_document_id,
            "shortage": result.shortage_document_id,
        }
        for which, widget, text in (
            ("surplus", self.open_surplus, "Оприходование излишков №{n}"),
            ("shortage", self.open_shortage, "Списание недостачи №{n}"),
        ):
            document_id = self.made[which]
            widget.setVisible(document_id is not None)
            if document_id is not None:
                number = self.inventory.load_document(self.s.company_id, document_id).number
                widget.setText(tr(text, n=number))

    def _open_made(self, which: str) -> None:
        document_id = self.made[which]
        if document_id is not None:
            self.open_inventory_document.emit(document_id)
