"""«Добавить субсчёт…» on an account that is not a group (D182): the
account becomes a group first. Its own history goes on as the first subaccount, named
here; nothing posted changes — postings follow the account, not its code."""

from __future__ import annotations

from PySide6.QtWidgets import QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit

from modern_gl.application.catalog import AccountInfo
from modern_gl.desktop.session import Session
from modern_gl.desktop.theme import fonts
from modern_gl.domain.errors import LedgerError
from modern_gl.i18n import tr


class SplitAccountDialog(QDialog):
    """The first subaccount's code and name; `group_id` — the group made of the account."""

    def __init__(self, session: Session, account: AccountInfo, parent=None) -> None:
        super().__init__(parent)
        self.s, self.account = session, account
        self.group_id: int | None = None
        self.setWindowTitle(tr("Сделать счёт {code} группой", code=account.short))
        self.setMinimumWidth(520)
        form = QFormLayout(self)
        used = session.catalog.has_postings(account.id)
        text = (
            tr(
                "Счёт {code} станет группой. Его проводки, остатки и операции не меняются: "
                "они останутся на первом субсчёте. Назовите его — потом добавите следующие.",
                code=account.short,
            )
            if used
            else tr(
                "Счёт {code} станет группой, а сам он — её первым субсчётом. "
                "Назовите его — потом добавите следующие.",
                code=account.short,
            )
        )
        about = QLabel(text)
        about.setWordWrap(True)
        form.addRow(about)
        self.code = QLineEdit(self._free_code())
        self.code.setPlaceholderText(tr("необязательно"))
        self.name = QLineEdit(account.name)
        form.addRow(tr("Код субсчёта"), self.code)
        form.addRow(tr("Название субсчёта"), self.name)
        self.error = QLabel()
        self.error.setObjectName("error")
        self.error.setFont(fonts().small)
        self.error.setWordWrap(True)
        self.error.hide()
        form.addRow(self.error)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        ok = buttons.button(QDialogButtonBox.StandardButton.Ok)
        ok.setText(tr("Сделать группой"))
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)
        ok.setDefault(True)
        ok.setFocus()  # the code and name offered are usually right: Enter takes them

    def _free_code(self) -> str:
        """75 → 75.1 (75.2… if taken); an account without a code — none."""
        code = self.account.code
        if not code:
            return ""
        n = 1
        while f"{code}.{n}" in self.s.catalog.by_code:
            n += 1
        return f"{code}.{n}"

    def save(self) -> None:
        try:
            self.group_id = self.s.ledger.split_account(
                self.s.company_id, self.account.id, self.code.text(), self.name.text()
            )
        except LedgerError as e:
            self.error.setText(str(e))
            self.error.show()
            return
        self.accept()
