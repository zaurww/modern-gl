"""The page of a «Расходы по партии» document."""

from __future__ import annotations

from datetime import date
from fractions import Fraction

from PySide6.QtCore import (
    Qt,
)
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QDialog,
    QMessageBox,
)

from modern_gl.application.currencies import rate_on
from modern_gl.desktop.landed_cost_page.columns import (
    ACCOUNT,
    AMOUNT,
    COST,
    COST_TYPE,
    CURRENCY_AMOUNT,
    DOCUMENT,
    ITEM,
    MEMO,
    QUANTITY,
    RATE,
    SC1,
    SC2,
    SC3,
    SHARE,
    UNIT_COST,
    VAT,
    WAREHOUSE,
    ChargeRow,
    TargetRow,
)
from modern_gl.desktop.landed_cost_page.form import LandedCostForm
from modern_gl.desktop.landed_cost_page.models import ChargesModel, TargetsModel
from modern_gl.desktop.landed_cost_page.pickers import (
    BatchCostDialog,
    cost_source_picker,
    receipt_picker,
    source_label,
)
from modern_gl.desktop.session import Session
from modern_gl.desktop.widgets import (
    edited_date,
    enter_goes_on,
    money,
    to_qdate,
)
from modern_gl.domain.currency import unit_rate
from modern_gl.domain.errors import LedgerError, ValidationError
from modern_gl.i18n import tr
from modern_gl.reporting.inventory import (
    cost_sources,
    receipt_line_choices,
)


class LandedCostPage(LandedCostForm):
    def __init__(self, session: Session, document_id: int | None = None) -> None:
        super().__init__(session)
        self.delegate.error.connect(self.show_error)
        self.delegate.add_value = self._add_value
        self._connect()

        self._set_models([], [], read_only=False)
        if document_id is None:
            self.number.setText(tr("Новый"))
            self.status.set(tr("Новый"), "blue")
            self._apply_mode(False)
        else:
            self.load(document_id)

    def _connect(self) -> None:
        self.btn_save.clicked.connect(lambda: self.save(post=False))
        self.btn_post.clicked.connect(lambda: self.save(post=True))
        self.btn_delete.clicked.connect(self.delete)
        self.btn_unpost.clicked.connect(self.unpost)
        self.btn_gl.clicked.connect(self._open_gl)
        self.btn_report.clicked.connect(self.show_report)
        self.btn_add_charge.clicked.connect(self.add_charge)
        self.btn_from_gl.clicked.connect(self.add_from_gl)
        self.btn_add_receipts.clicked.connect(self.add_receipts)
        self.memo.textEdited.connect(self._changed)
        self.date.dateChanged.connect(self._date_changed)
        self.method.activated.connect(self._changed)
        for keys, callback in (
            ("Ctrl+S", lambda: self.save(post=False)),
            ("Ctrl+Return", lambda: self.save(post=True)),
            ("Ctrl+Enter", lambda: self.save(post=True)),
        ):
            QShortcut(QKeySequence(keys), self).activated.connect(callback)
        for table in (self.charges_table, self.targets_table):
            for keys, callback in (("Ins", self.add_charge), ("Del", self._remove_row)):
                shortcut = QShortcut(QKeySequence(keys), table)
                shortcut.setContext(Qt.ShortcutContext.WidgetShortcut)
                shortcut.activated.connect(callback)

    # ---- page protocol -----------------------------------------------------------------

    @property
    def document_id(self) -> int | None:
        return self.doc.id if self.doc else None

    @property
    def key(self):
        return ("inventory_doc", self.document_id) if self.doc else ("new_inventory", id(self))

    def title(self) -> str:
        operation = tr("Дополнительные расходы")
        title = (
            f"{operation} №{self.doc.number}" if self.doc else tr("Новое: {type}", type=operation)
        )
        return title + (" •" if self.dirty else "")

    def is_dirty(self) -> bool:
        return self.dirty

    def focus_table(self) -> None:
        self.charges_table.setFocus()

    # ---- editing -----------------------------------------------------------------------

    def _set_models(
        self, charges: list[ChargeRow], targets: list[TargetRow], read_only: bool
    ) -> None:
        self.charges = ChargesModel(self.s, charges, read_only, self._rate_of)
        self.targets = TargetsModel(targets, read_only)
        self.charges_table.setModel(self.charges)
        self.targets_table.setModel(self.targets)
        self.charges_table.set_widths(
            {
                COST_TYPE: 130,
                ACCOUNT: 150,
                SC1: 130,
                SC2: 120,
                SC3: 110,
                CURRENCY_AMOUNT: 110,
                RATE: 80,
                AMOUNT: 100,
                VAT: 90,
            },
            MEMO,
        )
        used = self.s.catalog.used_positions()
        for key in (SC2, SC3):
            column = self.charges.columns.index(key)
            self.charges_table.setColumnHidden(column, int(key[-1]) not in used)
        self.targets_table.set_widths(
            {DOCUMENT: 140, WAREHOUSE: 130, QUANTITY: 110, COST: 110, SHARE: 110, UNIT_COST: 130},
            ITEM,
        )
        self.charges.changed.connect(self._changed)
        self.targets.changed.connect(self._changed)
        self._show_currency_columns()
        self._recalculate()

    def _recalculate(self) -> None:
        method = str(self.method.currentData())
        self.targets.preview(method, self.charges.total())
        total, allocated = self.charges.total(), self.targets.allocated()
        self.totals["total"].setText(money(total, blank_zero=False))
        self.totals["vat"].setText(money(self.charges.vat_total(), blank_zero=False))
        self.totals["allocated"].setText(money(allocated, blank_zero=False))
        off = allocated != total and method == "manual"
        self.totals["allocated"].setObjectName("error" if off else "")
        self.totals["allocated"].style().polish(self.totals["allocated"])
        for key in ("vat", "allocated"):
            shown = key != "vat" or bool(self.charges.vat_total())
            self.totals[key].setVisible(shown)
            self.totals[f"{key}_caption"].setVisible(shown)

    def _rate_of(self, currency_id: int) -> Fraction | None:
        found = rate_on(self.s.conn, self.s.company_id, currency_id, edited_date(self.date))
        return found.per_unit if found else None

    def _date_changed(self, *_args) -> None:
        self.charges.refresh_rates()  # also marks the page changed

    def _show_currency_columns(self) -> None:
        shown = self.charges.has_currency()
        for key in (CURRENCY_AMOUNT, RATE):
            self.charges_table.setColumnHidden(self.charges.columns.index(key), not shown)

    def _changed(self, *_args) -> None:
        self._show_currency_columns()
        self._recalculate()
        if not self.charges.read_only and not self.dirty:
            self.dirty = True
            self.title_changed.emit()

    def add_charge(self) -> None:
        if self.charges.read_only:
            return
        row = self.charges.insert_row()
        self.charges_table.setFocus()
        self.charges_table.setCurrentIndex(self.charges.index(row, 0))

    def add_from_gl(self) -> None:
        if self.charges.read_only:
            return
        dialog = cost_source_picker(self.s, self.document_id, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        taken = {charge.source for charge in self.charges.rows}
        for source in dialog.chosen():
            if (source.document_id, source.line_no) in taken:
                continue
            self.charges.insert_row(
                ChargeRow(
                    account_id=source.debit_account_id,
                    subconto=list(source.debit_subconto),
                    amount=source.left,
                    source=(source.document_id, source.line_no),
                    source_label=source_label(source),
                )
            )

    def add_receipts(self) -> None:
        if self.targets.read_only:
            return
        dialog = receipt_picker(self.s, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.targets.add(dialog.chosen())

    def _remove_row(self) -> None:
        self._finish_editing()
        if self.charges_table.hasFocus():
            current = self.charges_table.currentIndex()
            if current.isValid() and not self.charges.read_only:
                self.charges.remove_row(current.row())
        elif self.targets_table.hasFocus():
            current = self.targets_table.currentIndex()
            if current.isValid() and not self.targets.read_only:
                self.targets.remove_row(current.row())

    def _add_value(self, kind_id: int, text: str, owner_id: int | None) -> int:
        value_id = self.s.ledger.add_subconto_value(
            self.s.company_id, kind_id, text, owner_id=owner_id
        )
        self.s.catalog.add_value(value_id, kind_id, text, owner_id=owner_id)
        kind = self.s.catalog.kinds[kind_id]
        self.s.notify(tr("Добавлено в «{kind}»: {text}", kind=kind, text=text))
        return value_id

    def keyPressEvent(self, event) -> None:
        """Enter in the title, date or method goes on as Tab does."""
        if not enter_goes_on(self, event):
            super().keyPressEvent(event)

    # ---- storage -----------------------------------------------------------------------

    def load(self, document_id: int) -> None:
        self.doc = self.inventory.load_document(self.s.company_id, document_id)
        self.number.setText(f"№{self.doc.number}")
        self.memo.setText(self.doc.memo)
        self.date.setDate(to_qdate(date.fromisoformat(self.doc.doc_date)))
        self.method.setCurrentIndex(max(self.method.findData(self.doc.allocation_method), 0))
        receipts = {r.id: r for r in receipt_line_choices(self.s.conn, self.s.company_id)}
        sources = {
            (c.document_id, c.line_no): c
            for c in cost_sources(self.s.conn, self.s.company_id, self.doc.id, only_left=False)
        }
        charges = [
            ChargeRow(
                charge.cost_type_id,
                charge.account_id,
                list(charge.subconto),
                charge.amount or None,
                charge.vat_amount or None,
                None
                if charge.source_document_id is None
                else (charge.source_document_id, charge.source_line_no or 0),
                self._source_label(charge.source_document_id, charge.source_line_no, sources),
                charge.memo,
                charge.currency_id,
                next(
                    (
                        c.code
                        for c in self.s.catalog.active_currencies
                        if c.id == charge.currency_id
                    ),
                    "",
                ),
                charge.currency_amount,
                None if charge.currency_rate is None else unit_rate(charge.currency_rate),
                rate_typed=True,  # the saved rate stays as it was
            )
            for charge in self.doc.charges
        ]
        manual = self.doc.allocation_method == "manual"
        targets = [
            TargetRow(
                receipts[line.source_receipt_line_id],
                line.amount if manual else None,
                line.id,
            )
            for line in self.doc.lines
            if line.source_receipt_line_id in receipts
        ]
        read_only = not self.doc.editable
        self._set_models(charges, targets, read_only)
        if self.doc.status == "posted":
            self.status.set(tr("Проведён"), "green")
        else:
            self.status.set(tr("Черновик"), "amber")
        self._apply_mode(read_only)
        self.dirty = False
        self.title_changed.emit()

    @staticmethod
    def _source_label(document_id, line_no, sources) -> str:
        source = sources.get((document_id, line_no)) if document_id is not None else None
        return source_label(source) if source is not None else ""

    def _apply_mode(self, read_only: bool) -> None:
        posted = self.doc is not None and self.doc.status == "posted"
        for widget in (self.memo, self.date, self.method):
            widget.setEnabled(not read_only)
        for control in (self.btn_add_charge, self.btn_from_gl, self.btn_add_receipts):
            control.setVisible(not read_only)
        self.btn_save.setVisible(not read_only and not posted)
        self.btn_post.setVisible(not read_only)
        self.btn_delete.setVisible(self.doc is not None)
        self.btn_unpost.setVisible(posted and not read_only)
        self.btn_gl.setVisible(self.doc is not None and self.doc.gl_document_id is not None)
        self.btn_report.setVisible(posted)  # the shares exist once it is posted
        self.hint.setVisible(not read_only)

    def save(self, post: bool) -> bool:
        if self.charges.read_only:
            return False
        self._finish_editing()
        self.error.hide()
        try:
            targets, charges = self.targets.to_inputs(), self.charges.to_inputs()
            if not targets:
                raise ValidationError(tr("Добавьте поступления партии"))
            if self.doc is not None and self.doc.status == "posted":
                post = True
                with self.inventory.reposting(self.s.company_id, self.doc.id):
                    document_id = self._save_draft(targets, charges)
            else:
                document_id = self._save_draft(targets, charges)
                if post:
                    self.inventory.post_document(self.s.company_id, document_id)
        except (LedgerError, ValueError, TypeError) as exc:
            self.show_error(str(exc))
            return False
        self.s.working_date = edited_date(self.date)
        self.load(document_id)
        assert self.doc is not None
        self.s.notify(
            tr(
                "Складской документ №{n} проведён" if post else "Складской документ №{n} сохранён",
                n=self.doc.number,
            )
        )
        self.saved.emit(document_id)
        return True

    def _save_draft(self, targets, charges) -> int:
        method = str(self.method.currentData())
        when = edited_date(self.date)
        memo = self.memo.text().strip()
        if self.doc is None:
            return self.inventory.create_landed_cost_draft(
                self.s.company_id, when, targets, charges, method, memo
            )
        self.inventory.update_landed_cost_draft(
            self.s.company_id, self.doc.id, when, targets, charges, method, memo
        )
        return self.doc.id

    def delete(self) -> None:
        if self.doc is None:
            return
        if (
            QMessageBox.question(
                self,
                tr("Удалить складской документ"),
                tr("Удалить складской документ №{n}?", n=self.doc.number),
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        number = self.doc.number
        try:
            self.inventory.delete_document(self.s.company_id, self.doc.id)
        except LedgerError as exc:
            self.show_error(str(exc))
            return
        self.dirty = False
        self.s.notify(tr("Складской документ №{n} удалён", n=number))
        self.saved.emit(self.doc.id)
        self.close_requested.emit()

    def unpost(self) -> None:
        if self.doc is None:
            return
        try:
            self.inventory.unpost_document(self.s.company_id, self.doc.id)
        except LedgerError as exc:
            self.show_error(str(exc))
            return
        self.load(self.doc.id)
        self.s.notify(
            tr(
                "Проведение складского документа №{n} отменено — можно исправлять",
                n=self.doc.number,
            )
        )
        self.saved.emit(self.doc.id)

    def show_report(self) -> None:
        if self.doc is None or self.doc.status != "posted":
            return
        title = f"{self.title().rstrip(' •')}  ·  {self.doc.memo}".rstrip(" ·")
        BatchCostDialog(self.s, self.doc.id, title, self).exec()

    def _open_gl(self) -> None:
        if self.doc is not None and self.doc.gl_document_id is not None:
            self.open_gl_document.emit(self.doc.gl_document_id)
