"""Dialogs that pick receipt lines, GL postings to take as expenses, and show a
batch's cost."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from PySide6.QtCore import (
    Qt,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QTableView,
    QVBoxLayout,
)

from modern_gl.application.inventory import (
    format_quantity,
    unit_price,
)
from modern_gl.desktop.reports_page import Column, ReportModel
from modern_gl.desktop.session import Session
from modern_gl.desktop.theme import fonts
from modern_gl.desktop.widgets import (
    button,
    list_table,
    money,
)
from modern_gl.domain.currency import format_unit_rate, unit_rate
from modern_gl.domain.dates import ru_date
from modern_gl.domain.money import format_minor
from modern_gl.i18n import fold, tr
from modern_gl.reporting.inventory import (
    BatchCostLine,
    CostSource,
    batch_cost,
    cost_sources,
    receipt_line_choices,
)
from modern_gl.reporting.inventory.costs import BatchCharge


def _list(selection: QAbstractItemView.SelectionMode) -> QTableView:
    return list_table(None, 32, selection=selection)


class PickerDialog(QDialog):
    """A searchable list to pick several rows from. With `usual`, only the usual rows are
    shown until «Все» is ticked."""

    def __init__(
        self,
        title: str,
        hint: str,
        columns: list[Column],
        rows: list,
        parent=None,
        usual: Callable[[Any], bool] | None = None,
        all_title: str = "",
    ):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(820, 480)
        self.all_rows = rows
        layout = QVBoxLayout(self)
        text = QLabel(hint)
        text.setObjectName("secondary")
        text.setWordWrap(True)
        layout.addWidget(text)
        self.search = QLineEdit()
        self.search.setPlaceholderText(tr("Поиск"))
        self.usual = usual
        self.show_all = QCheckBox(all_title)
        search_bar = QHBoxLayout()
        search_bar.addWidget(self.search, 1)
        search_bar.addWidget(self.show_all)
        self.show_all.setVisible(usual is not None)
        layout.addLayout(search_bar)
        self.model = ReportModel()
        self.columns = columns
        self.table = _list(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setModel(self.model)
        layout.addWidget(self.table, 1)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.search.textChanged.connect(self._filter)
        self.show_all.toggled.connect(lambda _on: self._filter(self.search.text()))
        self.table.doubleClicked.connect(lambda _index: self.accept())
        self._filter("")

    def _filter(self, text: str) -> None:
        needle = fold(text.strip())
        usual = self.usual if self.usual and not self.show_all.isChecked() else None
        rows = [row for row in self.all_rows if (usual is None or usual(row))]
        rows = [
            row
            for row in rows
            if not needle
            or needle in fold(" ".join(str(c.get(row)) for c in self.columns if not c.money))
            or needle in format_minor(getattr(row, "amount", 0)).replace(" ", "")
        ]
        self.model.set(self.columns, rows)
        header = self.table.horizontalHeader()
        for n, column in enumerate(self.columns):
            if column.width:
                header.setSectionResizeMode(n, QHeaderView.ResizeMode.Interactive)
                self.table.setColumnWidth(n, column.width)
            else:
                header.setSectionResizeMode(n, QHeaderView.ResizeMode.Stretch)
        if rows:
            self.table.selectRow(0)

    def chosen(self) -> list:
        return [self.model.rows[i.row()] for i in self.table.selectionModel().selectedRows()]


def receipt_picker(session: Session, parent=None) -> PickerDialog:
    rows = receipt_line_choices(session.conn, session.company_id)
    columns = [
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
    return PickerDialog(
        tr("Партия: поступления"),
        tr("Выберите строки поступлений (Ctrl / Shift — несколько). Поиск — по товару, номеру…"),
        columns,
        rows,
        parent,
    )


def cost_source_picker(session: Session, exclude: int | None, parent=None) -> PickerDialog:
    rows = cost_sources(session.conn, session.company_id, exclude)
    columns = [
        Column(tr("Дата"), lambda r: ru_date(r.doc_date), width=96),
        Column("№", lambda r: r.number, width=56),
        Column(tr("Дт"), lambda r: r.debit, width=70),
        Column(tr("Кт"), lambda r: r.credit, width=70),
        Column(tr("Субконто"), lambda r: r.subconto, width=150),
        Column(tr("Содержание"), lambda r: r.memo),
        Column(tr("Сумма"), lambda r: r.amount, money=True, width=100),
        Column(tr("Остаток"), lambda r: r.left, money=True, width=100),
    ]
    return PickerDialog(
        tr("Расход из проводки"),
        tr(
            "Уже введённая проводка (фактура брокера, таможни…): её дебет перейдёт в стоимость "
            "товаров. Показан нераспределённый остаток."
        ),
        columns,
        rows,
        parent,
        usual=lambda r: r.debit_class == "expense",
        all_title=tr("Все проводки"),
    )


def source_label(source: CostSource) -> str:
    return f"№{source.number} · {ru_date(source.doc_date)} · {source.debit}/{source.credit}" + (
        f" · {source.memo}" if source.memo else ""
    )


@dataclass
class _CostRow:
    """A line of the batch cost report, or its total."""

    document: str = ""
    item: str = ""
    quantity: str = ""
    price: str = ""
    rate: str = ""
    cost: int = 0
    shares: dict[int, int] = field(default_factory=dict)
    expenses: int = 0
    total: int = 0
    unit_cost: int | None = None
    is_total: bool = False


def _cost_row(line: BatchCostLine) -> _CostRow:
    price = ""
    if line.currency and line.currency_amount is not None and line.quantity:
        price = f"{money(unit_price(line.currency_amount, line.quantity) or 0)} {line.currency}"
    return _CostRow(
        f"№{line.number}  ·  {ru_date(line.doc_date)}",
        line.item_name,
        f"{format_quantity(line.quantity, line.precision)} {line.unit}",
        price,
        "" if line.rate is None else format_unit_rate(unit_rate(line.rate)),
        line.cost,
        line.shares,
        line.expenses,
        line.total,
        unit_price(line.total, line.quantity),
    )


def _rate_notes(charges: list[BatchCharge]) -> list[str]:
    """«Доставка: 100.00 USD по курсу 1.7000» for each expense in a currency."""
    return [
        tr(
            "{title}: {amount} {code} по курсу {rate}",
            title=c.title,
            amount=money(c.currency_amount or 0),
            code=c.currency,
            rate=format_unit_rate(unit_rate(c.rate or 0)),
        )
        for c in charges
        if c.currency
    ]


def _cost_columns(charges: list[BatchCharge], in_currency: bool) -> list[Column]:
    """The receipt line, the supplier's price (in a currency: and the rate), each expense,
    the total and a unit's cost. Width 1: as wide as the contents; the item takes the rest."""
    return [
        Column(tr("Поступление"), lambda r: r.document, width=1),
        Column(tr("Товар"), lambda r: r.item),
        Column(tr("Количество"), lambda r: r.quantity, width=1, right=True),
        *(
            [
                Column(tr("Цена поставщика"), lambda r: r.price, width=1, right=True),
                Column(tr("Курс"), lambda r: r.rate, width=1, right=True),
            ]
            if in_currency
            else []
        ),
        Column(tr("Стоимость"), lambda r: r.cost, money=True, width=1),
        *[
            Column(c.title, lambda r, cid=c.id: r.shares.get(cid, 0), money=True, width=1)
            for c in charges
        ],
        Column(tr("Итого"), lambda r: r.total, money=True, width=1),
        Column(tr("Цена за единицу"), lambda r: r.unit_cost, money=True, width=1),
    ]


class BatchCostDialog(QDialog):
    """«Себестоимость партии»: what each receipt line cost — the supplier's price (in a
    currency and at what rate), every expense separately, the total and a unit's cost."""

    def __init__(self, session: Session, document_id: int, title: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("Себестоимость партии"))
        charges, lines = batch_cost(session.conn, session.company_id, document_id)
        layout = QVBoxLayout(self)
        heading = QLabel(title)
        heading.setFont(fonts().heading)
        layout.addWidget(heading)
        notes = _rate_notes(charges)
        if notes:
            note = QLabel("   ·   ".join(notes))
            note.setObjectName("secondary")
            layout.addWidget(note)
        self.columns = _cost_columns(charges, any(line.currency for line in lines))
        rows = [_cost_row(line) for line in lines]
        total = _CostRow(
            tr("Итого"),
            cost=sum(r.cost for r in rows),
            shares={c.id: sum(r.shares.get(c.id, 0) for r in rows) for c in charges},
            expenses=sum(r.expenses for r in rows),
            total=sum(r.total for r in rows),
            is_total=True,
        )
        self.model = ReportModel()
        self.model.set(
            self.columns,
            [*rows, total],
            emphasis=lambda r: r.is_total,
            total=lambda r: r.is_total,
        )
        table = _list(QAbstractItemView.SelectionMode.SingleSelection)
        table.setModel(self.model)
        header = table.horizontalHeader()
        header.setMinimumSectionSize(70)
        for n, column in enumerate(self.columns):
            mode = QHeaderView.ResizeMode.ResizeToContents
            header.setSectionResizeMode(n, mode if column.width else QHeaderView.ResizeMode.Stretch)
        table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        layout.addWidget(table, 1)
        fixed = sum(header.sectionSizeHint(n) for n, c in enumerate(self.columns) if c.width)
        self.resize(min(max(fixed + 320, 900), 1500), 460)
        buttons = QHBoxLayout()
        copy = button(tr("Копировать для Excel"), "flat")
        copy.clicked.connect(self.copy)
        buttons.addWidget(copy)
        buttons.addStretch(1)
        close = button(tr("Закрыть"))
        close.clicked.connect(self.accept)
        buttons.addWidget(close)
        layout.addLayout(buttons)

    def text(self) -> str:
        """The table as tab-separated lines with a header."""
        model = self.model
        lines = ["\t".join(c.title for c in self.columns)]
        for row in range(model.rowCount()):
            cells = [
                str(model.index(row, column).data() or "").replace("\u00a0", "").replace(" ", "")
                if self.columns[column].money
                else str(model.index(row, column).data() or "")
                for column in range(model.columnCount())
            ]
            lines.append("\t".join(cells))
        return "\n".join(lines) + "\n"

    def copy(self) -> None:
        QApplication.clipboard().setText(self.text())
