"""Directories (subconto): banks, counterparties, contracts, cost items…

Left: the directories with how many elements they have. Right: the elements.
Ins adds, F2 renames, the context menu hides / shows. Hidden elements stay in
history and reports but are no longer offered when entering postings.
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QAction, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QStackedLayout,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from modern_gl.application.catalog import SubcontoInfo
from modern_gl.desktop.reports_page import Column, ReportModel
from modern_gl.desktop.session import Session
from modern_gl.desktop.theme import fonts
from modern_gl.desktop.widgets import EmptyState, PageHeader, button
from modern_gl.domain.errors import LedgerError
from modern_gl.i18n import sort_key, tr

KIND_ROLE = Qt.ItemDataRole.UserRole


class DirectoriesPage(QWidget):
    key = ("directories",)

    def __init__(self, session: Session) -> None:
        super().__init__()
        self.setObjectName("page")
        self.s = session
        root = QVBoxLayout(self)
        root.setContentsMargins(40, 30, 40, 24)
        root.setSpacing(18)

        self.header = PageHeader(tr("Справочники"), "")
        add_kind = button(tr("+ Новый справочник"), "flat")
        add_kind.clicked.connect(self.add_kind)
        self.header.add_action(add_kind)
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
        add = button(tr("+ Новый элемент"), "primary", "Ins")
        add.clicked.connect(self.add_value)
        top.addWidget(add)
        right.addLayout(top)
        self.used_in = QLabel()
        self.used_in.setObjectName("secondary")
        self.used_in.setWordWrap(True)
        right.addWidget(self.used_in)

        self.model = ReportModel()
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setShowGrid(False)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(34)
        self.table.horizontalHeader().setHighlightSections(False)
        self.table.doubleClicked.connect(lambda idx: self.rename_value(self._value_at(idx)))
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._context_menu)
        self.empty = EmptyState(
            "○", tr("Справочник пуст"), tr("Нажмите «+ Новый элемент» или Ins.")
        )
        self.stack = QStackedLayout()
        self.stack.addWidget(self.table)
        self.stack.addWidget(self.empty)
        right.addLayout(self.stack, 1)
        hint = QLabel(tr("Ins — новый элемент   ·   F2 или двойной щелчок — переименовать"))
        hint.setObjectName("tertiary")
        hint.setFont(fonts().small)
        right.addWidget(hint)
        body.addLayout(right, 1)
        root.addLayout(body, 1)

        for keys, fn in (
            ("Ins", self.add_value),
            ("F2", lambda: self.rename_value(self._current_value())),
        ):
            sc = QShortcut(QKeySequence(keys), self)
            sc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            sc.activated.connect(fn)
        self.refresh()

    def title(self) -> str:
        return tr("Справочники")

    def is_dirty(self) -> bool:
        return False

    def focus_table(self) -> None:
        self.table.setFocus()

    # ---- data ------------------------------------------------------------------------

    def kind_id(self) -> int | None:
        item = self.kinds.currentItem()
        return item.data(KIND_ROLE) if item else None

    def refresh(self, select_kind: int | None = None) -> None:
        cat = self.s.catalog
        current = select_kind or self.kind_id()
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
        self.refresh_values()

    def refresh_values(self, select_value: int | None = None) -> None:
        cat, kind_id = self.s.catalog, self.kind_id()
        if kind_id is None:
            return
        self.kind_title.setText(cat.kinds[kind_id])
        accounts = cat.accounts_using(kind_id)
        self.used_in.setText(
            tr("Используется на счетах: {codes}", codes=", ".join(a.code for a in accounts))
            if accounts
            else tr("Пока не используется ни на одном счёте")
        )
        values = cat.all_values(kind_id)
        columns = [
            Column(
                tr("Наименование"), lambda v: v.name if v.active else f"{v.name}  ·  {tr('скрыт')}"
            ),
        ]
        self.model.set(columns, values, muted=lambda v: not v.active)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.stack.setCurrentWidget(self.table if values else self.empty)
        if select_value is not None:
            row = next((i for i, v in enumerate(values) if v.id == select_value), None)
            if row is not None:
                self.table.setCurrentIndex(self.model.index(row, 0))

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

    def add_value(self) -> None:
        kind_id = self.kind_id()
        if kind_id is None:
            return
        kind = self.s.catalog.kinds[kind_id]
        name = self._ask(tr("Новый элемент"), tr("Название (справочник «{kind}»):", kind=kind))
        if name:
            self._apply(
                lambda: self.s.ledger.add_subconto_value(self.s.company_id, kind_id, name),
                tr("Добавлено в «{kind}»: {text}", kind=kind, text=name),
            )

    def rename_value(self, value: SubcontoInfo | None) -> None:
        if value is None:
            return
        name = self._ask(tr("Переименовать"), tr("Новое название:"), value.name)
        if name and name != value.name:
            self._apply(
                lambda: self.s.ledger.update_subconto_value(
                    self.s.company_id, value.id, name, value.code
                ),
                tr("Переименовано: {old} → {new}", old=value.name, new=name),
                value.id,
            )

    def toggle_value(self, value: SubcontoInfo) -> None:
        self._apply(
            lambda: self.s.ledger.set_subconto_value_active(
                self.s.company_id, value.id, not value.active
            ),
            tr("«{text}» снова в списках", text=value.name)
            if not value.active
            else tr("«{text}» скрыт из списков ввода", text=value.name),
            value.id,
        )

    def add_kind(self) -> None:
        name = self._ask(tr("Новый справочник"), tr("Название справочника (например, «Проекты»):"))
        if not name:
            return
        try:
            kind_id = self.s.ledger.add_subconto_kind(self.s.company_id, None, name)
        except LedgerError as e:
            self.s.notify(str(e))
            return
        self.s.catalog.reload()
        self.refresh(select_kind=kind_id)
        self.s.notify(
            tr("Справочник «{name}» создан. Подключите его к счёту в плане счетов.", name=name)
        )

    def _context_menu(self, pos) -> None:
        value = self._value_at(self.table.indexAt(pos))
        if value is None:
            return
        menu = QMenu(self)
        for text, fn in (
            (tr("Переименовать…"), lambda: self.rename_value(value)),
            (
                tr("Показать") if not value.active else tr("Скрыть"),
                lambda: self.toggle_value(value),
            ),
        ):
            act = QAction(text, menu)
            act.triggered.connect(fn)
            menu.addAction(act)
        menu.exec(self.table.viewport().mapToGlobal(pos))
