"""Directories (subconto): banks, counterparties, contracts, cost items…

Left: the directories with how many elements they have. Right: the elements.
Ins adds, F2 renames, the context menu hides / shows. Hidden elements stay in
history and reports but are no longer offered when entering postings.

Groups (folders, as in 1C) hold elements: «Kabellər», «Xarici təchizatçılar». A new
element goes into the group chosen in the list; «В группу…» moves one. Groups are only
for finding and reports: a posting has an element, never a group (D60).

Contracts belong to counterparties: their list shows whose each one is, the dialog of a
contract asks for its counterparty, and a counterparty's menu adds a contract to it.
A counterparty has a VÖEN; a non-resident has none, but a country and a tax number of
its own country instead.

Tags («Связанная сторона», «Арендодатель») are of the company: an element has any number
of them, and ОСВ по субконто shows only the elements with a tag (D64).
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QAction, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QStackedLayout,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from modern_gl.application.catalog import SubcontoInfo
from modern_gl.application.inventory import Inventory
from modern_gl.desktop.directories_page.tags import TagsDialog
from modern_gl.desktop.directories_page.values import (
    ValueDialog,
    has_currency,
    new_value,
    tax_id_taken,
)
from modern_gl.desktop.icons import icon
from modern_gl.desktop.inventory_page import open_item
from modern_gl.desktop.reports_page import Column, ReportModel
from modern_gl.desktop.session import Session
from modern_gl.desktop.theme import P, fonts
from modern_gl.desktop.widgets import EmptyState, PageHeader, button, hide_when_viewing
from modern_gl.domain.errors import LedgerError
from modern_gl.i18n import sort_key, tr
from modern_gl.infrastructure.db import transaction
from modern_gl.reporting.inventory import item_details

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
        add_kind = self.header.primary(tr("+ Новый справочник"), self.add_kind)
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
        add_group.clicked.connect(lambda: self.add_group())
        top.addWidget(add_group)
        add = button(tr("+ Новый элемент"), "primary", "Ins")
        add.clicked.connect(lambda: self.add_value())
        top.addWidget(add)
        hide_when_viewing(session.read_only, add_kind, add_group, add)
        right.addLayout(top)
        self.used_in = QLabel()
        self.used_in.setObjectName("secondary")
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

        for keys, fn in (
            ("Ins", lambda: self.add_value()),
            ("F2", lambda: self.rename_value(self._current_value())),
        ):
            sc = QShortcut(QKeySequence(keys), self)
            sc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            sc.activated.connect(fn)
        delete = QShortcut(QKeySequence("Del"), self.table)  # not while typing a search
        delete.setContext(Qt.ShortcutContext.WidgetShortcut)
        delete.activated.connect(lambda: self.delete_value(self._current_value()))
        self.refresh()

    def _build_table(self) -> None:
        """The elements: rows to pick, no grid, F2 or a double click to edit."""
        self.model = ReportModel()
        self.table = QTableView()
        self.table.setObjectName("list")
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
        widths = []
        owner_kind = cat.owner_kinds.get(kind_id)
        if owner_kind is not None:  # contracts: whose each one is, grouped by counterparty
            columns.append(Column(cat.owner_title(kind_id), self._owner_name, width=260))
            widths.append(260)
            if not grouped:
                values.sort(key=lambda v: (v.owner_id is not None, sort_key(self._owner_name(v))))
        if cat.has_tax_id(kind_id):
            columns.append(Column(tr("VÖEN"), self._tax_text, width=260))
            widths.append(260)
        if any(a.currency for a in accounts):
            columns.append(Column(tr("Валюта"), self._currency_code, width=120))
            widths.append(120)
        if any(v.tags for v in values):
            columns.append(Column(tr("Метки"), cat.tag_text, width=260))
            widths.append(260)
        if grouped:  # each group followed by what it holds
            values = [value for _, value in tree]
        self.model.set(columns, values, emphasis=lambda v: v.is_group, muted=lambda v: not v.active)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for col, width in enumerate(widths, start=1):
            self.table.setColumnWidth(col, width)
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

    def add_value(self, kind_id: int | None = None, owner_id: int | None = None) -> None:
        kind_id = kind_id if kind_id is not None else self.kind_id()
        if kind_id is None:
            return
        kind = self.s.catalog.kinds[kind_id]
        if self._detailed(kind_id):
            self._add_detailed(kind_id, owner_id)
            return
        group = self._group_here() if kind_id == self.kind_id() else None
        name = self._ask(tr("Новый элемент"), tr("Название (справочник «{kind}»):", kind=kind))
        if name:
            self._apply(
                lambda: self.s.ledger.add_subconto_value(
                    self.s.company_id, kind_id, name, parent_id=group
                ),
                tr("Добавлено в «{kind}»: {text}", kind=kind, text=name),
            )

    def add_group(self) -> None:
        """A folder of the directory, at the top; «В группу…» nests it if needed."""
        kind_id = self.kind_id()
        if kind_id is None:
            return
        name = self._ask(
            tr("Новая группа"),
            tr("Название группы (например, «Кабели», «Иностранные поставщики»):"),
        )
        if name:
            self._apply(
                lambda: self.s.ledger.add_subconto_group(self.s.company_id, kind_id, name),
                tr("Группа «{name}» создана", name=name),
            )

    def move_value(self, value: SubcontoInfo | None) -> None:
        """Into a group, or out of any; a group moves with all it holds."""
        if value is None:
            return
        groups = [
            (depth, group)
            for depth, group in self.s.catalog.groups(value.kind_id)
            if group.id != value.id
        ]
        none = tr("— без группы")
        items = [none] + [" " * 2 * depth + group.name for depth, group in groups]
        current = next(
            (i + 1 for i, (_, group) in enumerate(groups) if group.id == value.parent_id), 0
        )
        choice, ok = QInputDialog.getItem(
            self,
            tr("В группу"),
            tr("Куда перенести «{name}»:", name=value.name),
            items,
            current,
            False,
        )
        if not ok:
            return
        index = items.index(choice)
        target = groups[index - 1][1] if index else None
        self._apply(
            lambda: self.s.ledger.set_subconto_value_parent(
                self.s.company_id, value.id, target.id if target else None
            ),
            tr("«{name}» перенесён в «{group}»", name=value.name, group=target.name)
            if target
            else tr("«{name}» — без группы", name=value.name),
            value.id,
        )

    def _detailed(self, kind_id: int) -> bool:
        """Elements with more than a name: a contract's counterparty, a VÖEN, a currency."""
        cat = self.s.catalog
        return (
            kind_id in cat.owner_kinds or cat.has_tax_id(kind_id) or has_currency(self.s, kind_id)
        )

    def _tax_id_taken(
        self, kind_id: int, tax: tuple[str | None, bool, str | None], value_id: int | None = None
    ) -> bool:
        return tax_id_taken(self.s, self, kind_id, tax, value_id)

    def _add_detailed(self, kind_id: int, owner_id: int | None) -> None:
        group = self._group_here() if kind_id == self.kind_id() else None
        value_id = new_value(self.s, self, kind_id, owner_id=owner_id)
        if value_id is None:
            return
        if group is not None:  # the dialog adds at the top; the chosen group takes it
            self.s.ledger.set_subconto_value_parent(self.s.company_id, value_id, group)
            self.s.catalog.reload()
        if kind_id != self.kind_id():
            self.refresh(select_kind=kind_id)
        self.refresh()
        self.refresh_values(value_id)

    def _edit_detailed(self, value: SubcontoInfo) -> None:
        dlg = ValueDialog(
            self.s,
            value.kind_id,
            tr("Изменить"),
            value.name,
            value.owner_id,
            self,
            value.currency_id,
            value,
        )
        if dlg.exec() != QDialog.DialogCode.Accepted or not dlg.name.text().strip():
            return
        name, owner, currency = dlg.name.text().strip(), dlg.owner_id(), dlg.currency_id()
        tax, old_tax = dlg.tax(), (value.tax_id, value.nonresident, value.country)
        if dlg.tax_id is not None and tax != old_tax:
            if self._tax_id_taken(value.kind_id, tax, value.id):
                return
        else:
            tax = old_tax

        def save() -> None:
            cid = self.s.company_id
            with transaction(self.s.conn):
                if name != value.name:
                    self.s.ledger.update_subconto_value(cid, value.id, name, value.code)
                if dlg.owner is not None and owner != value.owner_id:
                    self.s.ledger.set_subconto_value_owner(cid, value.id, owner)
                if dlg.currency is not None and currency != value.currency_id:
                    self.s.ledger.set_subconto_value_currency(cid, value.id, currency)
                if tax != old_tax:
                    self.s.ledger.set_subconto_value_tax(cid, value.id, *tax)
                self.s.ledger.set_subconto_value_tags(cid, value.id, dlg.tags.chosen())

        self._apply(save, tr("Сохранено: {text}", text=name), value.id)

    def rename_value(self, value: SubcontoInfo | None) -> None:
        if value is None:
            return
        if self.s.catalog.kind_codes.get(value.kind_id) == "item" and not value.is_group:
            inventory = Inventory(self.s.conn, actor=self.s.ledger.actor)
            if item_details(self.s.conn, self.s.company_id, value.id) is not None:
                if open_item(self.s, inventory, value.id, self):  # unit, account, group too
                    self.refresh()
                    self.refresh_values(value.id)
                return
        if self._detailed(value.kind_id) and not value.is_group:
            self._edit_detailed(value)
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

    def delete_value(self, value: SubcontoInfo | None) -> None:
        """An element entered by mistake; a used one stays, the message says where it is."""
        if value is None:
            return
        question = tr("Удалить «{name}»?", name=value.name)
        if QMessageBox.question(self, tr("Удалить"), question) != QMessageBox.StandardButton.Yes:
            return
        inventory = Inventory(self.s.conn, actor=self.s.ledger.actor)
        self._apply(
            lambda: inventory.delete_value(self.s.company_id, value.id),
            tr("«{name}» удалён", name=value.name),
        )

    def edit_tags(self, value: SubcontoInfo) -> None:
        dlg = TagsDialog(self.s, value, self)
        accepted = dlg.exec() == QDialog.DialogCode.Accepted
        chosen = dlg.picker.chosen()
        self.s.catalog.reload()  # a tag made, renamed or deleted in the window stays
        if not accepted:
            self.refresh_values(value.id)
            return
        self._apply(
            lambda: self.s.ledger.set_subconto_value_tags(self.s.company_id, value.id, chosen),
            tr("Метки «{name}» сохранены", name=value.name),
            value.id,
        )

    def choose_currency(self, value: SubcontoInfo) -> None:
        """A USD bank account, a contract in EUR: the line takes this currency."""
        currencies = self.s.catalog.active_currencies
        items = [tr("— без валюты")] + [c.label for c in currencies]
        current = next((i + 1 for i, c in enumerate(currencies) if c.id == value.currency_id), 0)
        choice, ok = QInputDialog.getItem(
            self, tr("Валюта"), tr("Валюта «{name}»:", name=value.name), items, current, False
        )
        if not ok:
            return
        index = items.index(choice)
        currency = currencies[index - 1] if index else None
        self._apply(
            lambda: self.s.ledger.set_subconto_value_currency(
                self.s.company_id, value.id, currency.id if currency else None
            ),
            tr("«{name}»: валюта {code}", name=value.name, code=currency.code)
            if currency
            else tr("«{name}»: без валюты", name=value.name),
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
        actions = [
            (tr("Переименовать…"), lambda: self.rename_value(value)),
            (
                tr("Показать") if not value.active else tr("Скрыть"),
                lambda: self.toggle_value(value),
            ),
            (tr("В группу…"), lambda: self.move_value(value)),
            (tr("Удалить"), lambda: self.delete_value(value)),
        ]
        if not value.is_group:
            actions.insert(1, (tr("Метки…"), lambda: self.edit_tags(value)))
        if any(a.currency for a in self.s.catalog.accounts_using(value.kind_id)):
            actions.append((tr("Валюта…"), lambda: self.choose_currency(value)))
        for owned, owner in self.s.catalog.owner_kinds.items():  # a counterparty
            if owner == value.kind_id:
                actions.append(
                    (
                        tr("Добавить в «{kind}»…", kind=self.s.catalog.kinds[owned]),
                        lambda owned=owned: self.add_value(owned, value.id),
                    )
                )
        for text, fn in actions:
            act = QAction(text, menu)
            act.triggered.connect(fn)
            menu.addAction(act)
        menu.exec(self.table.viewport().mapToGlobal(pos))
