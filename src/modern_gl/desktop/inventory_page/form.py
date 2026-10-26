"""The stock page's frame: the header, the operations and the layout; its parts fill it.

Everything the warehouse does starts here (D88): a client may keep only the warehouse,
so purchases and sales are typed from this page too, and the postings make themselves."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QHBoxLayout,
    QLabel,
    QStackedLayout,
    QVBoxLayout,
    QWidget,
)

from modern_gl.application.inventory import Inventory
from modern_gl.desktop.session import Session
from modern_gl.desktop.theme import fonts
from modern_gl.desktop.widgets import (
    PageHeader,
    button,
    hide_when_viewing,
    menu_button,
    trailing_icon,
)
from modern_gl.i18n import tr
from modern_gl.reporting.inventory import StockBalance

# what each operation does, in one phrase for a beginner
OPERATIONS = (
    (
        "+ Покупка",
        "receipt",
        "Товар пришёл от поставщика — по e-qaimə или таможенной декларации; "
        "проводки создаются сами",
    ),
    (
        "+ Продажа",
        "sale",
        "Товар продан покупателю: выручка, ƏDV и себестоимость проводятся сами",
    ),
    (
        "Оприходование",
        "incoming",
        "Товар пришёл не от поставщика: излишки, вклад учредителя, своё производство, подарок",
    ),
    ("Списание", "issue", "Товар израсходован или испорчен: его стоимость уходит в расходы"),
    ("Перемещение", "transfer", "Товар переехал на другой склад; стоимость не меняется"),
    (
        "Инвентаризация",
        "count",
        "Пересчитали склад: учёт подставлен, впишите факт — излишки и недостача проведутся сами",
    ),
    (
        "Дополнительные расходы",
        "landed_cost",
        "Доставка, таможня, сертификация — увеличивают стоимость полученного товара",
    ),
    ("Начальные остатки", "opening", "Что было на складе в день начала учёта в программе"),
)


class InventoryForm(QWidget):
    key = ("inventory",)
    open_inventory_document = Signal(int)
    new_inventory_document = Signal(str)
    open_landed_report = Signal()
    open_report = Signal(str)  # a warehouse report of «Все отчёты»

    def __init__(self, session: Session) -> None:
        super().__init__()
        self.setObjectName("page")
        self.s = session
        self.inventory = Inventory(session.conn, actor=session.ledger.actor)
        root = QVBoxLayout(self)
        root.setContentsMargins(40, 30, 40, 24)
        root.setSpacing(14)
        self.header = PageHeader(tr("Склад"), "")
        reports = menu_button(  # the warehouse's own reports, not the sidebar's
            trailing_icon(button(tr("Отчёты"), "flatMenu")),
            lambda: [
                (tr("Ведомость по складу"), lambda: self.open_report.emit("stock_statement")),
                (tr("Валовая прибыль по товарам"), lambda: self.open_report.emit("gross_profit")),
                (tr("Дополнительные расходы по декларациям"), self.open_landed_report.emit),
            ],
        )
        self.header.add_action(reports)
        add_item = self.header.primary(tr("+ Товар"), self.add_item)
        more = self.header.more(  # what is set up once, rarely
            lambda: [
                (tr("+ Единица"), self.add_unit),
                (tr("+ Склад"), self.add_warehouse),
                (tr("+ Вид расходов"), self.add_landed_cost_type),
                (tr("Настройки склада…"), self.settings),
            ]
        )
        hide_when_viewing(session.read_only, add_item, more)
        root.addWidget(self.header)

        self._build_operations(root)
        self._build_stock(root)
        self._build_below(root)
        hint = QLabel(
            tr("Остатки считаются по проведённым документам.")
            if session.stock_only  # the books are not shown (D90)
            else tr(
                "Остатки считаются по проведённым документам; "
                "проводки в бухгалтерии создаются сами."
            )
        )
        hint.setObjectName("tertiary")
        hint.setFont(fonts().small)
        hint.setWordWrap(True)
        root.addWidget(hint)
        self.refresh()

    def _build_operations(self, root: QVBoxLayout) -> None:
        operations = QHBoxLayout()
        operations.setSpacing(6)
        self.operation_buttons: dict[str, QWidget] = {}
        for title, operation, tip in OPERATIONS:
            control = button(tr(title), "flat", tr(tip))
            control.clicked.connect(lambda _=False, op=operation: self.operation(op))
            operations.addWidget(control)
            hide_when_viewing(self.s.read_only, control)
            self.operation_buttons[operation] = control
        operations.addStretch(1)
        root.addLayout(operations)

    def _build_below(self, root: QVBoxLayout) -> None:
        """Under the stock: the chosen item's movements, or all the warehouse documents."""
        bar = QHBoxLayout()
        bar.setSpacing(6)
        self.views = QButtonGroup(self)
        self.movements_button = button(tr("Движения"), "segment")
        self.documents_button = button(tr("Документы"), "segment")
        for view in (self.movements_button, self.documents_button):
            view.setCheckable(True)
            view.clicked.connect(self._show_view)
            self.views.addButton(view)
            bar.addWidget(view)
        self.movements_button.setChecked(True)
        bar.addSpacing(12)
        self.below_title = QLabel()  # «Printer kartrici 85A · Mərkəzi anbar»
        self.below_title.setFont(fonts().heading)
        keep_room = self.below_title.sizePolicy()
        keep_room.setRetainSizeWhenHidden(True)  # hidden, it still holds the switch left
        self.below_title.setSizePolicy(keep_room)
        bar.addWidget(self.below_title, 1)
        self.remove = button(tr("Удалить документ"), "danger")
        self.remove.clicked.connect(self.delete_document)
        bar.addWidget(self.remove)
        root.addLayout(bar)
        self.below = QStackedLayout()
        self.movements_page = self._build_movements()
        self.documents_page = self._build_documents()
        self.below.addWidget(self.movements_page)
        self.below.addWidget(self.documents_page)
        root.addLayout(self.below, 1)
        self._show_view()

    def _show_view(self) -> None:
        documents = self.documents_button.isChecked()
        self.below.setCurrentWidget(self.documents_page if documents else self.movements_page)
        self.remove.setVisible(documents and not self.s.read_only)
        self.below_title.setVisible(not documents)

    def title(self) -> str:
        return tr("Склад")

    def is_dirty(self) -> bool:
        return False

    def operation(self, operation: str) -> None:
        self.new_inventory_document.emit(operation)

    # ---- made by the groups of the page; each group may call the others --------------

    def _build_stock(self, root: QVBoxLayout) -> None:
        raise NotImplementedError

    def _build_movements(self) -> QWidget:
        raise NotImplementedError

    def _build_documents(self) -> QWidget:
        raise NotImplementedError

    def refresh(self) -> None:
        raise NotImplementedError

    def chosen_balance(self) -> StockBalance | None:
        raise NotImplementedError

    def has_stock(self) -> bool:
        raise NotImplementedError

    def _show_movements(self) -> None:
        raise NotImplementedError

    def _show_documents(self) -> None:
        raise NotImplementedError

    def delete_document(self) -> None:
        raise NotImplementedError

    def add_item(self) -> None:
        raise NotImplementedError

    def add_unit(self) -> None:
        raise NotImplementedError

    def add_warehouse(self) -> None:
        raise NotImplementedError

    def add_landed_cost_type(self) -> None:
        raise NotImplementedError

    def settings(self) -> None:
        raise NotImplementedError
