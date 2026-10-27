"""Add or edit an account: code, name, parent, group, type (and so class), subconto."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from modern_gl.application.catalog import AccountInfo
from modern_gl.application.ledger import AccountForm
from modern_gl.desktop.session import Session
from modern_gl.desktop.theme import fonts
from modern_gl.desktop.widgets import button, class_icon, type_choices
from modern_gl.domain.accounts import TYPE_CLASS
from modern_gl.domain.currency import CURRENCY_ONLY, CURRENCY_OPTIONAL, NO_CURRENCY
from modern_gl.domain.errors import LedgerError
from modern_gl.i18n import N_, tr

AUTO = "auto"  # type combobox: let the ledger decide (the parent's type and class)
CURRENCY_CHOICES = (
    (NO_CURRENCY, N_("Только в манатах")),
    (CURRENCY_OPTIONAL, N_("В манатах и в валюте")),
    (CURRENCY_ONLY, N_("Только в валюте")),
)


class AccountDialog(QDialog):
    """`account=None` creates a new account (optionally under the account `parent_id`)."""

    def __init__(
        self,
        session: Session,
        account: AccountInfo | None = None,
        parent_id: int | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.s = session
        self.account = account
        self.setWindowTitle(tr("Счёт {code}", code=account.short) if account else tr("Новый счёт"))
        self.setMinimumWidth(560)

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 20)
        root.setSpacing(16)
        title = QLabel(self.windowTitle())
        title.setFont(fonts().heading)
        root.addWidget(title)

        form = QFormLayout()
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(10)
        self._build_fields(account, parent_id)
        self._build_type(account)
        self.contra = QCheckBox(tr("Контрсчёт"))
        class_row = QHBoxLayout()
        class_row.addWidget(self.account_type, 1)
        class_row.addWidget(self.contra)
        self._build_subconto()

        form.addRow(tr("Код"), self.code)
        form.addRow(tr("Наименование"), self.name)
        form.addRow(tr("Родитель"), self.parent_box)
        form.addRow("", self.group)
        form.addRow(tr("Тип"), class_row)
        form.addRow("", self.two_sided)
        form.addRow(tr("Валюта"), self.currency)
        for i, (box, optional) in enumerate(zip(self.subconto, self.optional, strict=True), 1):
            row = QHBoxLayout()
            row.addWidget(box, 1)
            row.addWidget(optional)
            form.addRow(tr("Субконто {i}", i=i), row)
        self._build_subconto_hint(form)
        root.addLayout(form)

        self.error = QLabel()
        self.error.setObjectName("error")
        self.error.setWordWrap(True)
        self.error.hide()
        root.addWidget(self.error)

        self._build_buttons(root)

        self.group.toggled.connect(self._group_toggled)
        if account:
            self._load(account)
        else:
            self._prefill_child(parent_id)

    def _build_fields(self, account: AccountInfo | None, parent_id: int | None) -> None:
        self.code = QLineEdit(account.code if account else "")
        self.code.setPlaceholderText(tr("необязательно"))
        self.name = QLineEdit(account.name if account else "")
        self.parent_box = QComboBox()
        self.parent_box.addItem("—", None)
        for a in self.s.catalog.accounts.values():
            if a.is_group or (account is None and a.id == parent_id):
                self.parent_box.addItem(a.label, a.id)
        self.two_sided = QCheckBox(tr("Сальдо бывает с обеих сторон"))
        self.two_sided.setToolTip(
            tr(
                "Расчёты с контрагентами, налоги: дебетовые и кредитовые остатки "
                "показываются развёрнуто и не считаются ошибкой"
            )
        )
        self.group = QCheckBox(tr("Группа (есть субсчета, проводки только на субсчета)"))
        self.currency = QComboBox()
        for mode, text in CURRENCY_CHOICES:
            self.currency.addItem(tr(text), mode)
        self.currency.setToolTip(
            tr(
                "Проводки в валюте несут валюту и сумму в ней; остатки в валюте "
                "переоцениваются по курсу"
            )
        )

    def _build_type(self, account: AccountInfo | None) -> None:
        # Type picker grouped by class: a class alone in bold, then its types. Item data is
        # the type, or the class for a class alone ("" — not set); see _choice()
        self.account_type = QComboBox()
        self.account_type.setMaxVisibleItems(20)
        self.account_type.setToolTip(
            tr("Тип говорит программе, что это за счёт, при любом коде: по нему строятся отчёты")
        )
        if account is None:
            self.account_type.addItem(tr("Автоматически"), AUTO)
        for cls, t, text in type_choices():
            self.account_type.addItem(class_icon(cls), text, t or cls or "")
            if cls and not t:
                self.account_type.setItemData(
                    self.account_type.count() - 1, fonts().cell_bold, Qt.ItemDataRole.FontRole
                )

    def _build_subconto(self) -> None:
        self.subconto = []
        self.optional = []  # the position may stay empty: 70 paid in one sum (D78)
        for _ in range(3):
            box = QComboBox()
            box.addItem("—", None)
            for kind_id, kind_name in sorted(self.s.catalog.kinds.items(), key=lambda kv: kv[1]):
                box.addItem(kind_name, kind_id)
            optional = QCheckBox(tr("можно не заполнять"))
            policy = optional.sizePolicy()
            policy.setRetainSizeWhenHidden(True)  # the boxes keep their width
            optional.setSizePolicy(policy)
            optional.setVisible(False)
            box.currentIndexChanged.connect(self._fit_optional)
            self.subconto.append(box)
            self.optional.append(optional)

    def _fit_optional(self, *_) -> None:
        for box, optional in zip(self.subconto, self.optional, strict=True):
            kind = box.currentData() is not None and not self.group.isChecked()
            optional.setVisible(kind)  # a locked kind (old postings) still may turn optional
            if not kind:
                optional.setChecked(False)

    def _build_subconto_hint(self, form: QFormLayout) -> None:
        # an account with postings keeps its subconto; a new one goes to a free place (D61)
        self.subconto_hint = QLabel(
            tr(
                "По счёту есть проводки: субконто можно только добавить. "
                "В старых проводках оно останется пустым («<не указано>» в отчётах)."
            )
        )
        self.subconto_hint.setObjectName("tertiary")
        self.subconto_hint.setFont(fonts().small)
        self.subconto_hint.setWordWrap(True)
        self.subconto_hint.hide()
        form.addRow("", self.subconto_hint)

    def _build_buttons(self, root: QVBoxLayout) -> None:
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = button(tr("Отмена"))
        save = button(tr("Сохранить"), "primary")
        save.setDefault(True)
        cancel.clicked.connect(self.reject)
        save.clicked.connect(self.save)
        buttons.addWidget(cancel)
        buttons.addWidget(save)
        root.addLayout(buttons)

    # ---- state -----------------------------------------------------------------------

    def _select(self, box: QComboBox, value) -> None:
        i = box.findData(value)
        if i >= 0:
            box.setCurrentIndex(i)

    def _load(self, a: AccountInfo) -> None:
        parent = next((p for p in self.s.catalog.accounts.values() if p.id == a.parent_id), None)
        self._select(self.parent_box, parent.id if parent else None)
        self.parent_box.setEnabled(False)  # moving accounts between groups: not yet
        self.two_sided.setChecked(a.two_sided)
        self._select(self.currency, a.currency)
        self.group.setChecked(a.is_group)
        self._select(self.account_type, a.account_type or a.account_class or "")
        self.contra.setChecked(a.contra)
        for box, kind_id in zip(self.subconto, a.sc_kinds, strict=True):
            self._select(box, kind_id)
        for position, optional in enumerate(self.optional):
            optional.setChecked(position in a.sc_optional)
        if not a.is_group and self.s.catalog.has_postings(a.id):
            self.subconto_hint.show()
            for box, kind_id in zip(self.subconto, a.sc_kinds, strict=True):
                if kind_id is not None:  # old postings carry values of this kind
                    box.setEnabled(False)

    def _prefill_child(self, parent_id: int | None) -> None:
        if not parent_id:
            return
        cat = self.s.catalog
        parent = cat.accounts[parent_id]
        self._select(self.parent_box, parent_id)
        self.two_sided.setChecked(parent.two_sided)
        self._select(self.currency, parent.currency)
        if parent.code:  # a coded parent suggests the next subaccount code: 60.1, 60.2…
            n = 1
            while f"{parent.code}.{n}" in cat.by_code:
                n += 1
            self.code.setText(f"{parent.code}.{n}")
        self.name.setFocus()

    def _group_toggled(self, on: bool) -> None:
        for box in self.subconto:
            box.setEnabled(not on)
        self._fit_optional()

    def _choice(self) -> tuple[str | None, str | None]:
        """(class, type) picked; (None, None) for "automatically" and "not set"."""
        key = self.account_type.currentData()
        if key in TYPE_CLASS:
            return TYPE_CLASS[key], key
        return (None, None) if key in (AUTO, "") else (key, None)

    # ---- save ------------------------------------------------------------------------

    def _optional_positions(self, subconto: list[int | None]) -> set[int]:
        """Ticked positions, and one just added to an account with postings: the old
        postings have no value there (D61)."""
        ticked = {i for i, box in enumerate(self.optional) if box.isChecked()}
        a = self.account
        if a is not None and self.s.catalog.has_postings(a.id):
            ticked |= {
                i for i, kind in enumerate(subconto) if kind is not None and a.sc_kinds[i] is None
            }
        return {i for i in ticked if i < len(subconto) and subconto[i] is not None}

    def save(self) -> None:
        led, cid = self.s.ledger, self.s.company_id
        code, name = self.code.text().strip(), self.name.text().strip()
        two_sided = self.two_sided.isChecked()
        group = self.group.isChecked()
        subconto = [] if group else [b.currentData() for b in self.subconto]
        while subconto and subconto[-1] is None:
            subconto.pop()
        account_class, account_type = self._choice()
        form = AccountForm(
            code,
            name,
            parent_id=self.parent_box.currentData() if self.account is None else None,
            is_group=group,
            subconto=subconto,
            account_class=account_class,
            account_type=account_type,
            contra=self.contra.isChecked(),
            two_sided=two_sided,
            currency=self.currency.currentData(),
            optional=frozenset(self._optional_positions(subconto)),
        )
        try:
            saved_id = led.save_account_form(
                cid, None if self.account is None else self.account.id, form
            )
        except (LedgerError, KeyError) as e:
            self.error.setText(str(e).strip("'\""))
            self.error.show()
            return
        self.saved_id = saved_id
        self.accept()
