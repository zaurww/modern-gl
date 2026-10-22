"""Currency conversion (D37): two bank accounts side by side — what left one, what came to
the other — and under them the Central Bank's rate, the bank's rate and the difference."""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from itertools import pairwise

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QMessageBox,
    QWidget,
)

from modern_gl.application.conversions import (
    ConversionInput,
    bank_rate,
    calculate,
    load_conversion,
    official_rate,
)
from modern_gl.application.currencies import rate_on
from modern_gl.application.ledger.conversion import MissingAccountRole
from modern_gl.application.queries import load_document
from modern_gl.desktop.conversion_page.accounts_dialog import ConversionAccountsDialog
from modern_gl.desktop.conversion_page.common import (
    BASE,
    NONE,
    money_accounts,
)
from modern_gl.desktop.conversion_page.fee_row import FeeRow
from modern_gl.desktop.conversion_page.form import ConversionForm
from modern_gl.desktop.session import Session
from modern_gl.desktop.theme import P
from modern_gl.desktop.widgets import (
    MenuItem,
    edited_date,
    enter_goes_on,
    ru_date,
    to_qdate,
)
from modern_gl.domain.currency import format_unit_rate
from modern_gl.domain.errors import LedgerError
from modern_gl.domain.money import format_minor
from modern_gl.i18n import tr


class ConversionPage(ConversionForm):
    def __init__(
        self,
        session: Session,
        conversion_id: int | None = None,
        prefill: ConversionInput | None = None,
    ) -> None:
        super().__init__(session)
        self._connect()
        if conversion_id is not None:
            self.load(conversion_id)
        else:
            self._set_new(prefill)
        self._chain()

    def _connect(self) -> None:
        self.btn_rates.clicked.connect(self.load_rates)
        self.btn_add_fee.clicked.connect(lambda: self.add_fee(focus=True))
        self.btn_save.clicked.connect(lambda: self.save(post=False))
        self.btn_post.clicked.connect(lambda: self.save(post=True))
        self.btn_delete.clicked.connect(self.delete)
        self.btn_unpost.clicked.connect(self.unpost)
        self.btn_gl.clicked.connect(self._open_gl)
        for keys, fn in (
            ("Ctrl+S", lambda: self.save(post=self.posted)),
            ("Ctrl+Return", lambda: self.save(post=True)),
            ("Ctrl+Enter", lambda: self.save(post=True)),
            ("Ins", lambda: self.add_fee(focus=True)),
            ("Ctrl+Del", self._remove_current_fee),
        ):
            shortcut = QShortcut(QKeySequence(keys), self)
            shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            shortcut.activated.connect(fn)
        self.btn_add_fee.setToolTip(tr("Комиссия, которую удержал банк") + " (Ins)")
        for panel in (self.source, self.target):
            panel.changed.connect(self._changed)
        self.memo.textEdited.connect(self._changed)
        self.date.dateChanged.connect(self._date_changed)

    # ---- state -----------------------------------------------------------------------

    @property
    def key(self):
        return ("conversion", self.doc.id) if self.doc else ("new_conversion", id(self))

    def title(self) -> str:
        title = tr("Конвертация №{n}", n=self.doc.number) if self.doc else tr("Новая конвертация")
        return title + (" •" if self.dirty else "")

    def is_dirty(self) -> bool:
        return self.dirty

    def focus_table(self) -> None:
        self.source.amount.setFocus()

    def _set_new(self, prefill: ConversionInput | None) -> None:
        self._loading = True
        if prefill is not None:
            self._fill(prefill)
        else:
            # the usual case: currency sold from a currency account to a manat one
            accounts = money_accounts(self.s)
            banks = sorted(accounts, key=lambda a: a.account_type != "bank")  # cash last
            foreign = next((a for a in banks if a.currency), None)
            local = next((a for a in banks if not a.currency), None)
            for panel, account in ((self.source, foreign), (self.target, local)):
                if account is not None:
                    panel.account.setCurrentIndex(panel.account.findData(account.id))
                    panel._account_changed()
        self.number.setText("")
        self.status.set(tr("Новый"), "blue")
        self._loading = False
        self.dirty = prefill is not None
        self._apply_mode()
        self._update_summary()
        QTimer.singleShot(0, self.source.amount.setFocus)

    def load(self, conversion_id: int) -> None:
        self.doc = load_conversion(self.s.conn, self.s.company_id, conversion_id)
        d = self.doc
        self._loading = True
        self._fill(d)
        self._loading = False
        self.number.setText(f"№{d.number}")
        closed = load_document(self.s.conn, self.s.company_id, d.document_id).closed
        self.read_only = (d.status == "posted" and closed) or self.s.read_only  # viewing (D80)
        if d.status == "draft":
            self.status.set(tr("Черновик"), "amber")
        else:
            self.status.set(tr("Проведён"), "green")
        self.dirty = False
        self._apply_mode()
        self._update_summary()
        self.title_changed.emit()

    def _fill(self, d: ConversionInput) -> None:
        self.memo.setText(d.memo)
        self.date.setDate(to_qdate(date.fromisoformat(d.doc_date)))
        self.source.set_value(d.source)
        self.target.set_value(d.target)
        self.target.date.setDate(to_qdate(date.fromisoformat(d.target_date or d.doc_date)))
        for row in list(self.fee_rows):
            self._remove_fee(row)
        for fee in d.fees:
            self.add_fee().set_value(fee)

    def _apply_mode(self) -> None:
        ro = self.read_only
        self.date.setEnabled(not ro)
        self.memo.setReadOnly(ro)
        self.btn_add_fee.setVisible(not ro)
        for row in self.fee_rows:
            row.set_read_only(ro)
        self.source.set_read_only(ro)
        self.target.set_read_only(ro)
        self.btn_delete.setVisible(self.doc is not None and not ro)
        self.btn_unpost.setVisible(self.posted and not ro)
        self.btn_gl.setVisible(self.posted)
        self.btn_save.setVisible(not ro and not self.posted)  # Ctrl+S reposts it
        self.btn_post.setVisible(not ro)

    def menu_items(self) -> list[MenuItem]:
        if self.s.read_only:  # viewing (D80)
            return []
        items: list[MenuItem] = [(tr("Счета конвертации…"), self.edit_accounts)]
        if self.doc is not None:
            items.append((tr("Копировать"), self._copy))
        return items

    def edit_accounts(self, missing: str | None = None) -> bool:
        dialog = ConversionAccountsDialog(self.s, self, missing)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return False
        self.error.hide()
        return True

    def _copy(self) -> None:
        try:
            data = self.collect()
        except (LedgerError, ValueError) as e:
            self.show_error(str(e))
            return
        self.copy_requested.emit(self.copy_of(data))

    @staticmethod
    def copy_of(data: ConversionInput) -> ConversionInput:
        """A new conversion like this one; the bank references belong to the original."""
        source, target = (
            None if side is None else replace(side, reference="")
            for side in (data.source, data.target)
        )
        return ConversionInput(
            data.doc_date,
            source,
            target,
            data.target_date,
            data.fees,
            data.memo,
        )

    def add_fee(self, focus: bool = False) -> FeeRow:
        """A new fee line; it is taken from the account sold from, until changed."""
        row = FeeRow(self.s)
        source = self.source.value()
        if source is not None:
            row.set_place(source.account_id, source.subconto)
        row.changed.connect(self._changed)
        row.removed.connect(self._remove_fee)
        self.fee_rows.append(row)
        self.fees_box.addWidget(row)
        self._chain()
        if focus and not self.read_only:
            row.amount.setFocus()
        return row

    def _remove_fee(self, row: FeeRow) -> None:
        self.fee_rows.remove(row)
        self.fees_box.removeWidget(row)
        row.hide()  # out of the Enter / Tab order at once
        row.deleteLater()
        self._changed()

    def _remove_current_fee(self) -> None:
        """Ctrl+Del: the fee the cursor is in goes; the cursor to the one above it."""
        focused = QApplication.focusWidget()
        row = next((r for r in self.fee_rows if focused and r.isAncestorOf(focused)), None)
        if row is None or self.read_only:
            return
        at = self.fee_rows.index(row)
        self._remove_fee(row)
        if self.fee_rows:
            self.fee_rows[max(at - 1, 0)].amount.setFocus()

    def _chain(self) -> None:
        """Enter and Tab go in the order things are typed: the title, the side sold from,
        the side bought to, then the fees (made later than the buttons below them, so
        Qt's own order would put them last)."""
        fields: list[QWidget] = [self.memo]
        for panel in (self.source, self.target):
            fields += [panel.account, *panel.sc, panel.currency, panel.amount]
            fields += [panel.date, panel.reference]
        for row in self.fee_rows:
            fields += [row.amount, row.currency, row.place, row.expense]
        fields.append(self.btn_post)
        for first, second in pairwise(fields):
            QWidget.setTabOrder(first, second)

    def keyPressEvent(self, event) -> None:
        """Enter goes on to the next field, as Tab does (as in the journal)."""
        if not enter_goes_on(self, event):
            super().keyPressEvent(event)

    def _changed(self, *_) -> None:
        if self._loading:
            return
        self.error.hide()
        self._update_summary()
        if not self.dirty and not self.read_only:
            self.dirty = True
            self.title_changed.emit()

    def _date_changed(self, *_) -> None:
        # the credit usually comes the same day: it follows until set apart
        day, credit = self.date.date(), self.target.date.date()
        if not self._loading and (credit == self._last_date or credit < day):
            self.target.date.setDate(day)
        self._last_date = day
        self._changed()

    # ---- input and summary -------------------------------------------------------------

    def collect(self) -> ConversionInput:
        doc_date = edited_date(self.date).isoformat()
        target_date = edited_date(self.target.date).isoformat()
        source, target = self.source.value(), self.target.value()
        memo = self.memo.text().strip()
        if not memo and source is not None and target is not None:
            memo = tr(
                "Конвертация {source} → {target}",
                source=self.source.code(),
                target=self.target.code(),
            )
        return ConversionInput(
            doc_date=doc_date,
            source=source,
            target=target,
            target_date=None if target_date == doc_date else target_date,
            fees=tuple(f for row in self.fee_rows if (f := row.value()) is not None),
            memo=memo,
        )

    def _update_summary(self) -> None:
        try:
            data = self.collect()
        except ValueError:
            for stat in (self.cbar, self.bank, self.difference, self.fee_value):
                stat.set(NONE)
            return
        base = BASE
        calc = calculate(self.s.conn, self.s.company_id, data)
        src, tgt = self.source.code(), self.target.code()
        # quoted as the bank does: the foreign currency (the source of a cross) per unit
        unit, quote = (tgt, src) if data.source and data.source.currency_id is None else (src, tgt)
        cbar = official_rate(data, calc.rates)
        self.cbar.set(f"1 {unit} = {format_unit_rate(cbar)} {quote}" if cbar else NONE)
        rate = bank_rate(data)
        self.bank.set(f"1 {unit} = {format_unit_rate(rate)} {quote}" if rate else NONE)
        diff = calc.difference
        if diff is None or calc.missing:
            self.difference.set(NONE)
        elif diff == 0:
            self.difference.set("0.00")
        elif diff > 0:
            self.difference.set(tr("{amount} убыток", amount=format_minor(diff)), P.red)
        else:
            self.difference.set(tr("{amount} доход", amount=format_minor(-diff)), P.green)
        self.fee_value.caption.setText(tr("Комиссии, {code}", code=base))
        self.fee_value.set(format_minor(calc.fee_total) if calc.fee_total else NONE)
        self._update_rate_note(data)

    def _update_rate_note(self, data: ConversionInput) -> None:
        """Currencies without a rate set for the date itself: offer the official ones."""
        if self.read_only or self.posted:
            self.rate_note.hide()
            return
        day = data.doc_date
        parts = []
        for side in (data.source, data.target):
            if side is None or side.currency_id is None:
                continue
            code = self.s.catalog.currencies[side.currency_id].code
            rate = rate_on(self.s.conn, self.s.company_id, side.currency_id, day)
            if rate is None:
                parts.append(tr("нет курса {code}", code=code))
            elif rate.rate_date < day:
                parts.append(tr("курс {code} от {old}", code=code, old=ru_date(rate.rate_date)))
        if not parts:
            self.rate_note.hide()
            return
        self.rate_text.setText(
            tr("На {date} курс не загружен: {what}", date=ru_date(day), what=", ".join(parts))
        )
        self.rate_note.show()

    def load_rates(self) -> None:
        day = edited_date(self.date)
        QGuiApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            count = self.s.ledger.import_rates(self.s.company_id, day, self.s.fetch_rates(day))
        except LedgerError as e:
            self.show_error(str(e))
            return
        finally:
            QGuiApplication.restoreOverrideCursor()
        self._update_summary()
        self.s.notify(
            tr("Курсы ЦБА на {date} загружены: {n}", date=ru_date(day.isoformat()), n=count)
        )

    # ---- actions ---------------------------------------------------------------------

    def save(self, post: bool) -> bool:
        if self.read_only:
            return False
        self.error.hide()
        try:
            data = self.collect()
            conversion_id = self.s.ledger.save_conversion(
                self.s.company_id, data, self.doc.id if self.doc else None, post=post
            )
        except MissingAccountRole as e:
            # a chart without the accounts: choose them now and post again
            chosen = self.edit_accounts(missing=e.role)
            if chosen and self.s.ledger.account_role(self.s.company_id, e.role) is not None:
                return self.save(post)
            self.show_error(str(e))
            return False
        except (LedgerError, ValueError) as e:
            self.show_error(str(e))
            return False
        self.s.catalog.reload()  # items of the difference and the fee may be new
        self.load(conversion_id)
        assert self.doc is not None
        self.s.notify(
            tr("Конвертация №{n} проведена", n=self.doc.number)
            if post
            else tr("Черновик №{n} сохранён", n=self.doc.number)
        )
        self.saved.emit(self.doc.document_id)
        return True

    def unpost(self) -> None:
        if self.doc is None:
            return
        try:
            self.s.ledger.unpost_conversion(self.s.company_id, self.doc.id)
        except LedgerError as e:
            self.show_error(str(e))
            return
        self.load(self.doc.id)
        self.saved.emit(self.doc.document_id)

    def delete(self) -> None:
        if self.doc is None:
            return
        question = tr("Удалить конвертацию №{n}?", n=self.doc.number)
        if QMessageBox.question(self, tr("Удалить"), question) != QMessageBox.StandardButton.Yes:
            return
        try:
            self.s.ledger.delete_conversion(self.s.company_id, self.doc.id)
        except LedgerError as e:
            self.show_error(str(e))
            return
        self.saved.emit(self.doc.document_id)
        self.dirty = False
        self.close_requested.emit()

    def _open_gl(self) -> None:
        if self.doc is not None:
            self.open_gl_document.emit(self.doc.document_id)
