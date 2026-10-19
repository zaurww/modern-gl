"""Currencies: the company's currencies, their rates, CBAR rates, revaluation.

Left: the currencies with their latest rate. Right: the rate history of the chosen one.
Rates of the Central Bank (cbar.az) are loaded for a day or a period; a rate can also be
typed by hand. Revaluation brings balances of currency accounts to the rate of a day.
"""

from __future__ import annotations

from datetime import date, timedelta

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QAction, QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QSpinBox,
    QStackedLayout,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from modern_gl.application.currencies import CurrencyInfo, Rate, latest_rates, list_rates
from modern_gl.desktop.reports_page import Column, ReportModel, month_of
from modern_gl.desktop.session import Session
from modern_gl.desktop.theme import fonts
from modern_gl.desktop.widgets import (
    EmptyState,
    PageHeader,
    button,
    date_edit,
    edited_date,
    ru_date,
)
from modern_gl.domain.currency import KNOWN, currency_name, format_rate, parse_rate
from modern_gl.domain.errors import LedgerError
from modern_gl.i18n import tr
from modern_gl.infrastructure import cbar

CURRENCY_ROLE = Qt.ItemDataRole.UserRole
MAX_DAYS = 92  # one request per day: a quarter at most


def _dialog(parent: QWidget, title: str) -> tuple[QDialog, QVBoxLayout, QFormLayout]:
    dlg = QDialog(parent)
    dlg.setWindowTitle(title)
    dlg.setMinimumWidth(420)
    lay = QVBoxLayout(dlg)
    lay.setContentsMargins(24, 20, 24, 16)
    lay.setSpacing(14)
    heading = QLabel(title)
    heading.setFont(fonts().heading)
    lay.addWidget(heading)
    form = QFormLayout()
    form.setHorizontalSpacing(16)
    form.setVerticalSpacing(10)
    lay.addLayout(form)
    return dlg, lay, form


def _buttons(dlg: QDialog, lay: QVBoxLayout) -> None:
    buttons = QDialogButtonBox(
        QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
    )
    buttons.accepted.connect(dlg.accept)
    buttons.rejected.connect(dlg.reject)
    lay.addWidget(buttons)


class CurrenciesPage(QWidget):
    key = ("currencies",)
    open_document = Signal(int)

    def __init__(self, session: Session) -> None:
        super().__init__()
        self.setObjectName("page")
        self.s = session
        self.fetch = cbar.fetch  # replaced in tests: no network there
        root = QVBoxLayout(self)
        root.setContentsMargins(40, 30, 40, 24)
        root.setSpacing(18)

        self.header = PageHeader(tr("Валюты"), "")
        for text, tip, fn in (
            (tr("+ Валюта"), tr("Добавить валюту"), self.add_currency),
            (
                tr("Переоценка…"),
                tr("Пересчитать остатки валютных счетов по курсу на дату"),
                self.revalue,
            ),
            (
                tr("Курсы ЦБА…"),
                tr("Загрузить официальные курсы Центрального банка (cbar.az)"),
                self.load_cbar,
            ),
        ):
            b = button(text, "flat", tip)
            b.clicked.connect(fn)
            self.header.add_action(b)
        root.addWidget(self.header)

        body = QHBoxLayout()
        body.setSpacing(28)
        self.currencies = QListWidget()
        self.currencies.setObjectName("nav")
        self.currencies.setFixedWidth(300)
        self.currencies.currentItemChanged.connect(lambda *_: self.refresh_rates())
        self.currencies.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.currencies.customContextMenuRequested.connect(self._currency_menu)
        body.addWidget(self.currencies)

        right = QVBoxLayout()
        right.setSpacing(10)
        top = QHBoxLayout()
        self.currency_title = QLabel()
        self.currency_title.setFont(fonts().heading)
        top.addWidget(self.currency_title, 1)
        add = button(tr("+ Курс"), "primary", "Ins")
        add.clicked.connect(self.add_rate)
        top.addWidget(add)
        right.addLayout(top)
        self.latest = QLabel()
        self.latest.setObjectName("secondary")
        right.addWidget(self.latest)

        self.model = ReportModel()
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setShowGrid(False)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(34)
        self.table.horizontalHeader().setHighlightSections(False)
        self.table.doubleClicked.connect(lambda idx: self.edit_rate(self._rate_at(idx)))
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._rate_menu)
        self.empty = EmptyState(
            "○",
            tr("Курсов пока нет"),
            tr("Загрузите курсы ЦБА или добавьте курс вручную (Ins)."),
        )
        self.stack = QStackedLayout()
        self.stack.addWidget(self.table)
        self.stack.addWidget(self.empty)
        right.addLayout(self.stack, 1)
        hint = QLabel(tr("Ins — новый курс   ·   двойной щелчок — изменить   ·   Del — удалить"))
        hint.setObjectName("tertiary")
        hint.setFont(fonts().small)
        right.addWidget(hint)
        body.addLayout(right, 1)
        root.addLayout(body, 1)

        for keys, fn in (
            ("Ins", self.add_rate),
            ("Del", lambda: self.delete_rate(self._rate_at(self.table.currentIndex()))),
        ):
            sc = QShortcut(QKeySequence(keys), self)
            sc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            sc.activated.connect(fn)
        self.refresh()

    def title(self) -> str:
        return tr("Валюты")

    def is_dirty(self) -> bool:
        return False

    def focus_table(self) -> None:
        self.table.setFocus()

    # ---- data ------------------------------------------------------------------------

    def currency(self) -> CurrencyInfo | None:
        item = self.currencies.currentItem()
        return self.s.catalog.currencies.get(item.data(CURRENCY_ROLE)) if item else None

    def refresh(self, select: int | None = None) -> None:
        cat = self.s.catalog
        shown = self.currency()
        current = select or (shown.id if shown else None)
        latest = latest_rates(self.s.conn, self.s.company_id)
        self.currencies.blockSignals(True)
        self.currencies.clear()
        for c in cat.currencies.values():
            rate = latest.get(c.id)
            text = f"{c.code}   {c.name}"
            if not c.active:
                text += f"  ·  {tr('скрыта')}"
            elif rate:
                text += f"   {format_rate(rate.rate, rate.nominal)}"
            item = QListWidgetItem(text)
            item.setData(CURRENCY_ROLE, c.id)
            item.setSizeHint(QSize(0, 34))
            if not c.active:
                item.setForeground(Qt.GlobalColor.gray)
            self.currencies.addItem(item)
            if c.id == current:
                self.currencies.setCurrentItem(item)
        if self.currencies.currentItem() is None and self.currencies.count():
            self.currencies.setCurrentRow(0)
        self.currencies.blockSignals(False)
        self.header.subtitle.setText(
            tr("{n} валют  ·  основная валюта — манат (AZN)", n=len(cat.currencies))
        )
        self.refresh_rates()

    def refresh_rates(self) -> None:
        c = self.currency()
        if c is None:
            self.currency_title.setText("")
            self.stack.setCurrentWidget(self.empty)
            return
        self.currency_title.setText(f"{c.code}  ·  {c.name}")
        rates = list_rates(self.s.conn, self.s.company_id, c.id)
        self.latest.setText(
            tr(
                "Последний курс: {rate} AZN за {nominal} {code} на {date}",
                rate=format_rate(rates[0].rate),
                nominal=rates[0].nominal,
                code=c.code,
                date=ru_date(rates[0].rate_date),
            )
            if rates
            else ""
        )
        columns = [
            Column(tr("Дата"), lambda r: ru_date(r.rate_date), width=120),
            Column(tr("Курс, AZN"), lambda r: format_rate(r.rate), width=140),
            Column(tr("За единиц"), lambda r: r.nominal, width=110),
            Column(
                tr("Источник"),
                lambda r: tr("ЦБА (cbar.az)") if r.source == "cbar" else tr("вручную"),
            ),
        ]
        self.model.set(columns, rates)
        self.stack.setCurrentWidget(self.table if rates else self.empty)
        hh = self.table.horizontalHeader()
        for i, col in enumerate(columns):
            if col.width:
                self.table.setColumnWidth(i, col.width)
            else:
                hh.setSectionResizeMode(i, QHeaderView.ResizeMode.Stretch)

    def _rate_at(self, index) -> Rate | None:
        return index.data(Qt.ItemDataRole.UserRole) if index.isValid() else None

    def _changed(self, message: str, select: int | None = None) -> None:
        self.s.catalog.reload()
        self.refresh(select)
        self.s.notify(message)

    # ---- currencies ------------------------------------------------------------------

    def add_currency(self) -> None:
        have = {c.code for c in self.s.catalog.currencies.values()}
        items = [f"{code}  {currency_name(code)}" for code in sorted(KNOWN) if code not in have]
        text, ok = QInputDialog.getItem(
            self,
            tr("Новая валюта"),
            tr("Валюта (или введите код из трёх букв):"),
            items,
            0,
            True,
        )
        if not ok or not text.strip():
            return
        code = text.split()[0]
        try:
            currency_id = self.s.ledger.add_currency(self.s.company_id, code)
        except LedgerError as e:
            self.s.notify(str(e))
            return
        self._changed(tr("Валюта {code} добавлена", code=code.upper()), currency_id)

    def toggle_currency(self, c: CurrencyInfo) -> None:
        self.s.ledger.set_currency_active(self.s.company_id, c.id, not c.active)
        self._changed(
            tr("{code} снова в списках", code=c.code)
            if not c.active
            else tr("{code} скрыта из списков ввода", code=c.code),
            c.id,
        )

    def _currency_menu(self, pos) -> None:
        item = self.currencies.itemAt(pos)
        c = self.s.catalog.currencies.get(item.data(CURRENCY_ROLE)) if item else None
        if c is None:
            return
        menu = QMenu(self)
        act = QAction(tr("Показать") if not c.active else tr("Скрыть"), menu)
        act.triggered.connect(lambda: self.toggle_currency(c))
        menu.addAction(act)
        menu.exec(self.currencies.viewport().mapToGlobal(pos))

    # ---- rates -----------------------------------------------------------------------

    def add_rate(self) -> None:
        c = self.currency()
        if c is not None:
            self._rate_dialog(c, None)

    def edit_rate(self, rate: Rate | None) -> None:
        c = self.currency()
        if c is not None and rate is not None:
            self._rate_dialog(c, rate)

    def _rate_dialog(self, c: CurrencyInfo, rate: Rate | None) -> None:
        dlg, lay, form = _dialog(self, tr("Курс {code}", code=c.code))
        day = date_edit(date.fromisoformat(rate.rate_date) if rate else self.s.working_date, dlg)
        day.setEnabled(rate is None)
        value = QLineEdit(format_rate(rate.rate) if rate else "")
        value.setPlaceholderText("1.7000")
        value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        nominal = QSpinBox()
        nominal.setRange(1, 1_000_000)
        nominal.setValue(rate.nominal if rate else 1)
        form.addRow(tr("Дата"), day)
        form.addRow(tr("Курс, AZN"), value)
        form.addRow(tr("За единиц"), nominal)
        error = QLabel()
        error.setObjectName("error")
        error.hide()
        lay.addWidget(error)
        _buttons(dlg, lay)
        while dlg.exec() == QDialog.DialogCode.Accepted:
            try:
                self.s.ledger.set_rate(
                    self.s.company_id,
                    c.id,
                    edited_date(day),
                    parse_rate(value.text()),
                    nominal.value(),
                )
            except (LedgerError, ValueError, TypeError) as e:
                error.setText(str(e))
                error.show()
                continue
            self._changed(tr("Курс {code} на {date} сохранён", code=c.code, date=day.text()), c.id)
            return

    def delete_rate(self, rate: Rate | None) -> None:
        c = self.currency()
        if c is None or rate is None:
            return
        question = tr("Удалить курс {code} на {date}?", code=c.code, date=ru_date(rate.rate_date))
        if QMessageBox.question(self, tr("Удалить"), question) != QMessageBox.StandardButton.Yes:
            return
        self.s.ledger.delete_rate(self.s.company_id, c.id, rate.rate_date)
        self._changed(tr("Курс {code} на {date} удалён", code=c.code, date=ru_date(rate.rate_date)))

    def _rate_menu(self, pos) -> None:
        rate = self._rate_at(self.table.indexAt(pos))
        if rate is None:
            return
        menu = QMenu(self)
        for text, fn in (
            (tr("Изменить…"), lambda: self.edit_rate(rate)),
            (tr("Удалить"), lambda: self.delete_rate(rate)),
        ):
            act = QAction(text, menu)
            act.triggered.connect(fn)
            menu.addAction(act)
        menu.exec(self.table.viewport().mapToGlobal(pos))

    # ---- CBAR ------------------------------------------------------------------------

    def load_cbar(self) -> None:
        dlg, lay, form = _dialog(self, tr("Курсы ЦБА"))
        start = date_edit(self.s.working_date, dlg)
        end = date_edit(self.s.working_date, dlg)
        form.addRow(tr("С"), start)
        form.addRow(tr("по"), end)
        note = QLabel(
            tr(
                "Официальные курсы Центрального банка Азербайджана (cbar.az) "
                "для валют компании. Нужен интернет."
            )
        )
        note.setObjectName("secondary")
        note.setWordWrap(True)
        lay.addWidget(note)
        _buttons(dlg, lay)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        self.load_rates(edited_date(start), edited_date(end))

    def load_rates(self, first: date, last: date) -> int:
        """Load CBAR rates for every day of the period; returns the days loaded."""
        if first > last:
            first, last = last, first
        if (last - first).days >= MAX_DAYS:
            self.s.notify(tr("Слишком длинный период: не больше {n} дней", n=MAX_DAYS))
            return 0
        loaded, problems = 0, []
        QGuiApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            day = first
            while day <= last:
                try:
                    if self.s.ledger.import_rates(self.s.company_id, day, self.fetch(day)):
                        loaded += 1
                except LedgerError as e:
                    problems.append(str(e))
                    if isinstance(e, cbar.RatesUnavailable) and "cbar.az" in str(e):
                        break  # no connection: do not try every other day
                day += timedelta(days=1)
        finally:
            QGuiApplication.restoreOverrideCursor()
        self.s.catalog.reload()
        self.refresh()
        if problems and not loaded:
            QMessageBox.warning(self, tr("Курсы ЦБА"), problems[0])
        else:
            self.s.notify(tr("Загружены курсы ЦБА за {n} дн.", n=loaded))
        return loaded

    # ---- revaluation -----------------------------------------------------------------

    def revalue(self) -> None:
        cat = self.s.catalog
        accounts = [a for a in cat.leaf_accounts if not a.currency and not any(a.sc_kinds)]
        if not accounts:
            self.s.notify(tr("Нет счёта без субконто для курсовых разниц"))
            return
        dlg, lay, form = _dialog(self, tr("Переоценка валютных остатков"))
        day = date_edit(month_of(self.s.working_date).date_to, dlg)
        gain, loss = QComboBox(), QComboBox()
        for box in (gain, loss):
            for a in accounts:
                box.addItem(a.label, a.id)
            default = cat.by_code.get("80")  # прибыли и убытки in the classic chart
            if default is not None and box.findData(default.id) >= 0:
                box.setCurrentIndex(box.findData(default.id))
        form.addRow(tr("На дату"), day)
        form.addRow(tr("Положительные разницы (Кт)"), gain)
        form.addRow(tr("Отрицательные разницы (Дт)"), loss)
        note = QLabel(
            tr(
                "Остатки валютных счетов пересчитываются по курсу на дату; разница "
                "проводится одним документом."
            )
        )
        note.setObjectName("secondary")
        note.setWordWrap(True)
        lay.addWidget(note)
        _buttons(dlg, lay)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        self.run_revaluation(edited_date(day), gain.currentData(), loss.currentData())

    def run_revaluation(self, day: date, gain_id: int, loss_id: int) -> int | None:
        try:
            doc_id = self.s.ledger.revalue(self.s.company_id, day, gain_id, loss_id)
        except LedgerError as e:
            QMessageBox.warning(self, tr("Переоценка валютных остатков"), str(e))
            return None
        if doc_id is None:
            self.s.notify(tr("Переоценка не нужна: остатки уже по курсу на эту дату"))
            return None
        self.s.notify(tr("Переоценка проведена"))
        self.open_document.emit(doc_id)
        return doc_id
