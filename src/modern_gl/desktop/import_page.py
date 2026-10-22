"""Import of many documents from Excel: paste a table (or open a file), see every row
as it will be posted with its problems, then import all at once (all or nothing)."""

from __future__ import annotations

from datetime import date
from fractions import Fraction
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QStackedLayout,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from modern_gl.application import journal_import
from modern_gl.application.currencies import rate_on
from modern_gl.application.journal_import import ImportPlan, Row
from modern_gl.desktop.reports_page import Column, ReportModel
from modern_gl.desktop.session import Session
from modern_gl.desktop.theme import P, fonts
from modern_gl.desktop.widgets import EmptyState, PageHeader, button, money
from modern_gl.domain.errors import LedgerError
from modern_gl.domain.money import format_minor
from modern_gl.i18n import tr
from modern_gl.infrastructure.table_files import from_clipboard, read_rows

COLUMNS_HINT = "Дата · Документ · Дебет · Субконто · Кредит · Субконто · Сумма · Содержание"


class ImportPage(QWidget):
    key = ("import",)
    imported = Signal(list)  # ids of the new documents

    def __init__(self, session: Session) -> None:
        super().__init__()
        self.setObjectName("page")
        self.s = session
        self.source: list[list[str]] = []
        self.plan = ImportPlan()
        root = QVBoxLayout(self)
        root.setContentsMargins(40, 30, 40, 24)
        root.setSpacing(16)

        self.header = PageHeader(
            tr("Импорт из Excel"),
            tr("Скопируйте строки вместе с заголовком и нажмите Ctrl+V, или откройте файл"),
        )
        paste = button(tr("Вставить"), "flat", "Ctrl+V")
        paste.clicked.connect(lambda: self.paste())
        self.header.add_action(paste)
        self.header.primary(tr("Открыть файл…"), self.open_file, tr("Excel (.xlsx) или CSV"))
        root.addWidget(self.header)

        options = QHBoxLayout()
        options.setSpacing(16)
        self.mode = QComboBox()
        self.mode.addItem(tr("Провести документы"), True)
        self.mode.addItem(tr("Сохранить черновиками"), False)
        self.mode.setFixedWidth(230)
        self.add_new = QCheckBox(tr("Добавлять новые элементы справочников"))
        self.add_new.setToolTip(
            tr("Названия, которых нет в справочниках, будут добавлены (иначе это ошибка)")
        )
        options.addWidget(self.mode)
        options.addWidget(self.add_new)
        options.addStretch(1)
        root.addLayout(options)
        self.mode.currentIndexChanged.connect(lambda _: self.rebuild())
        self.add_new.toggled.connect(lambda _: self.rebuild())

        self.model = ReportModel()
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setShowGrid(False)
        self.table.setWordWrap(False)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(32)
        self.table.horizontalHeader().setHighlightSections(False)
        self.empty = EmptyState(
            "⇩",
            tr("Вставьте таблицу из Excel"),
            tr("Колонки (первая строка): {columns}", columns=tr(COLUMNS_HINT))
            + "\n"
            + tr("Обязательны: Дата, Дебет, Кредит, Сумма. Одинаковый «Документ» — один документ."),
        )
        self.stack = QStackedLayout()
        self.stack.addWidget(self.table)
        self.stack.addWidget(self.empty)
        root.addLayout(self.stack, 1)

        bottom = QHBoxLayout()
        self.summary = QLabel()
        self.summary.setObjectName("secondary")
        self.summary.setWordWrap(True)
        bottom.addWidget(self.summary, 1)
        self.run_button = button(tr("Импортировать"), "primary")
        self.run_button.setMinimumWidth(170)
        self.run_button.clicked.connect(self.run)
        bottom.addWidget(self.run_button)
        root.addLayout(bottom)

        sc = QShortcut(QKeySequence("Ctrl+V"), self)
        sc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        sc.activated.connect(lambda: self.paste())
        self.rebuild()

    def title(self) -> str:
        return tr("Импорт из Excel")

    def is_dirty(self) -> bool:
        return False

    def focus_table(self) -> None:
        self.table.setFocus()

    # ---- input -------------------------------------------------------------------------

    def paste(self, text: str | None = None) -> None:
        text = QApplication.clipboard().text() if text is None else text
        self.load(from_clipboard(text))

    def open_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, tr("Импорт из Excel"), "", tr("Таблицы (*.xlsx *.csv *.txt *.tsv)")
        )
        if path:
            self.load_file(Path(path))

    def load_file(self, path: Path) -> None:
        try:
            rows = read_rows(path)
        except LedgerError as e:
            self.s.notify(str(e))
            return
        self.load(rows)

    def load(self, rows: list[list[str]]) -> None:
        self.source = rows
        self.rebuild()

    # ---- preview -----------------------------------------------------------------------

    def _rate(self, currency_id: int, day: date) -> Fraction | None:
        rate = rate_on(self.s.conn, self.s.company_id, currency_id, day)
        return rate.per_unit if rate else None

    def _read(self) -> ImportPlan:
        return journal_import.read_plan(
            self.source, self.s.catalog, self.s.layers, self._rate, self.add_new.isChecked()
        )

    def rebuild(self) -> None:
        if not self.source:
            self.plan = ImportPlan()
            self.model.set([], [])
            self.stack.setCurrentWidget(self.empty)
            self.summary.setText("")
            self.run_button.setEnabled(False)
            return
        self.plan = self._read()
        if not self.plan.problem:
            journal_import.check(
                self.s.ledger, self.s.company_id, self.plan, self.mode.currentData()
            )
        self._show()

    def _show(self) -> None:
        plan = self.plan
        currency = any(r.currency for r in plan.rows)

        def side(r: Row, debit: bool) -> str:
            acc = r.debit if debit else r.credit
            names = r.debit_names if debit else r.credit_names
            if acc is None:
                return ""
            return "  ·  ".join([acc.short, ", ".join(names)]) if names else acc.short

        columns = [
            Column(tr("Строка"), lambda r: r.row_no, width=64),
            Column(tr("Док."), lambda r: r.document + 1, width=56),
            Column(tr("Дата"), lambda r: f"{r.doc_date:%d.%m.%Y}" if r.doc_date else "", width=100),
            Column(tr("Дебет"), lambda r: side(r, True), width=200),
            Column(tr("Кредит"), lambda r: side(r, False), width=200),
            Column(tr("Сумма"), lambda r: r.amount, money=True, width=110),
            Column(tr("Содержание"), lambda r: r.memo, width=150),
            Column(
                tr("Проверка"),
                lambda r: "; ".join(r.errors) if r.errors else "✓",
                warn=lambda r: "\n".join(r.errors) or None,
            ),
        ]
        if currency:
            columns.insert(
                5,
                Column(
                    tr("В валюте"),
                    lambda r: (
                        f"{format_minor(r.currency_amount)} {r.currency}"
                        if r.currency_amount
                        else ""
                    ),
                    width=130,
                ),
            )
        self.model.set(columns, plan.rows, muted=lambda r: not r.errors)
        hh = self.table.horizontalHeader()
        for i, col in enumerate(columns):
            if col.width:
                hh.setSectionResizeMode(i, QHeaderView.ResizeMode.Interactive)
                self.table.setColumnWidth(i, col.width)
            else:
                hh.setSectionResizeMode(i, QHeaderView.ResizeMode.Stretch)
        self.stack.setCurrentWidget(self.table if plan.rows else self.empty)

        total = sum(r.amount or 0 for r in plan.rows)
        text = tr(
            "Документов: {docs}   ·   строк: {rows}   ·   сумма {total}",
            docs=len(plan.documents),
            rows=len(plan.rows),
            total=money(total, False),
        )
        if plan.new_values:
            text += "   ·   " + tr("новых элементов: {n}", n=len(plan.new_values))
        bad = sum(1 for r in plan.rows if r.errors)
        if plan.problem:
            text = plan.problem
        elif bad:
            text += "\n" + tr(
                "Строк с ошибками: {n}. Исправьте их в Excel и вставьте снова — "
                "импорт идёт целиком или не идёт.",
                n=bad,
            )
        self.summary.setText(text)
        self.summary.setStyleSheet(f"color: {P.red};" if bad or plan.problem else "")
        ready = bool(plan.documents) and not bad and not plan.problem
        self.run_button.setEnabled(ready)
        self.run_button.setText(
            tr("Импортировать {n} док.", n=len(plan.documents)) if ready else tr("Импортировать")
        )
        self.run_button.setFont(fonts().body)

    # ---- import ------------------------------------------------------------------------

    def run(self) -> list[int]:
        self.plan = self._read()  # fresh: new elements get their ids in the import itself
        ids = journal_import.run(
            self.s.ledger, self.s.company_id, self.plan, self.mode.currentData()
        )
        if not ids:
            self._show()
            return []
        if self.plan.new_values:
            self.s.catalog.reload()
        posted = self.mode.currentData()
        self.s.notify(
            tr("Импортировано документов: {n} (проведены)", n=len(ids))
            if posted
            else tr("Импортировано документов: {n} (черновики)", n=len(ids))
        )
        self.source = []
        self.rebuild()
        self.imported.emit(ids)
        return ids
