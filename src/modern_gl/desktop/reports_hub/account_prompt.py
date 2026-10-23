"""«Какой счёт?» — a report of one account opened from the page «Отчёты» or the sidebar
asks it first: a field typed as everywhere (code or name, `PickBox`), Enter opens. The
account asked last is offered again (`QSettings`)."""

from __future__ import annotations

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from modern_gl.application.catalog import AccountInfo, Catalog
from modern_gl.desktop.pick import PickBox
from modern_gl.desktop.theme import fonts
from modern_gl.desktop.widgets import button
from modern_gl.i18n import tr

LAST_SETTING = "reports/last_account"


def offered(catalog: Catalog, kind: str) -> list[AccountInfo]:
    """ОСВ по субконто — accounts with a subconto; a card or an analysis — any account
    (a group too: its card gathers the subaccounts)."""
    accounts = [
        a for a in catalog.accounts.values() if a.active and a.id not in catalog.system_account_ids
    ]
    if kind == "subconto":
        accounts = [a for a in accounts if not a.is_group and a.sc_kinds[0] is not None]
    return sorted(accounts, key=lambda a: (a.code == "", a.code, a.name))


class AccountPrompt(QDialog):
    def __init__(
        self, catalog: Catalog, kind: str, title: str, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(460)
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 20)
        root.setSpacing(12)
        caption = QLabel(title)
        caption.setFont(fonts().heading)
        root.addWidget(caption)
        root.addWidget(QLabel(tr("Какой счёт?")))
        self.account = PickBox(tr("Код или название"))
        for a in offered(catalog, kind):
            self.account.addItem(a.label, a.id)
        last = QSettings().value(LAST_SETTING)
        if last is not None:
            self.account.setCurrentIndex(self.account.findData(int(str(last))))
        self.account.activated.connect(lambda _i: self.take())
        root.addWidget(self.account)
        row = QHBoxLayout()
        row.addStretch(1)
        cancel, self.ok = button(tr("Отмена")), button(tr("Открыть"), "primary")
        cancel.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        cancel.clicked.connect(self.reject)
        self.ok.clicked.connect(self.take)
        row.addWidget(cancel)
        row.addWidget(self.ok)
        root.addLayout(row)
        self.account.setFocus()
        self.account.selectAll()

    def chosen(self) -> int | None:
        return self.account.currentData()

    def take(self) -> None:
        if self.chosen() is None:
            self.account.setFocus()
            return
        QSettings().setValue(LAST_SETTING, self.chosen())
        self.accept()


def ask_account(catalog: Catalog, kind: str, title: str, parent: QWidget) -> int | None:
    prompt = AccountPrompt(catalog, kind, title, parent)
    return prompt.chosen() if prompt.exec() else None
