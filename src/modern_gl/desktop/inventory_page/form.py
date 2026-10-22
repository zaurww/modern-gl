"""The stock page's frame: the header, the operations and the layout; its parts fill it."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget

from modern_gl.application.inventory import Inventory
from modern_gl.desktop.session import Session
from modern_gl.desktop.widgets import (
    PageHeader,
    button,
    hide_when_viewing,
    menu_button,
    more_button,
)
from modern_gl.i18n import tr


class InventoryForm(QWidget):
    key = ("inventory",)
    open_inventory_document = Signal(int)
    new_inventory_document = Signal(str)
    open_landed_report = Signal()

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
            button(tr("Отчёты") + "  ▾", "flat"),
            lambda: [(tr("Дополнительные расходы по декларациям"), self.open_landed_report.emit)],
        )
        self.header.add_action(reports)
        add_item = button(tr("+ Товар"), "flat")
        add_item.clicked.connect(self.add_item)
        self.header.add_action(add_item)
        more = more_button(  # what is set up once, rarely
            lambda: [
                (tr("+ Единица"), self.add_unit),
                (tr("+ Склад"), self.add_warehouse),
                (tr("+ Вид расходов"), self.add_landed_cost_type),
                (tr("Настройки склада…"), self.settings),
            ]
        )
        self.header.add_action(more)
        hide_when_viewing(session.read_only, add_item, more)
        root.addWidget(self.header)

        self._build_operations(root)
        self._build_stock(root)
        self._build_documents(root)
        self.refresh()

    def _build_operations(self, root: QVBoxLayout) -> None:
        operations = QHBoxLayout()
        operations.setSpacing(6)
        for title, operation, kind in (
            ("Начальные остатки", "opening", "flat"),
            ("Списание", "issue", "primary"),
            ("Перемещение", "transfer", "flat"),
            ("Дополнительные расходы", "landed_cost", "flat"),
        ):
            control = button(tr(title), kind)
            control.clicked.connect(lambda _=False, op=operation: self.operation(op))
            operations.addWidget(control)
            hide_when_viewing(self.s.read_only, control)
        operations.addStretch(1)
        root.addLayout(operations)

    def title(self) -> str:
        return tr("Склад")

    def is_dirty(self) -> bool:
        return False

    def operation(self, operation: str) -> None:
        self.new_inventory_document.emit(operation)

    # ---- made by the groups of the page; each group may call the others --------------

    def _build_stock(self, root: QVBoxLayout) -> None:
        raise NotImplementedError

    def _build_documents(self, root: QVBoxLayout) -> None:
        raise NotImplementedError

    def refresh(self) -> None:
        raise NotImplementedError

    def _show_documents(self) -> None:
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
