"""An element of a directory: its window (name, owner, VÖEN, currency) and adding one
from anywhere — at once from a list, or through the window to check the name (D49, D54)."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QCompleter,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from modern_gl.application.catalog import SubcontoInfo
from modern_gl.application.ledger import ValueDetails
from modern_gl.desktop.directories_page.tags import TagPicker
from modern_gl.desktop.session import Session
from modern_gl.desktop.theme import fonts
from modern_gl.desktop.widgets import button
from modern_gl.domain.errors import LedgerError
from modern_gl.i18n import tr


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
        self.tags = TagPicker(session, value.tags if value else frozenset())
        form.addRow(tr("Метки"), self.tags)
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
        details = ValueDetails(owner, currency, tax, tuple(dlg.tags.chosen()))
        value_id = session.ledger.add_detailed_value(cid, kind_id, name, details)
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
        details = ValueDetails(owner_id, currency_id)
        value_id = session.ledger.add_detailed_value(cid, kind_id, name, details)
    except LedgerError as e:
        session.notify(str(e))
        return None
    session.catalog.reload()
    kind = session.catalog.kinds[kind_id]
    session.notify(tr("Добавлено в «{kind}»: {text}", kind=kind, text=name))
    return value_id
