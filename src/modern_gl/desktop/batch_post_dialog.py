"""«Провести черновики» (D87): before the drafts of a batch post, where their open lines go —
a purchase's expense account and its subconto, and the account they are owed on (60, 76…;
D110), a sale's group (D61). The place they went the last time is filled in, so a month
like the last one is one Enter; left empty, each line goes where it went the last time
(D76). A cost item missing from the list is added right in its field. Nothing is stored
here: the posted lines are what the next batch learns from."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QDialog, QFormLayout, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from modern_gl.application.common import pad_subconto
from modern_gl.application.trade_batch import Booking, OpenLines
from modern_gl.desktop.directories_page import added_value, new_value
from modern_gl.desktop.pick import ENTER, PickBox
from modern_gl.desktop.session import Session
from modern_gl.desktop.theme import fonts
from modern_gl.desktop.widgets import button
from modern_gl.i18n import tr


class BatchPostDialog(QDialog):
    def __init__(
        self,
        session: Session,
        drafts: int,
        names: str,
        lines: OpenLines,
        sale_kinds: list[int],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.s, self.lines, self.sale_kinds = session, lines, sale_kinds
        self.booking: Booking | None = None  # the choice; None: like the last time
        self.purchase = lines.doc_type == "receipt"
        self.setWindowTitle(tr("Провести"))
        self.setMinimumWidth(520)
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 20)
        root.setSpacing(12)
        title = QLabel(tr("Провести черновики: {n}", n=drafts))
        title.setFont(fonts().heading)
        root.addWidget(title)
        if names:
            who = QLabel(names)
            who.setObjectName("secondary")
            who.setWordWrap(True)
            root.addWidget(who)
        self.account: PickBox | None = None
        self.offset: PickBox | None = None  # Kt of a purchase: 60 as imported, 76…
        self.fields: list[tuple[int, PickBox]] = []  # (kind, field) of the subconto
        self.form = QFormLayout()
        if lines.count:
            root.addWidget(QLabel(self._question()))
            root.addLayout(self.form)
            self._build_fields()
            hint = QLabel(
                tr(
                    "Пусто — каждой строке как в прошлый раз. Выбранное запомнится: "
                    "следующие e-qaimə этих контрагентов предложат то же."
                )
            )
            hint.setObjectName("secondary")
            hint.setWordWrap(True)
            root.addWidget(hint)
        self.error = QLabel()
        self.error.setObjectName("error")
        self.error.setWordWrap(True)
        self.error.hide()
        root.addWidget(self.error)
        row = QHBoxLayout()
        row.addStretch(1)
        cancel, self.ok = button(tr("Отмена")), button(tr("Провести"), "primary")
        cancel.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        cancel.clicked.connect(self.reject)
        self.ok.clicked.connect(self.post)
        row.addWidget(cancel)
        row.addWidget(self.ok)
        root.addLayout(row)
        # the cursor on the first field to fill; all filled as last time — on «Провести»
        empty = next((f for f in self._chain() if f.currentData() is None), None)
        (empty or self.ok).setFocus()

    def _chain(self) -> list[PickBox]:
        """The fields in the order Enter goes through them."""
        fields = (self.account, *(f for _, f in self.fields), self.offset)
        return [f for f in fields if f is not None]

    def _question(self) -> str:
        if self.purchase:
            return tr("Строк без счёта: {n}. На какой счёт их провести?", n=self.lines.count)
        return tr("Строк без аналитики продажи: {n}. Куда их отнести?", n=self.lines.count)

    # ---- the fields --------------------------------------------------------------------

    def _build_fields(self) -> None:
        suggested = self.lines.suggested
        if self.purchase:
            catalog = self.s.catalog
            self.account = PickBox(tr("Код или название"))
            self.offset = PickBox(tr("Код или название"))
            for a in catalog.leaf_accounts:
                if not catalog.is_stock_account(a.id):
                    self.account.addItem(a.label, a.id)
                    self.offset.addItem(a.label, a.id)
            self.account.activated.connect(lambda _: self._account_chosen())
            self.offset.activated.connect(lambda _: self._go_on(self.offset))
            self.form.addRow(tr("Счёт (Дт)"), self.account)
            self.form.addRow(tr("Счёт расчётов (Кт)"), self.offset)
            if suggested is not None and suggested.account_id is not None:
                self.account.setCurrentIndex(self.account.findData(suggested.account_id))
            if self.lines.offset_account_id is not None:
                self.offset.setCurrentIndex(self.offset.findData(self.lines.offset_account_id))
            self._subconto_fields(self._account_kinds())
        else:
            self._subconto_fields(self.sale_kinds)
        for value in suggested.subconto if suggested else ():
            for kind, field in self.fields:
                if value is not None and self.s.catalog.value(value).kind_id == kind:
                    field.setCurrentIndex(field.findData(value))

    def _account_kinds(self) -> list[int]:
        account_id = self.account.currentData() if self.account else None
        if account_id is None:
            return []
        return [k for k in self.s.catalog.accounts[account_id].sc_kinds if k is not None]

    def _subconto_fields(self, kinds: list[int]) -> None:
        for _, field in self.fields:
            self.form.removeRow(field)
        self.fields = []
        for row, kind in enumerate(kinds, 1 if self.purchase else 0):  # under the account
            field = PickBox(tr("Название"))
            self._fill_values(field, kind)
            field.can_add = True  # a new cost item: added right here (D49, D54)
            field.activated.connect(lambda _, f=field: self._go_on(f))
            field.added.connect(lambda text, f=field, k=kind: self._add_value(f, k, text, True))
            field.unknown.connect(lambda text, f=field, k=kind: self._add_value(f, k, text))
            self.form.insertRow(row, self.s.catalog.kinds.get(kind, ""), field)
            self.fields.append((kind, field))

    def _fill_values(self, field: PickBox, kind: int) -> None:
        field.clear()
        for v in self.s.catalog.values(kind):
            field.addItem(v.label, v.id, v.name)

    def _add_value(self, field: PickBox, kind: int, text: str, listed: bool = False) -> None:
        """«+ Добавить «…»» picked: the name goes in at once; typed and not in the list:
        the directory's window, to check it first — as in the journal (D49, D54)."""
        add = added_value if listed else new_value
        value = add(self.s, self, kind, text)
        if value is None:
            field.setFocus()
            return
        self._fill_values(field, kind)
        field.setCurrentIndex(field.findData(value))
        self._go_on(field)

    def _account_chosen(self) -> None:
        self._subconto_fields(self._account_kinds())
        self._go_on(self.account)

    def _go_on(self, field: PickBox | None) -> None:
        """After a choice the cursor goes to the next field, after the last one to
        «Провести» — Enter there posts. Deferred: the list's Enter moves focus itself."""
        chain = self._chain()
        after = chain[chain.index(field) + 1 :] if field in chain else []
        target = after[0] if after else self.ok
        QTimer.singleShot(0, target.setFocus)

    def keyPressEvent(self, event) -> None:
        """Enter in a field only takes what was typed (the field then moves the cursor on);
        it posts from «Провести» alone, never past a field still to fill."""
        if event.key() in ENTER and not self.ok.hasFocus():
            return
        super().keyPressEvent(event)

    # ---- posting -----------------------------------------------------------------------

    def post(self) -> None:
        values = tuple(field.currentData() for _, field in self.fields)
        account_id = self.account.currentData() if self.account else None
        if self.purchase and account_id is not None:
            missing = self._missing(account_id)
            if missing is not None:
                self.error.setText(tr("Укажите «{kind}» — его требует счёт", kind=missing[0]))
                self.error.show()
                missing[1].setFocus()
                return
            offset = self.offset.currentData() if self.offset else None
            if offset == self.lines.offset_account_id:
                offset = None  # as the drafts have it: nothing to move
            self.booking = Booking(account_id, pad_subconto(values), offset)
        elif not self.purchase and any(v is not None for v in values):
            self.booking = Booking(None, tuple(v for v in values if v is not None))
        self.accept()

    def _missing(self, account_id: int) -> tuple[str, PickBox] | None:
        """The first subconto the account cannot post without that is left empty."""
        account, catalog = self.s.catalog.accounts[account_id], self.s.catalog
        fields = iter(self.fields)
        for position, kind in enumerate(account.sc_kinds):
            if kind is None:
                continue
            _, field = next(fields)
            optional = position in account.sc_optional or kind in catalog.owner_kinds
            if field.currentData() is None and not optional:
                return catalog.kinds.get(kind, ""), field
        return None
