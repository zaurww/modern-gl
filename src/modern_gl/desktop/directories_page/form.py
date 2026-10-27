"""Directories: the lists — directories on the left, their elements on the right — and
what the commands ask of them (page.py has the commands)."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QStackedLayout,
    QVBoxLayout,
)

from modern_gl.application.catalog import SubcontoInfo
from modern_gl.desktop.icons import icon
from modern_gl.desktop.list_table import ListTable
from modern_gl.desktop.page import PageWidget
from modern_gl.desktop.reports_page import Column, ReportModel
from modern_gl.desktop.session import Session
from modern_gl.desktop.shortcuts import bind
from modern_gl.desktop.theme import P, fonts
from modern_gl.desktop.widgets import EmptyState, PageHeader, button, caption, hide_when_viewing
from modern_gl.domain.errors import LedgerError
from modern_gl.i18n import sort_key, tr

KIND_ROLE = Qt.ItemDataRole.UserRole


class DirectoriesForm(PageWidget):
    def __init__(self, session: Session) -> None:
        super().__init__()
        self.setObjectName("page")
        self.s = session
        root = QVBoxLayout(self)
        root.setContentsMargins(40, 30, 40, 24)
        root.setSpacing(18)

        self.header = PageHeader(tr("Справочники"), "")
        # one blue button on the page (D86): «+ New element»; a new directory is rare
        add_kind = self.header.more(lambda: [(tr("+ Новый справочник"), self.add_kind)])
        root.addWidget(self.header)

        body = QHBoxLayout()
        body.setSpacing(28)
        self.kinds = QListWidget()
        self.kinds.setObjectName("nav")  # same calm look as the sidebar list
        self.kinds.setFixedWidth(250)
        self.kinds.currentItemChanged.connect(lambda *_: self.refresh_values())
        body.addWidget(self.kinds)

        right = QVBoxLayout()
        right.setSpacing(10)
        top = QHBoxLayout()
        self.kind_title = QLabel()
        self.kind_title.setFont(fonts().heading)
        top.addWidget(self.kind_title, 1)
        add_group = button(tr("+ Группа"), "flat")
        add_group.clicked.connect(self.add_group)
        top.addWidget(add_group)
        add = button(tr("+ Новый элемент"), "primary", "Ins")
        add.clicked.connect(lambda: self.add_value())  # noqa: PLW0108 clicked(bool) would be kind_id
        top.addWidget(add)
        hide_when_viewing(session.read_only, add_kind, add_group, add)
        right.addLayout(top)
        self.used_in = caption()
        self.used_in.setWordWrap(True)
        right.addWidget(self.used_in)

        self._build_table()
        self.empty = EmptyState(
            "○", tr("Справочник пуст"), tr("Нажмите «+ Новый элемент» или Ins.")
        )
        self.stack = QStackedLayout()
        self.stack.addWidget(self.table)
        self.stack.addWidget(self.empty)
        right.addLayout(self.stack, 1)
        hint = QLabel(
            tr("Ins — новый элемент   ·   F2 или двойной щелчок — изменить   ·   Del — удалить")
        )
        hint.setObjectName("tertiary")
        hint.setFont(fonts().small)
        right.addWidget(hint)
        body.addLayout(right, 1)
        root.addLayout(body, 1)

        bind(self, "insert", self.add_value)
        bind(self, "edit", lambda: self.rename_value(self._current_value()))
        bind(self.table, "delete", lambda: self.delete_value(self._current_value()))
        self.refresh()

    def _build_table(self) -> None:
        """The elements: rows to pick, no grid, F2 or a double click to edit."""
        self.model = ReportModel()
        self.table = ListTable(self.model, 34)
        self.table.doubleClicked.connect(lambda idx: self.rename_value(self._value_at(idx)))
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._context_menu)

    def title(self) -> str:
        return tr("Справочники")

    def activated(self) -> None:
        self.refresh(keep_value=True)  # elements added elsewhere (e-qaimə import…)
        self.focus_table()

    def focus_table(self) -> None:
        self.table.setFocus()

    # ---- data ------------------------------------------------------------------------

    def kind_id(self) -> int | None:
        item = self.kinds.currentItem()
        return item.data(KIND_ROLE) if item else None

    def refresh(self, select_kind: int | None = None, keep_value: bool = False) -> None:
        cat = self.s.catalog
        current = select_kind or self.kind_id()
        value = self._current_value() if keep_value else None
        self.kinds.blockSignals(True)
        self.kinds.clear()
        for kind_id, name in sorted(cat.kinds.items(), key=lambda kv: sort_key(kv[1])):
            count = len(cat.values(kind_id))
            item = QListWidgetItem(f"{name}   {count}" if count else name)
            item.setData(KIND_ROLE, kind_id)
            item.setSizeHint(QSize(0, 34))
            self.kinds.addItem(item)
            if kind_id == current:
                self.kinds.setCurrentItem(item)
        if self.kinds.currentItem() is None and self.kinds.count():
            self.kinds.setCurrentRow(0)
        self.kinds.blockSignals(False)
        self.header.subtitle.setText(tr("{n} справочников", n=len(cat.kinds)))
        self.refresh_values(value.id if value else None)

    def refresh_values(self, select_value: int | None = None) -> None:
        cat, kind_id = self.s.catalog, self.kind_id()
        if kind_id is None:
            return
        self.kind_title.setText(cat.kinds[kind_id])
        accounts = cat.accounts_using(kind_id)
        self.used_in.setText(
            tr("Используется на счетах: {codes}", codes=", ".join(a.short for a in accounts))
            if accounts
            else tr("Пока не используется ни на одном счёте")
        )
        values = cat.all_values(kind_id)
        tree = cat.tree(kind_id)
        grouped = any(value.is_group for value in values)
        depth = {value.id: level for level, value in tree}
        columns = [
            Column(
                tr("Наименование"),
                lambda v: self._name_text(v, depth.get(v.id, 0)),
                icon=(lambda v: icon("folder", P.tertiary) if v.is_group else None),
            ),
        ]
        owner_kind = cat.owner_kinds.get(kind_id)
        if owner_kind is not None:  # contracts: whose each one is, grouped by counterparty
            columns.append(Column(cat.owner_title(kind_id), self._owner_name, width=260))
            if not grouped:
                values.sort(key=lambda v: (v.owner_id is not None, sort_key(self._owner_name(v))))
        if cat.has_tax_id(kind_id):
            columns.append(Column(tr("VÖEN"), self._tax_text, width=260))
        if any(a.currency for a in accounts):
            columns.append(Column(tr("Валюта"), self._currency_code, width=120))
        if any(v.tags for v in values):
            columns.append(Column(tr("Теги"), cat.tag_text, width=260))
        if grouped:  # each group followed by what it holds
            values = [value for _, value in tree]
        self.model.set(columns, values, emphasis=lambda v: v.is_group, muted=lambda v: not v.active)
        self.stack.setCurrentWidget(self.table if values else self.empty)
        if select_value is not None:
            row = next((i for i, v in enumerate(values) if v.id == select_value), None)
            if row is not None:
                self.table.setCurrentIndex(self.model.index(row, 0))

    def _name_text(self, value: SubcontoInfo, depth: int) -> str:
        """Indented under its group; a group shows how many elements it holds."""
        text = value.name
        if value.is_group:
            count = sum(
                1
                for v in self.s.catalog.all_values(value.kind_id)
                if v.parent_id == value.id and not v.is_group
            )
            text = f"{text}   {count}" if count else text
        if not value.active:
            text = f"{text}  ·  {tr('скрыт')}"
        return " " * 2 * depth + text  # an element of a group stands past its icon

    def _group_here(self) -> int | None:
        """The group a new element goes into: the chosen group, or the chosen element's."""
        value = self._current_value()
        if value is None:
            return None
        return value.id if value.is_group else value.parent_id

    def _owner_name(self, value: SubcontoInfo) -> str:
        return self.s.catalog.value(value.owner_id).name if value.owner_id else ""

    @staticmethod
    def _tax_text(value: SubcontoInfo) -> str:
        """A resident's VÖEN; for a non-resident, its country and own tax number."""
        if not value.nonresident:
            return value.tax_id or ""
        parts = [value.country or tr("нерезидент"), value.tax_id or ""]
        return "  ·  ".join(p for p in parts if p)

    def _currency_code(self, value: SubcontoInfo) -> str:
        currency = self.s.catalog.currencies.get(value.currency_id or 0)
        return currency.code if currency else ""

    def _value_at(self, index) -> SubcontoInfo | None:
        return index.data(Qt.ItemDataRole.UserRole) if index.isValid() else None

    def _current_value(self) -> SubcontoInfo | None:
        return self._value_at(self.table.currentIndex())

    # ---- actions ---------------------------------------------------------------------

    def _ask(self, title: str, label: str, text: str = "") -> str | None:
        value, ok = QInputDialog.getText(self, title, label, text=text)
        return value.strip() if ok and value.strip() else None

    def _apply(self, action, message: str, select_value: int | None = None) -> None:
        try:
            result = action()
        except LedgerError as e:
            self.s.notify(str(e))
            return
        self.s.catalog.reload()
        self.refresh()
        self.refresh_values(select_value if select_value is not None else result)
        self.s.notify(message)

    # ---- hooks: the page's commands (page.py) --------------------------------------
    def add_kind(self) -> None:
        raise NotImplementedError

    def add_group(self) -> None:
        raise NotImplementedError

    def add_value(self, kind_id: int | None = None, owner_id: int | None = None) -> None:
        raise NotImplementedError

    def rename_value(self, value: SubcontoInfo | None) -> None:
        raise NotImplementedError

    def delete_value(self, value: SubcontoInfo | None) -> None:
        raise NotImplementedError

    def _context_menu(self, pos) -> None:
        raise NotImplementedError
