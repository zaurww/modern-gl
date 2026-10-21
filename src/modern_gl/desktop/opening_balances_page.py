"""The company's opening balances, entered like a trial balance: Дебет or Кредит."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import date, timedelta
from fractions import Fraction
from typing import cast

from PySide6.QtCore import QPersistentModelIndex, Qt, QTimer, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemDelegate,
    QAbstractItemView,
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from modern_gl.application.currencies import rate_on
from modern_gl.application.ledger import PostingInput
from modern_gl.application.queries import PostingData, load_document, opening_document
from modern_gl.desktop.postings import (
    AMOUNT,
    CT,
    DT,
    HEADER_FIELDS,
    HEADERS,
    INVOICE,
    MEMO,
    EntryHints,
    PostingRow,
    PostingsDelegate,
    PostingsModel,
    PostingsTable,
    header_columns,
    header_names,
)
from modern_gl.desktop.session import Session
from modern_gl.desktop.theme import P, fonts
from modern_gl.desktop.widgets import (
    Chip,
    PageHeader,
    button,
    date_edit,
    edited_date,
    money,
    ru_date,
    to_qdate,
)
from modern_gl.domain.accounts import DEBIT_NORMAL
from modern_gl.domain.errors import LedgerError, ValidationError
from modern_gl.i18n import tr

HINT = (
    "Enter / Tab — следующее поле   ·   Ins — строка   ·   F9 — копия   ·   "
    "Del — удалить   ·   Ctrl+V — вставить из Excel   ·   Ctrl+Enter — провести"
)
CREDIT_AMOUNT = len(HEADERS)  # the second amount column, after "Дебет" (AMOUNT)
OPENING_FIELDS = [
    (header_names("Счёт", "Код"), DT),
    (header_names("Дебет", "Дт", "Сальдо Дт", "Сальдо дебет"), AMOUNT),
    (header_names("Кредит", "Кт", "Сальдо Кт", "Сальдо кредит"), CREDIT_AMOUNT),
    *((names, col) for names, col in HEADER_FIELDS if col not in (DT, CT, AMOUNT)),
]


@dataclass
class OpeningRow(PostingRow):
    """A balance: the account sits in the debit slot, the counter-account "00" in the
    credit slot; `on_credit` tells which column the amount is shown in and which side
    of the account it lands on."""

    on_credit: bool = False

    def is_empty(self) -> bool:
        return (
            self.debit is None
            and self.amount is None
            and self.currency_amount is None
            and not self.memo.strip()
            and not self.invoice
        )


class OpeningPostingsModel(PostingsModel):
    """One balance per line: account, subconto, then the amount in "Дебет" or "Кредит"."""

    def __init__(self, catalog, control_account: int) -> None:
        self.control_account = control_account
        super().__init__(catalog, inherit_invoices=False)
        self.rows = [self._blank()]

    def _blank(self) -> OpeningRow:
        return OpeningRow(credit=self.control_account)

    def row_from(self, p: PostingData) -> OpeningRow:
        row = PostingRow.from_data(p)
        on_credit = p.debit_account_id == self.control_account
        account, sc = (row.credit, row.credit_sc) if on_credit else (row.debit, row.debit_sc)
        fields = asdict(row) | {
            "debit": account,
            "debit_sc": sc,
            "credit": self.control_account,
            "credit_sc": [None, None, None],
        }
        return OpeningRow(**fields, on_credit=on_credit)

    # ---- columns ---------------------------------------------------------------------

    def columnCount(self, parent=None) -> int:
        return 0 if parent is not None and parent.isValid() else len(HEADERS) + 1

    def headerData(self, section, orientation, role: int = Qt.ItemDataRole.DisplayRole):
        titles = {DT: "Счёт", AMOUNT: "Дебет", CREDIT_AMOUNT: "Кредит"}
        if (
            role == Qt.ItemDataRole.DisplayRole
            and orientation == Qt.Orientation.Horizontal
            and section in titles
        ):
            return tr(titles[section])
        return super().headerData(section, orientation, role)

    def column_order(self) -> list[int]:
        return [*range(AMOUNT + 1), CREDIT_AMOUNT, MEMO, INVOICE]

    def is_number(self, col: int) -> bool:
        return col == CREDIT_AMOUNT or super().is_number(col)

    def header_columns(self, cells: list[str]) -> list[int | None] | None:
        return header_columns(cells, OPENING_FIELDS)

    def applies(self, row: int, col: int) -> bool:
        return col == CREDIT_AMOUNT or super().applies(row, col)

    # ---- values ----------------------------------------------------------------------

    def _text(self, row: int, col: int, display: bool) -> str:
        if col in (AMOUNT, CREDIT_AMOUNT):
            if (col == CREDIT_AMOUNT) != cast(OpeningRow, self.rows[row]).on_credit:
                return ""
            col = AMOUNT
        return super()._text(row, col, display)

    def parse(self, row: int, col: int, text: str):
        return super().parse(row, AMOUNT if col == CREDIT_AMOUNT else col, text)

    def setData(self, index, value, role: int = Qt.ItemDataRole.EditRole) -> bool:
        if self.read_only or role != Qt.ItemDataRole.EditRole:
            return False
        row, col = index.row(), index.column()
        r = cast(OpeningRow, self.rows[row])
        if col in (AMOUNT, CREDIT_AMOUNT):
            on_credit = col == CREDIT_AMOUNT
            if value is None and on_credit != r.on_credit:
                return True  # clearing the empty column leaves the other one alone
            r.on_credit = on_credit
            super().setData(self.index(row, AMOUNT), value, role)
            self._row_changed(row)
            return True
        had_amount = r.amount is not None or r.currency_amount is not None
        done = super().setData(index, value, role)
        if col == DT and r.debit is not None and not had_amount:
            account = self.catalog.accounts[r.debit]
            # a new line takes the account's normal side: 60 or 80 in "Кредит", 02 too
            credit_normal = account.account_class not in (None, *DEBIT_NORMAL)
            r.on_credit = account.account_class is not None and credit_normal != account.contra
            self._row_changed(row)
        return done

    def totals(self) -> tuple[int, int]:
        """Debit and credit balances entered so far."""
        rows = cast(list[OpeningRow], self.rows)
        debit = sum(r.amount or 0 for r in rows if not r.on_credit)
        credit = sum(r.amount or 0 for r in rows if r.on_credit)
        return debit, credit

    # ---- rows ------------------------------------------------------------------------

    def insert_row(self, at: int | None = None, row: PostingRow | None = None) -> int:
        return super().insert_row(at, row or self._blank())

    def duplicate_row(self, i: int) -> int:
        src = cast(OpeningRow, self.rows[i])
        return self.insert_row(
            i + 1, replace(src, debit_sc=list(src.debit_sc), credit_sc=[None, None, None])
        )

    def to_inputs(self) -> list[PostingInput]:
        """A debit balance is "Дт account / Кт 00", a credit one "Дт 00 / Кт account"."""
        lines: list[PostingRow] = []
        for n, r in enumerate(cast(list[OpeningRow], self.rows), start=1):
            if r.is_empty():
                lines.append(PostingRow())  # skipped, but keeps the line numbers
                continue
            if r.debit is None:
                raise ValidationError(tr("строка {line}: не указан счёт", line=n))
            balance = replace(r, debit_sc=list(r.debit_sc), credit_sc=[None, None, None])
            if r.on_credit:
                balance = replace(
                    balance,
                    debit=self.control_account,
                    debit_sc=[None, None, None],
                    credit=r.debit,
                    credit_sc=list(r.debit_sc),
                )
            lines.append(balance)
        rows = self.rows
        self.rows = lines
        try:
            return super().to_inputs() if any(not r.is_empty() for r in lines) else []
        finally:
            self.rows = rows


class OpeningBalancesPage(QWidget):
    key = ("opening",)
    saved = Signal(int)

    def __init__(self, session: Session) -> None:
        super().__init__()
        self.setObjectName("page")
        self.s = session
        self.doc_id: int | None = None
        self.doc_status: str | None = None
        self.dirty = False

        self.control_account = session.ledger.opening_account(session.company_id)
        session.catalog.reload()
        control_code = session.catalog.accounts[self.control_account].short

        root = QVBoxLayout(self)
        root.setContentsMargins(40, 30, 40, 22)
        root.setSpacing(12)
        self.header = PageHeader(tr("Начальные остатки"), tr("Сальдо до первой операции"))
        self.status = Chip(tr("Новый"), "blue")
        self.header.add_action(self.status)
        root.addWidget(self.header)

        meta = QHBoxLayout()
        caption = QLabel(tr("Остатки на начало дня"))
        caption.setObjectName("secondary")
        meta.addWidget(caption)
        self.date = date_edit(date(session.working_date.year, 1, 1))
        self.date.setFixedWidth(130)
        meta.addWidget(self.date)
        meta.addStretch(1)
        root.addLayout(meta)

        note = QFrame()
        note.setObjectName("note")
        note_lay = QHBoxLayout(note)
        note_lay.setContentsMargins(14, 8, 14, 8)
        explanation = QLabel(
            tr(
                "Перенесите сальдо из ОСВ: счёт, субконто и сумму в колонке «Дебет» или "
                "«Кредит» — можно вставить из Excel. Пока итоги не совпадают, разница "
                "остаётся на счёте {code} и видна в ОСВ.",
                code=control_code,
            )
        )
        explanation.setWordWrap(True)
        note_lay.addWidget(explanation)
        root.addWidget(note)

        self.model = OpeningPostingsModel(session.catalog, self.control_account)
        self.model.rate_for = self._rate_for
        delegate = PostingsDelegate(session.catalog, self, EntryHints())
        delegate.error.connect(self.show_error)
        delegate.unknown_value.connect(self._offer_new_value)
        delegate.add_value = self._add_value
        self.table = PostingsTable(self.model, delegate)
        for column in range(CT, CT + 4):  # the counter-account is always the same
            self.table.setColumnHidden(column, True)
        self.table.setColumnWidth(CREDIT_AMOUNT, self.table.columnWidth(AMOUNT))
        for keys, fn, editing in (
            ("Ins", self._insert_row, True),
            ("F9", self._duplicate_row, True),
            ("Del", self._remove_row, False),
            ("Ctrl+V", self.paste, False),
            ("Ctrl+C", self.copy, False),
        ):
            shortcut = QShortcut(QKeySequence(keys), self.table)
            shortcut.setContext(
                Qt.ShortcutContext.WidgetWithChildrenShortcut
                if editing
                else Qt.ShortcutContext.WidgetShortcut
            )
            shortcut.activated.connect(fn)
        root.addWidget(self.table, 1)

        self.error = QLabel()
        self.error.setObjectName("error")
        self.error.setWordWrap(True)
        self.error.hide()
        root.addWidget(self.error)

        totals = QHBoxLayout()
        hint = QLabel(tr(HINT))
        hint.setObjectName("tertiary")
        hint.setFont(fonts().small)
        hint.setWordWrap(True)
        totals.addWidget(hint, 1)
        self.total_debit = QLabel()
        self.total_credit = QLabel()
        self.difference = QLabel()
        self.difference.setStyleSheet(f"color: {P.red};")
        self.difference.setToolTip(tr("Останется на счёте {code}", code=control_code))
        self.difference_title = QLabel(tr("Разница"))
        for title, value in (
            (QLabel(tr("Дебет")), self.total_debit),
            (QLabel(tr("Кредит")), self.total_credit),
            (self.difference_title, self.difference),
        ):
            title.setObjectName("secondary")
            totals.addWidget(title)
            value.setFont(fonts().total)
            value.setMinimumWidth(120)
            value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            totals.addWidget(value)
        root.addLayout(totals)

        actions = QHBoxLayout()
        self.btn_difference = button(tr("Разницу — на счёт…"), "flat")
        self.btn_difference.setToolTip(
            tr("Добавить строку, которая закрывает разницу, — останется выбрать счёт")
        )
        actions.addWidget(self.btn_difference)
        actions.addStretch(1)
        self.btn_save = button(tr("Сохранить черновик"), tooltip="Ctrl+S")
        self.btn_post = button(tr("Провести"), "primary", "Ctrl+Enter")
        self.btn_post.setMinimumWidth(130)
        actions.addWidget(self.btn_save)
        actions.addWidget(self.btn_post)
        root.addLayout(actions)

        self.btn_difference.clicked.connect(self.close_difference)
        self.btn_save.clicked.connect(lambda: self.save(post=False))
        self.btn_post.clicked.connect(lambda: self.save(post=True))
        self.date.dateChanged.connect(self._changed)
        self.date.dateChanged.connect(self._date_changed)
        self.model.changed.connect(self._changed)
        self._shortcut("Ctrl+S", lambda: self.save(post=False))
        self._shortcut("Ctrl+Return", lambda: self.save(post=True))
        self._shortcut("Ctrl+Enter", lambda: self.save(post=True))
        self.refresh()

    def title(self) -> str:
        return tr("Начальные остатки")

    def is_dirty(self) -> bool:
        return self.dirty

    def focus_table(self) -> None:
        self.table.setFocus()

    def _shortcut(self, keys: str, fn) -> None:
        shortcut = QShortcut(QKeySequence(keys), self)
        shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        shortcut.activated.connect(fn)

    def _rate_for(self, currency_id: int) -> Fraction | None:
        day = edited_date(self.date) - timedelta(days=1)  # the day of the GL document
        rate = rate_on(self.s.conn, self.s.company_id, currency_id, day)
        return rate.per_unit if rate else None

    def _date_changed(self, *_) -> None:
        if not self.model.read_only:
            self.model.refresh_rates()

    def _changed(self, *_) -> None:
        if not self.model.read_only:
            self.dirty = True
        self._update_totals()

    def _update_totals(self) -> None:
        debit, credit = self.model.totals()
        self.total_debit.setText(money(debit, False))
        self.total_credit.setText(money(credit, False))
        self.difference.setText(money(abs(debit - credit), False))
        differs = debit != credit
        for widget in (self.difference_title, self.difference):
            widget.setVisible(differs)
        self.btn_difference.setVisible(differs and not self.model.read_only)

    def refresh(self) -> None:
        if self.dirty:
            return
        marker = opening_document(self.s.conn, self.s.company_id)
        if marker is None:
            self.doc_id = None
            self.doc_status = None
            self._set_rows([])
            self.status.set(tr("Новый"), "blue")
            self.header.subtitle.setText(tr("Сальдо до первой операции"))
            self._set_read_only(False, posted=False)
            self._update_totals()
            return
        doc = load_document(self.s.conn, self.s.company_id, marker.document_id)
        self.doc_id = doc.id
        self.doc_status = doc.status
        self.date.blockSignals(True)
        self.date.setDate(to_qdate(date.fromisoformat(marker.effective_date)))
        self.date.blockSignals(False)
        self._set_rows([self.model.row_from(p) for p in doc.postings])
        if doc.status == "draft":
            self.status.set(tr("Черновик"), "amber")
        else:
            self.status.set(tr("Проведён"), "green")
        self.header.subtitle.setText(
            tr(
                "Документ №{n} · остатки на {date}",
                n=doc.number,
                date=ru_date(marker.effective_date),
            )
        )
        self._set_read_only(not doc.editable, posted=doc.status == "posted")
        self.dirty = False
        self._update_totals()

    def _set_rows(self, rows: list[OpeningRow]) -> None:
        self.model.beginResetModel()
        self.model.rows = list(rows) or [self.model._blank()]
        self.model.endResetModel()

    def _set_read_only(self, read_only: bool, posted: bool) -> None:
        self.date.setEnabled(not read_only)
        self.model.read_only = read_only
        self.btn_save.setVisible(not read_only and not posted)
        self.btn_post.setVisible(not read_only)

    def show_error(self, message: str) -> None:
        self.error.setText(message)
        self.error.show()

    def _finish_editing(self) -> None:
        editor = QApplication.focusWidget()
        if self.table.state() == QAbstractItemView.State.EditingState and editor is not None:
            self.table.commitData(editor)
            self.table.closeEditor(editor, QAbstractItemDelegate.EndEditHint.NoHint)

    def _edit(self, row: int, column: int) -> None:
        index = self.model.index(row, column)
        self.table.setCurrentIndex(index)
        self.table.edit(index)

    def _insert_row(self) -> None:
        if self.model.read_only:
            return
        self._finish_editing()
        current = self.table.currentIndex()
        self._edit(self.model.insert_row(current.row() + 1 if current.isValid() else None), DT)

    def _duplicate_row(self) -> None:
        current = self.table.currentIndex()
        if self.model.read_only or not current.isValid():
            return
        self._finish_editing()
        row = self.model.duplicate_row(current.row())
        self.table.setCurrentIndex(self.model.index(row, current.column()))

    def _remove_row(self) -> None:
        current = self.table.currentIndex()
        if self.model.read_only or not current.isValid():
            return
        self.model.remove_row(current.row())
        row = min(current.row(), self.model.rowCount() - 1)
        self.table.setCurrentIndex(self.model.index(row, current.column()))

    def close_difference(self) -> None:
        """A line on the side that makes the totals agree; the account is the user's choice
        (the retained earnings account is offered when the chart has exactly one)."""
        if self.model.read_only:
            return
        self._finish_editing()
        debit, credit = self.model.totals()
        if debit == credit:
            return
        retained = [
            a.id for a in self.s.catalog.leaf_accounts if a.account_type == "retained_earnings"
        ]
        line = OpeningRow(
            debit=retained[0] if len(retained) == 1 else None,
            credit=self.control_account,
            amount=abs(debit - credit),
            memo=tr("Разница начальных остатков"),
            on_credit=debit > credit,
        )
        if self.model.rows[-1].is_empty():
            self.model.remove_row(len(self.model.rows) - 1)
        self._edit(self.model.insert_row(None, line), DT)

    def paste(self) -> None:
        if self.model.read_only:
            return
        text = QApplication.clipboard().text()
        if not text.strip():
            return
        current = self.table.currentIndex()
        row, column = (current.row(), current.column()) if current.isValid() else (0, DT)
        result = self.model.paste(text, row, column, lambda c: not self.table.isColumnHidden(c))
        problems = result.errors + [
            tr("нет в справочнике «{kind}»: {text}", kind=self.s.catalog.kinds[k], text=t)
            for _, _, k, t in result.unknown
        ]
        if problems:
            self.show_error("\n".join(problems[:6]))
        self.s.notify(tr("Вставлено строк: {n}", n=result.rows))

    def copy(self) -> None:
        QApplication.clipboard().setText(
            self.model.copy_text(lambda column: not self.table.isColumnHidden(column))
        )
        self.s.notify(tr("Проводки скопированы — их можно вставить в Excel"))

    def _offer_new_value(self, index: QPersistentModelIndex, kind_id: int, text: str) -> None:
        QTimer.singleShot(0, lambda: self._create_value(index, kind_id, text))

    def _create_value(self, index: QPersistentModelIndex, kind_id: int, text: str) -> None:
        kind = self.s.catalog.kinds[kind_id]
        answer = QMessageBox.question(
            self,
            tr("Новый элемент справочника"),
            tr("«{text}» нет в справочнике «{kind}». Добавить?", text=text, kind=kind),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if not index.isValid():
            return
        if answer != QMessageBox.StandardButton.Yes:
            self.table.edit_again(index, text)  # the name, to correct it
            return
        owner = self.model.owner_at(index.row(), index.column())
        value_id = self._add_value(kind_id, text, owner)
        self.model.setData(self.model.index(index.row(), index.column()), value_id)
        self.table.edit_next(index)

    def _add_value(self, kind_id: int, text: str, owner_id: int | None) -> int:
        value_id = self.s.ledger.add_subconto_value(
            self.s.company_id, kind_id, text, owner_id=owner_id
        )
        self.s.catalog.add_value(value_id, kind_id, text, owner_id=owner_id)
        kind = self.s.catalog.kinds[kind_id]
        self.s.notify(tr("Добавлено в «{kind}»: {text}", kind=kind, text=text))
        return value_id

    def save(self, post: bool) -> bool:
        if self.model.read_only:
            return False
        self._finish_editing()
        self.error.hide()
        try:
            post = post or self.doc_status == "posted"
            effective = edited_date(self.date)
            doc_id = self.s.ledger.save_opening_balances(
                self.s.company_id,
                effective,
                self.model.to_inputs(),
                post=post,
                memo=tr("Начальные остатки на {date}", date=ru_date(effective.isoformat())),
            )
        except (LedgerError, ValueError) as error:
            self.show_error(str(error))
            return False
        debit, credit = self.model.totals()
        self.s.working_date = effective
        self.dirty = False
        self.refresh()
        if debit != credit:
            message = tr(
                "Сохранено. Разница {amount} осталась на счёте {code}",
                amount=money(abs(debit - credit), False),
                code=self.s.catalog.accounts[self.control_account].short,
            )
        elif post:
            message = tr("Начальные остатки проведены")
        else:
            message = tr("Черновик начальных остатков сохранён")
        self.s.notify(message)
        self.saved.emit(doc_id)
        return True
