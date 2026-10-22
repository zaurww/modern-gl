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

from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QDialog,
    QInputDialog,
    QMenu,
    QMessageBox,
)

from modern_gl.application.catalog import SubcontoInfo
from modern_gl.application.inventory import Inventory
from modern_gl.application.ledger import ValueDetails
from modern_gl.desktop.directories_page.form import DirectoriesForm
from modern_gl.desktop.directories_page.tags import TagsDialog
from modern_gl.desktop.directories_page.values import (
    ValueDialog,
    has_currency,
    new_value,
    tax_id_taken,
)
from modern_gl.desktop.inventory_page import open_item
from modern_gl.domain.errors import LedgerError
from modern_gl.i18n import tr
from modern_gl.reporting.inventory import item_details


class DirectoriesPage(DirectoriesForm):
    key = ("directories",)

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
            details = ValueDetails(owner, currency, tax, tuple(dlg.tags.chosen()))
            self.s.ledger.save_detailed_value(
                self.s.company_id,
                value.id,
                name,
                details,
                owner_shown=dlg.owner is not None,
                currency_shown=dlg.currency is not None,
            )

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
