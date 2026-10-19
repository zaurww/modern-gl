"""Add or edit an account: code, name, parent, kind, group, class, subconto."""

from __future__ import annotations

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
from modern_gl.desktop.session import Session
from modern_gl.desktop.theme import fonts
from modern_gl.desktop.widgets import ACCOUNT_CLASSES, button, class_icon
from modern_gl.domain.errors import LedgerError
from modern_gl.i18n import tr
from modern_gl.infrastructure.db import transaction

AUTO = "auto"  # class combobox: let the ledger decide (parent's class or from kind)


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
        cat = session.catalog
        self.setWindowTitle(tr("Счёт {code}", code=account.short) if account else tr("Новый счёт"))
        self.setMinimumWidth(520)

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 20)
        root.setSpacing(16)
        title = QLabel(self.windowTitle())
        title.setFont(fonts().heading)
        root.addWidget(title)

        form = QFormLayout()
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(10)
        self.code = QLineEdit(account.code if account else "")
        self.code.setPlaceholderText(tr("необязательно"))
        self.name = QLineEdit(account.name if account else "")
        self.parent_box = QComboBox()
        self.parent_box.addItem("—", None)
        for a in cat.accounts.values():
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
        self.account_class = QComboBox()
        if account is None:
            self.account_class.addItem(tr("Автоматически"), AUTO)
        for code, name, _ in ACCOUNT_CLASSES:
            self.account_class.addItem(class_icon(code), tr(name), code)
        self.account_class.addItem(class_icon(None), tr("Не задан"), None)
        self.contra = QCheckBox(tr("Контрсчёт"))
        class_row = QHBoxLayout()
        class_row.addWidget(self.account_class, 1)
        class_row.addWidget(self.contra)
        self.subconto = []
        for _ in range(3):
            box = QComboBox()
            box.addItem("—", None)
            for kind_id, kind_name in sorted(cat.kinds.items(), key=lambda kv: kv[1]):
                box.addItem(kind_name, kind_id)
            self.subconto.append(box)

        form.addRow(tr("Код"), self.code)
        form.addRow(tr("Наименование"), self.name)
        form.addRow(tr("Родитель"), self.parent_box)
        form.addRow("", self.group)
        form.addRow(tr("Класс"), class_row)
        form.addRow("", self.two_sided)
        for i, box in enumerate(self.subconto, start=1):
            form.addRow(tr("Субконто {i}", i=i), box)
        root.addLayout(form)

        self.error = QLabel()
        self.error.setObjectName("error")
        self.error.setWordWrap(True)
        self.error.hide()
        root.addWidget(self.error)

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

        self.group.toggled.connect(self._group_toggled)
        if account:
            self._load(account)
        else:
            self._prefill_child(parent_id)

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
        self.group.setChecked(a.is_group)
        self._select(self.account_class, a.account_class)
        self.contra.setChecked(a.contra)
        for box, kind_id in zip(self.subconto, a.sc_kinds, strict=True):
            self._select(box, kind_id)

    def _prefill_child(self, parent_id: int | None) -> None:
        if not parent_id:
            return
        cat = self.s.catalog
        parent = cat.accounts[parent_id]
        self._select(self.parent_box, parent_id)
        self.two_sided.setChecked(parent.two_sided)
        if parent.code:  # a coded parent suggests the next subaccount code: 60.1, 60.2…
            n = 1
            while f"{parent.code}.{n}" in cat.by_code:
                n += 1
            self.code.setText(f"{parent.code}.{n}")
        self.name.setFocus()

    def _group_toggled(self, on: bool) -> None:
        for box in self.subconto:
            box.setEnabled(not on)

    # ---- save ------------------------------------------------------------------------

    def save(self) -> None:
        led, cid = self.s.ledger, self.s.company_id
        code, name = self.code.text().strip(), self.name.text().strip()
        two_sided = self.two_sided.isChecked()
        group = self.group.isChecked()
        subconto = [] if group else [b.currentData() for b in self.subconto]
        while subconto and subconto[-1] is None:
            subconto.pop()
        account_class = self.account_class.currentData()
        try:
            with transaction(self.s.conn):
                if self.account is None:
                    parent_id = self.parent_box.currentData()
                    if parent_id and not self.s.catalog.accounts[parent_id].is_group:
                        # Adding the first subaccount turns a plain account into a group.
                        led.update_account(cid, parent_id, is_group=True)
                    saved_id = led.add_account(
                        cid,
                        code,
                        name,
                        two_sided=two_sided,
                        parent=parent_id,
                        is_group=group,
                        subconto=subconto,
                        account_class=None if account_class == AUTO else account_class,
                        contra=self.contra.isChecked(),
                    )
                else:
                    a = self.account
                    saved_id = a.id
                    led.update_account(
                        cid,
                        a.id,
                        new_code=code,
                        name=name,
                        two_sided=two_sided,
                        is_group=group,
                        subconto=subconto,
                    )
                    if account_class != a.account_class or self.contra.isChecked() != a.contra:
                        led.set_account_class(cid, a.id, account_class, self.contra.isChecked())
        except (LedgerError, KeyError) as e:
            self.error.setText(str(e).strip("'\""))
            self.error.show()
            return
        self.saved_id = saved_id
        self.accept()
