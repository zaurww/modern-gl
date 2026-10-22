"""«Банк / Bank» (D47): the company's bank accounts with their balances on the left, the
statement of the chosen one on the right — every document that moved it, with the running
balance. New money in or out, and a currency conversion, start here."""

from __future__ import annotations

from datetime import date

from PySide6.QtCore import QModelIndex, QPersistentModelIndex, QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QVBoxLayout,
)

from modern_gl.application.bank import (
    IN,
    KIND_NAMES,
    OUT,
    BankOperationInput,
    BankPlace,
    StatementLine,
    place_balance,
    statement,
)
from modern_gl.application.bank import bank_places as list_places
from modern_gl.desktop.reports_page import Column, ReportPage, month_of
from modern_gl.desktop.session import Session
from modern_gl.desktop.theme import P, fonts
from modern_gl.desktop.widgets import (
    EmptyState,
    button,
    date_edit,
    edited_date,
    hide_when_viewing,
    more_button,
    ru_date,
)
from modern_gl.domain.accounts import BANK_FEE
from modern_gl.domain.errors import LedgerError
from modern_gl.domain.money import format_minor
from modern_gl.i18n import tr

PLACE_ROLE = Qt.ItemDataRole.UserRole
BALANCE_ROLE = Qt.ItemDataRole.UserRole + 1


def place_title(place: BankPlace) -> str:
    """How a bank account is named under its name: "51 · AZN"."""
    return f"{place.account_code}  ·  {place.currency or 'AZN'}"


class PlaceDelegate(QStyledItemDelegate):
    """A bank account in two lines: its name, and under it the account and the balance."""

    def sizeHint(self, option, index) -> QSize:
        return QSize(option.rect.width(), 54)

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> None:
        place: BankPlace = index.data(PLACE_ROLE)
        balance: int = index.data(BALANCE_ROLE)
        style_option = QStyleOptionViewItem(option)
        self.initStyleOption(style_option, index)
        style_option.text = ""
        widget = option.widget  # pyright: ignore[reportAttributeAccessIssue]
        style = widget.style() if widget else None
        if style is not None:  # the background: hover and selection from the stylesheet
            style.drawControl(QStyle.ControlElement.CE_ItemViewItem, style_option, painter, widget)
        rect: QRect = option.rect.adjusted(12, 8, -12, -8)  # pyright: ignore[reportAttributeAccessIssue]
        painter.save()
        painter.setFont(fonts().bold)
        painter.setPen(QColor(P.text))
        top = rect.adjusted(0, 0, 0, -rect.height() // 2)
        name = painter.fontMetrics().elidedText(
            place.name, Qt.TextElideMode.ElideRight, rect.width()
        )
        painter.drawText(top, int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), name)
        painter.setFont(fonts().small)
        bottom = rect.adjusted(0, rect.height() // 2, 0, 0)
        painter.setPen(QColor(P.secondary))
        painter.drawText(
            bottom,
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            place_title(place),
        )
        painter.setPen(QColor(P.red if balance < 0 else P.text))
        painter.drawText(
            bottom,
            int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
            format_minor(balance),
        )
        painter.restore()


class BankSettingsDialog(QDialog):
    """The account «+ Комиссия банка» puts on a new line (role bank_fee, shared with
    conversions); a line may still take another account."""

    def __init__(self, session: Session, parent=None) -> None:
        super().__init__(parent)
        self.s = session
        self.setWindowTitle(tr("Настройки банка"))
        self.setMinimumWidth(500)
        form = QFormLayout(self)
        self.fee = QComboBox()
        # long account names do not squeeze the label
        self.fee.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self.fee.setMinimumContentsLength(28)
        self.fee.addItem(tr("— не указан —"), None)
        for account in session.catalog.leaf_accounts:
            self.fee.addItem(account.label, account.id)
        current = session.ledger.account_role(session.company_id, BANK_FEE)
        self.fee.setCurrentIndex(max(self.fee.findData(current), 0))
        form.addRow(tr("Счёт комиссии банка"), self.fee)
        hint = QLabel(
            tr(
                "Счёт по умолчанию для «+ Комиссия банка» и для конвертации. "
                "В операции счёт строки можно сменить."
            )
        )
        hint.setObjectName("tertiary")
        hint.setFont(fonts().small)
        hint.setWordWrap(True)
        form.addRow(hint)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def _save(self) -> None:
        account_id = self.fee.currentData()
        try:
            if account_id != self.s.ledger.account_role(self.s.company_id, BANK_FEE):
                self.s.ledger.set_account_role(self.s.company_id, BANK_FEE, account_id)
        except LedgerError as exc:
            QMessageBox.warning(self, tr("Настройки банка"), str(exc))
            return
        self.accept()


class BankPage(ReportPage):
    key = ("bank",)
    has_period = False
    new_bank_operation = Signal(object)  # BankOperationInput: what is known already
    new_conversion = Signal()

    def __init__(self, session: Session) -> None:
        super().__init__(session, tr("Банк"))
        # money in and out: two equal buttons; a conversion and the settings are rarer
        for title, direction, tip in (
            ("+ Приход денег", IN, "Деньги пришли на счёт"),
            ("+ Расход денег", OUT, "Оплата поставщику, налоги, зарплата…"),
        ):
            control = button(tr(title), "", tr(tip))
            control.setMinimumWidth(120)
            control.clicked.connect(lambda _=False, d=direction: self.new_operation(d))
            self.header.add_action(control)
            hide_when_viewing(session.read_only, control)
        more = more_button(
            lambda: [
                (tr("Конвертация валюты…"), self.new_conversion.emit),
                None,
                (tr("Настройки банка…"), self.settings),
            ]
        )
        self.header.add_action(more)
        hide_when_viewing(session.read_only, more)

        # the period, under the title (a month, as in the reports)
        period = month_of(session.working_date)
        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.date_from = date_edit(period.date_from)
        self.date_to = date_edit(period.date_to)
        for caption, w in ((tr("Период с"), self.date_from), (tr("по"), self.date_to)):
            label = QLabel(caption)
            label.setObjectName("secondary")
            w.setFixedWidth(130)
            bar.addWidget(label)
            bar.addWidget(w)
        bar.addStretch(1)
        self.date_from.dateChanged.connect(lambda _: self.refresh())
        self.date_to.dateChanged.connect(lambda _: self.refresh())

        # bank accounts on the left of the statement
        self.places = QListWidget()
        self.places.setObjectName("places")
        self.places.setFixedWidth(250)
        self.places.setItemDelegate(PlaceDelegate(self.places))
        self.places.setSpacing(2)
        self.places.currentItemChanged.connect(lambda *_: self._place_chosen())
        root = self.layout()
        assert isinstance(root, QVBoxLayout)
        root.removeItem(self.stack)
        root.removeWidget(self.footer)
        right = QVBoxLayout()
        right.setSpacing(12)
        right.addLayout(self.stack, 1)
        right.addWidget(self.footer)
        body = QHBoxLayout()
        body.setSpacing(24)
        body.addWidget(self.places)
        body.addLayout(right, 1)
        root.insertLayout(1, bar)
        root.addLayout(body, 1)

        self.stack.removeWidget(self.empty)
        self.empty = EmptyState(
            "○",
            tr("Движений по счёту нет"),
            tr("Приход и расход за период появятся здесь."),
        )
        self.stack.addWidget(self.empty)
        self.no_accounts = EmptyState(
            "○",
            tr("Банковских счетов нет"),
            tr(
                "Счёт с типом «Банковские счета» (51, 52) и его банковские счета "
                "в справочнике «Банковские счета»."
            ),
        )
        self.stack.addWidget(self.no_accounts)
        self.refresh()

    def title(self) -> str:
        return tr("Банк")

    def settings(self) -> None:
        if BankSettingsDialog(self.s, self).exec() == QDialog.DialogCode.Accepted:
            self.s.notify(tr("Настройки банка сохранены"))

    @property
    def place(self) -> BankPlace | None:
        item = self.places.currentItem()
        return item.data(PLACE_ROLE) if item is not None else None

    def _place_chosen(self) -> None:
        if not self._filling:
            self.refresh(places=False)

    _filling = False

    def _fill_places(self) -> None:
        """The bank accounts with their balances at the end of the period."""
        current = self.place.key if self.place else None
        day = edited_date(self.date_to).isoformat()
        self._filling = True
        self.places.clear()
        for place in list_places(self.s.conn, self.s.company_id):
            item = QListWidgetItem(place.name)
            item.setData(PLACE_ROLE, place)
            item.setData(BALANCE_ROLE, place_balance(self.s.conn, self.s.company_id, place, day))
            item.setToolTip(f"{place.name}  ·  {place_title(place)}")
            self.places.addItem(item)
            if place.key == current:
                self.places.setCurrentItem(item)
        if self.places.currentItem() is None and self.places.count():
            self.places.setCurrentRow(0)
        self._filling = False

    def refresh(self, places: bool = True) -> None:
        if places:
            self._fill_places()
        super().refresh()
        if self.place is None:
            self.stack.setCurrentWidget(self.no_accounts)

    def build(self) -> None:
        place = self.place
        date_from = edited_date(self.date_from).isoformat()
        date_to = edited_date(self.date_to).isoformat()
        period = f"{ru_date(date_from)} — {ru_date(date_to)}"
        if place is None:
            self.model.set([], [])
            self.header.subtitle.setText(period)
            self.footer.setText("")
            return
        st = statement(self.s.conn, self.s.company_id, place, date_from, date_to)
        code = st.currency or "AZN"
        self.model.set(
            [
                Column(tr("Дата"), lambda r: ru_date(r.doc_date), width=100),
                Column(tr("№"), lambda r: r.number, width=60),
                Column(tr("Операция"), self._kind, width=190),
                Column(tr("Контрагент"), lambda r: r.counterparty or r.corr, width=200),
                Column(tr("Назначение"), lambda r: r.memo),
                Column(tr("Приход"), lambda r: r.money_in, money=True, width=120),
                Column(tr("Расход"), lambda r: r.money_out, money=True, width=120),
                Column(tr("Остаток"), lambda r: r.balance, money=True, width=130),
            ],
            st.lines,
            muted=lambda r: r.status == "draft",
        )
        self.header.subtitle.setText(f"{place.name}  ·  {place_title(place)}   ·   {period}")
        self.footer.setText(
            tr(
                "Остаток на начало {opening}   ·   приход {money_in}   ·   "
                "расход {money_out}   ·   остаток на конец {closing} {code}",
                opening=format_minor(st.opening),
                money_in=format_minor(st.total_in),
                money_out=format_minor(st.total_out),
                closing=format_minor(st.closing),
                code=code,
            )
        )

    @staticmethod
    def _kind(r: StatementLine) -> str:
        if r.status == "draft":
            return tr("Черновик")
        if r.kind == "conversion":
            return tr("Конвертация валюты")
        if r.kind in KIND_NAMES:
            return tr(KIND_NAMES[r.kind])
        return tr("Журнал")

    def new_operation(self, direction: str) -> None:
        """A new operation on the account chosen, dated by the working date."""
        place = self.place
        day = self.s.working_date
        self.new_bank_operation.emit(
            BankOperationInput(
                doc_date=day.isoformat() if isinstance(day, date) else str(day),
                direction=direction,
                account_id=place.account_id if place else None,
                subconto=place.subconto if place else (),
                currency_id=place.currency_id if place else None,
            )
        )

    def drill(self, row: StatementLine | None) -> None:
        if row is not None:
            self.open_document.emit(row.document_id)
