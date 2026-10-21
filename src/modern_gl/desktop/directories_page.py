"""Directories (subconto): banks, counterparties, contracts, cost items…

Left: the directories with how many elements they have. Right: the elements.
Ins adds, F2 renames, the context menu hides / shows. Hidden elements stay in
history and reports but are no longer offered when entering postings.

Contracts belong to counterparties: their list shows whose each one is, the dialog of a
contract asks for its counterparty, and a counterparty's menu adds a contract to it.
A counterparty has a VÖEN; a non-resident has none, but a country and a tax number of
its own country instead.
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QAction, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QCompleter,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
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
from modern_gl.desktop.reports_page import Column, ReportModel
from modern_gl.desktop.session import Session
from modern_gl.desktop.theme import fonts
from modern_gl.desktop.widgets import EmptyState, PageHeader, button
from modern_gl.domain.errors import LedgerError
from modern_gl.i18n import sort_key, tr
from modern_gl.infrastructure.db import transaction

KIND_ROLE = Qt.ItemDataRole.UserRole


class ValueDialog(QDialog):
    """Name of an element and what else it has: for a contract, the counterparty it
    belongs to; for a counterparty, its VÖEN (or, for a non-resident, its country and
    tax number); for an element of a currency account (a bank account on 52, a foreign
    supplier on 60), its currency."""

    def __init__(
        self,
        session: Session,
        kind_id: int,
        title: str,
        name: str = "",
        owner_id: int | None = None,
        parent: QWidget | None = None,
        currency_id: int | None = None,
        value: SubcontoInfo | None = None,
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
        notes = []
        self.tax_id: QLineEdit | None = None
        self.nonresident: QCheckBox | None = None
        self.country: QLineEdit | None = None
        if cat.has_tax_id(kind_id):
            self._tax_rows(form, value)
        self.owner: QComboBox | None = None
        if kind_id in cat.owner_kinds:
            self.owner = self._owner_box(session, kind_id, owner_id)
            form.addRow(cat.owner_title(kind_id), self.owner)
            notes.append(
                tr("Договор предлагается только вместе со своим контрагентом. Общий — с любым.")
            )
        self.currency: QComboBox | None = None
        if has_currency(session, kind_id):
            self.currency = QComboBox()
            self.currency.addItem(tr("— без валюты"), None)
            for c in cat.active_currencies:
                self.currency.addItem(c.label, c.id)
            self.currency.setCurrentIndex(max(self.currency.findData(currency_id), 0))
            form.addRow(tr("Валюта"), self.currency)
            notes.append(tr("С валютой строка сама берёт её, и проводка проверяется по ней."))
        lay.addLayout(form)
        for text in notes:
            note = QLabel(text)
            note.setObjectName("secondary")
            note.setWordWrap(True)
            lay.addWidget(note)
        buttons = QHBoxLayout()  # like the account dialog: quiet Cancel, blue Save
        buttons.addStretch(1)
        cancel = button(tr("Отмена"))
        save = button(tr("Сохранить"), "primary")
        save.setDefault(True)
        cancel.clicked.connect(self.reject)
        save.clicked.connect(self.accept)
        buttons.addWidget(cancel)
        buttons.addWidget(save)
        lay.addLayout(buttons)
        self.name.setFocus()

    def _tax_rows(self, form: QFormLayout, value: SubcontoInfo | None) -> None:
        """VÖEN of a resident; country and own tax number of a non-resident."""
        nonresident = QCheckBox(tr("Нерезидент — иностранная компания или лицо"))
        nonresident.setChecked(bool(value and value.nonresident))
        form.addRow("", nonresident)
        tax_id = QLineEdit((value.tax_id if value else None) or "")
        form.addRow(tr("VÖEN"), tax_id)
        country = QLineEdit((value.country if value else None) or "")
        form.addRow(tr("Страна"), country)
        self.nonresident, self.tax_id, self.country = nonresident, tax_id, country

        def switch() -> None:
            foreign = nonresident.isChecked()
            label = form.labelForField(tax_id)
            if isinstance(label, QLabel):
                label.setText(tr("Налоговый номер") if foreign else tr("VÖEN"))
            tax_id.setPlaceholderText(
                tr("EIN, VAT ID, TIN… — как в документах") if foreign else tr("10 цифр")
            )
            form.setRowVisible(country, foreign)

        nonresident.toggled.connect(switch)
        switch()

    def tax(self) -> tuple[str | None, bool, str | None]:
        """(tax number, non-resident, country) as typed; a VÖEN without spaces."""
        if self.tax_id is None or self.nonresident is None or self.country is None:
            return None, False, None
        foreign = self.nonresident.isChecked()
        text = " ".join(self.tax_id.text().split())
        if not foreign:
            text = text.replace(" ", "")
        country = self.country.text().strip() if foreign else ""
        return text or None, foreign, country or None

    def _owner_box(self, session: Session, kind_id: int, owner_id: int | None) -> QComboBox:
        cat = session.catalog
        box = QComboBox()
        box.setEditable(True)  # type to find among hundreds of counterparties
        box.addItem(tr("— общий для всех"), None)
        for v in cat.values(cat.owner_kinds[kind_id]):
            box.addItem(v.name, v.id)
        completer = QCompleter([box.itemText(i) for i in range(box.count())], self)
        box.setCompleter(completer)
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        box.setCurrentIndex(max(box.findData(owner_id), 0))
        return box

    def owner_id(self) -> int | None:
        """The chosen counterparty; text that names none of them means common."""
        if self.owner is None:
            return None
        text = self.owner.currentText().strip()
        index = self.owner.findText(text, Qt.MatchFlag.MatchFixedString)
        return self.owner.itemData(index) if index > 0 else None

    def currency_id(self) -> int | None:
        return self.currency.currentData() if self.currency is not None else None


def has_currency(session: Session, kind_id: int) -> bool:
    """Elements of the directory may have a currency: it is used on a currency account."""
    return any(a.currency for a in session.catalog.accounts_using(kind_id))


def tax_id_taken(
    session: Session,
    parent: QWidget,
    kind_id: int,
    tax: tuple[str | None, bool, str | None],
    value_id: int | None = None,
) -> bool:
    """A VÖEN another counterparty already has: save anyway (a branch) or go back."""
    tax_id, foreign, _ = tax
    if tax_id is None or foreign:
        return False
    others = session.catalog.same_tax_id(kind_id, tax_id, value_id)
    if not others:
        return False
    question = tr(
        "VÖEN {tax_id} уже есть у «{name}». Всё равно сохранить?", tax_id=tax_id, name=others[0]
    )
    return QMessageBox.question(parent, tr("VÖEN"), question) != QMessageBox.StandardButton.Yes


def new_value(
    session: Session,
    parent: QWidget,
    kind_id: int,
    typed: str = "",
    owner_id: int | None = None,
    currency_id: int | None = None,
) -> int | None:
    """A new element in the window of its directory, also right where it is needed (D49):
    what was typed is its name — or its VÖEN, if it is digits. The new id, or None."""
    cat = session.catalog
    kind = cat.kinds[kind_id]
    dlg = ValueDialog(
        session,
        kind_id,
        tr("Новый элемент"),
        owner_id=owner_id,
        parent=parent,
        currency_id=currency_id,
    )
    digits = typed.replace(" ", "")
    if dlg.tax_id is not None and digits.isdigit():
        dlg.tax_id.setText(digits)
    else:
        dlg.name.setText(typed.strip())
    if dlg.exec() != QDialog.DialogCode.Accepted or not dlg.name.text().strip():
        return None
    name, owner, currency = dlg.name.text().strip(), dlg.owner_id(), dlg.currency_id()
    tax = dlg.tax()
    if tax_id_taken(session, parent, kind_id, tax):
        return None
    cid = session.company_id
    try:
        with transaction(session.conn):
            value_id = session.ledger.add_subconto_value(cid, kind_id, name, owner_id=owner)
            if currency is not None:
                session.ledger.set_subconto_value_currency(cid, value_id, currency)
            if tax != (None, False, None):
                session.ledger.set_subconto_value_tax(cid, value_id, *tax)
    except LedgerError as e:
        session.notify(str(e))
        return None
    cat.reload()
    session.notify(tr("Добавлено в «{kind}»: {text}", kind=kind, text=name))
    return value_id


def added_value(
    session: Session,
    parent: QWidget,
    kind_id: int,
    typed: str,
    owner_id: int | None = None,
    currency_id: int | None = None,
) -> int | None:
    """ "+ Добавить «…»" picked from a list: the name goes in at once, no window, as in the
    journal (D54). Digits are a VÖEN, not a name: those still open the window."""
    name = typed.strip()
    if not name:
        return None
    if name.replace(" ", "").isdigit():
        return new_value(session, parent, kind_id, name, owner_id, currency_id)
    cid = session.company_id
    try:
        with transaction(session.conn):
            value_id = session.ledger.add_subconto_value(cid, kind_id, name, owner_id=owner_id)
            if currency_id is not None:
                session.ledger.set_subconto_value_currency(cid, value_id, currency_id)
    except LedgerError as e:
        session.notify(str(e))
        return None
    session.catalog.reload()
    kind = session.catalog.kinds[kind_id]
    session.notify(tr("Добавлено в «{kind}»: {text}", kind=kind, text=name))
    return value_id


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
        columns = [
            Column(
                tr("Наименование"), lambda v: v.name if v.active else f"{v.name}  ·  {tr('скрыт')}"
            ),
        ]
        widths = []
        owner_kind = cat.owner_kinds.get(kind_id)
        if owner_kind is not None:  # contracts: whose each one is, grouped by counterparty
            columns.append(Column(cat.owner_title(kind_id), self._owner_name, width=260))
            widths.append(260)
            values.sort(key=lambda v: (v.owner_id is not None, sort_key(self._owner_name(v))))
        if cat.has_tax_id(kind_id):
            columns.append(Column(tr("VÖEN"), self._tax_text, width=260))
            widths.append(260)
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
        name = self._ask(tr("Новый элемент"), tr("Название (справочник «{kind}»):", kind=kind))
        if name:
            self._apply(
                lambda: self.s.ledger.add_subconto_value(self.s.company_id, kind_id, name),
                tr("Добавлено в «{kind}»: {text}", kind=kind, text=name),
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
        value_id = new_value(self.s, self, kind_id, owner_id=owner_id)
        if value_id is None:
            return
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

        self._apply(save, tr("Сохранено: {text}", text=name), value.id)

    def rename_value(self, value: SubcontoInfo | None) -> None:
        if value is None:
            return
        if self._detailed(value.kind_id):
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
            (tr("Удалить"), lambda: self.delete_value(value)),
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
