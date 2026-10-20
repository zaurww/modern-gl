"""Directories (subconto): banks, counterparties, contracts, cost items…

Left: the directories with how many elements they have. Right: the elements.
Ins adds, F2 renames, the context menu hides / shows. Hidden elements stay in
history and reports but are no longer offered when entering postings.

Contracts belong to counterparties: their list shows whose each one is, the dialog of a
contract asks for its counterparty, and a counterparty's menu adds a contract to it.
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QAction, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QCompleter,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
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
from modern_gl.infrastructure.db import transaction

KIND_ROLE = Qt.ItemDataRole.UserRole


class ValueDialog(QDialog):
    """Name of an element and, for a contract, the counterparty it belongs to."""

    def __init__(
        self,
        session: Session,
        kind_id: int,
        title: str,
        name: str = "",
        owner_id: int | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        cat = session.catalog
        self.setWindowTitle(title)
        self.setMinimumWidth(460)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 20)
        lay.setSpacing(16)
        heading = QLabel(title)
        heading.setFont(fonts().heading)
        lay.addWidget(heading)
        form = QFormLayout()
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(10)
        self.name = QLineEdit(name)
        form.addRow(tr("Наименование"), self.name)
        owner_kind = cat.owner_kinds[kind_id]
        self.owner = QComboBox()
        self.owner.setEditable(True)  # type to find among hundreds of counterparties
        self.owner.addItem(tr("— общий для всех"), None)
        for v in cat.values(owner_kind):
            self.owner.addItem(v.name, v.id)
        completer = QCompleter([self.owner.itemText(i) for i in range(self.owner.count())], self)
        self.owner.setCompleter(completer)
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        index = self.owner.findData(owner_id)
        self.owner.setCurrentIndex(max(index, 0))
        form.addRow(cat.kinds[owner_kind], self.owner)
        lay.addLayout(form)
        note = QLabel(
            tr("Договор предлагается только вместе со своим контрагентом. Общий — с любым.")
        )
        note.setObjectName("secondary")
        note.setWordWrap(True)
        lay.addWidget(note)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)
        self.name.setFocus()

    def owner_id(self) -> int | None:
        """The chosen counterparty; text that names none of them means common."""
        text = self.owner.currentText().strip()
        index = self.owner.findText(text, Qt.MatchFlag.MatchFixedString)
        return self.owner.itemData(index) if index > 0 else None


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
        add.clicked.connect(lambda: self.add_value())
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
            ("Ins", lambda: self.add_value()),
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
            tr("Используется на счетах: {codes}", codes=", ".join(a.short for a in accounts))
            if accounts
            else tr("Пока не используется ни на одном счёте")
        )
        values = cat.all_values(kind_id)
        columns = [
            Column(
                tr("Наименование"), lambda v: v.name if v.active else f"{v.name}  ·  {tr('скрыт')}"
            ),
        ]
        widths = []
        owner_kind = cat.owner_kinds.get(kind_id)
        if owner_kind is not None:  # contracts: whose each one is, grouped by counterparty
            columns.append(Column(cat.kinds[owner_kind], self._owner_name, width=260))
            widths.append(260)
            values.sort(key=lambda v: (v.owner_id is not None, sort_key(self._owner_name(v))))
        if any(a.currency for a in accounts):
            columns.append(Column(tr("Валюта"), self._currency_code, width=120))
            widths.append(120)
        self.model.set(columns, values, muted=lambda v: not v.active)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for col, width in enumerate(widths, start=1):
            self.table.setColumnWidth(col, width)
        self.stack.setCurrentWidget(self.table if values else self.empty)
        if select_value is not None:
            row = next((i for i, v in enumerate(values) if v.id == select_value), None)
            if row is not None:
                self.table.setCurrentIndex(self.model.index(row, 0))

    def _owner_name(self, value: SubcontoInfo) -> str:
        return self.s.catalog.value(value.owner_id).name if value.owner_id else ""

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
        if kind_id in self.s.catalog.owner_kinds:
            self._add_owned(kind_id, owner_id)
            return
        name = self._ask(tr("Новый элемент"), tr("Название (справочник «{kind}»):", kind=kind))
        if name:
            self._apply(
                lambda: self.s.ledger.add_subconto_value(self.s.company_id, kind_id, name),
                tr("Добавлено в «{kind}»: {text}", kind=kind, text=name),
            )

    def _add_owned(self, kind_id: int, owner_id: int | None) -> None:
        """A contract: its name and its counterparty in one dialog."""
        kind = self.s.catalog.kinds[kind_id]
        dlg = ValueDialog(self.s, kind_id, tr("Новый элемент"), owner_id=owner_id, parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted or not dlg.name.text().strip():
            return
        name, owner = dlg.name.text().strip(), dlg.owner_id()
        if kind_id != self.kind_id():
            self.refresh(select_kind=kind_id)
        self._apply(
            lambda: self.s.ledger.add_subconto_value(
                self.s.company_id, kind_id, name, owner_id=owner
            ),
            tr("Добавлено в «{kind}»: {text}", kind=kind, text=name),
        )

    def _edit_owned(self, value: SubcontoInfo) -> None:
        dlg = ValueDialog(
            self.s, value.kind_id, tr("Переименовать"), value.name, value.owner_id, self
        )
        if dlg.exec() != QDialog.DialogCode.Accepted or not dlg.name.text().strip():
            return
        name, owner = dlg.name.text().strip(), dlg.owner_id()

        def save() -> None:
            with transaction(self.s.conn):
                if name != value.name:
                    self.s.ledger.update_subconto_value(
                        self.s.company_id, value.id, name, value.code
                    )
                if owner != value.owner_id:
                    self.s.ledger.set_subconto_value_owner(self.s.company_id, value.id, owner)

        self._apply(save, tr("Сохранено: {text}", text=name), value.id)

    def rename_value(self, value: SubcontoInfo | None) -> None:
        if value is None:
            return
        if value.kind_id in self.s.catalog.owner_kinds:
            self._edit_owned(value)
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
        ]
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
