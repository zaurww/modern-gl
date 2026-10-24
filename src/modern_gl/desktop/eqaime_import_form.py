"""The e-qaimə import window's fields: period and directions, the e-qaimə with their lines,
new and renamed counterparties, the actions; the dialog acts on them."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date

from PySide6.QtCore import Qt, QThread
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTreeWidget,
    QVBoxLayout,
    QWidget,
)

from modern_gl.application.eqaime_import import (
    EInvoice,
    InvoicePlan,
    NewCounterparty,
    RenamedCounterparty,
)
from modern_gl.application.inventory import Inventory
from modern_gl.desktop.period_field import portal_period
from modern_gl.desktop.session import Session
from modern_gl.desktop.theme import fonts
from modern_gl.desktop.widgets import button
from modern_gl.i18n import tr

COLUMNS = [
    "Дата",
    "E-qaimə",
    "Контрагент / строка",
    "VÖEN / код",
    "Вид",
    "Сумма",
    "ƏDV",
    "Расход за",
    "Станет",
]
EXPENSE_MONTH = COLUMNS.index("Расход за")
BECOMES = COLUMNS.index("Станет")


class EqaimeImportForm(QDialog):
    def __init__(
        self,
        session: Session,
        parent: QWidget | None,
        sign_in: Callable[[QWidget], str | None] | None,
        direction: str | None,
        today: date | None,
    ) -> None:
        super().__init__(parent)
        self.s = session
        self.inventory = Inventory(session.conn, actor=session.ledger.actor)
        self.sign_in = sign_in
        self.token: str | None = None
        self.plans: list[InvoicePlan] = []
        self.created: list[int] = []
        self.attached: list[int] = []  # waiting purchases given their e-qaimə (D119)
        self.worker: QThread | None = None
        self.setWindowTitle(tr("E-qaimə с портала"))
        self.resize(1180, 720)
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 22, 28, 20)
        root.setSpacing(12)

        title = QLabel(tr("E-qaimə с портала"))
        title.setFont(fonts().title)
        root.addWidget(title)
        self.company = QLabel()
        self.company.setObjectName("secondary")
        root.addWidget(self.company)

        self._build_bar(root, today)
        self._build_directions(root, direction)
        self._build_tree(root)
        self._build_parties(root)
        self._build_renames(root)

        self.warning = QLabel()
        self.warning.setObjectName("warning")
        self.warning.setWordWrap(True)
        self.warning.hide()
        root.addWidget(self.warning)

        self.status = QLabel(
            tr(
                "Выберите период и нажмите «Загрузить с портала»: откроется вход через ASAN İmza. "
                "Импорт создаёт только черновики — каждый проверьте и проведите."
            )
        )
        self.status.setObjectName("secondary")
        self.status.setWordWrap(True)
        root.addWidget(self.status)

        self._build_actions(root)

    def _build_bar(self, root: QVBoxLayout, today: date | None) -> None:
        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.period_field = portal_period(today or date.today())
        bar.addWidget(self.period_field)
        bar.addStretch(1)
        self.load_button = button(tr("Загрузить с портала"), "primary")
        bar.addWidget(self.load_button)
        root.addLayout(bar)

    def _build_directions(self, root: QVBoxLayout, direction: str | None) -> None:
        both = QHBoxLayout()  # the directions, when not opened from one section
        both.setSpacing(16)
        self.purchases = QCheckBox(tr("Полученные (покупки)"))
        self.purchases.setChecked(True)
        self.sales = QCheckBox(tr("Отправленные (продажи)"))
        self.sales.setChecked(True)
        both.addWidget(self.purchases)
        both.addWidget(self.sales)
        both.addStretch(1)
        if direction is not None:
            self.purchases.setChecked(direction == "receipt")
            self.sales.setChecked(direction == "sale")
            self.purchases.hide()
            self.sales.hide()
        else:
            root.addLayout(both)

    def _build_tree(self, root: QVBoxLayout) -> None:
        self.tree = QTreeWidget()
        self.tree.setColumnCount(len(COLUMNS))
        self.tree.setHeaderLabels([tr(c) for c in COLUMNS])
        self.tree.setRootIsDecorated(True)
        self.tree.setUniformRowHeights(True)
        self.tree.setAlternatingRowColors(False)
        header = self.tree.header()
        for column, width in enumerate((118, 140, 0, 104, 64, 90, 76, 130, 0)):
            if width:
                self.tree.setColumnWidth(column, width)
            else:
                header.setSectionResizeMode(column, QHeaderView.ResizeMode.Stretch)
        for column in (5, 6):
            self.tree.headerItem().setTextAlignment(
                column, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
        self.tree.headerItem().setToolTip(
            EXPENSE_MONTH,
            tr(
                "Месяц расхода по услугам, если e-qaimə пришла позже: расход начисляется "
                "последним днём этого месяца (Дт затрат / Кт 76H), долг поставщику и НДС — "
                "датой e-qaimə"
            ),
        )
        root.addWidget(self.tree, 3)

    def _build_parties(self, root: QVBoxLayout) -> None:
        """New counterparties: the VÖEN identifies them, the name is the user's to shorten."""
        parties = QHBoxLayout()
        self.parties_title = QLabel()
        self.parties_title.setFont(fonts().heading)
        parties.addWidget(self.parties_title, 1)
        self.add_parties_button = button(tr("Добавить контрагентов"), "flat")
        self.add_parties_button.setToolTip(tr("Только контрагенты, без документов"))
        parties.addWidget(self.add_parties_button)
        root.addLayout(parties)
        self.parties = QTableWidget(0, 4)
        self.parties.setHorizontalHeaderLabels(
            [tr("VÖEN"), tr("Название на портале"), tr("Название в программе"), tr("E-qaimə")]
        )
        self.parties.verticalHeader().hide()
        self.parties.setShowGrid(False)
        parties_header = self.parties.horizontalHeader()
        parties_header.setDefaultAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        for column, mode in enumerate(
            (
                QHeaderView.ResizeMode.Interactive,
                QHeaderView.ResizeMode.Stretch,
                QHeaderView.ResizeMode.Stretch,
                QHeaderView.ResizeMode.Interactive,
            )
        ):
            parties_header.setSectionResizeMode(column, mode)
        self.parties.setColumnWidth(0, 120)
        self.parties.setColumnWidth(3, 80)
        self.parties.setToolTip(tr("Название в программе можно исправить — двойной щелчок"))
        root.addWidget(self.parties, 1)
        self.new_parties: list[NewCounterparty] = []
        self.invoices: list[EInvoice] = []

    def _build_renames(self, root: QVBoxLayout) -> None:
        """The same VÖEN under a new name on the portal: rename here, or keep the name."""
        renames = QHBoxLayout()
        self.renames_title = QLabel()
        self.renames_title.setFont(fonts().heading)
        renames.addWidget(self.renames_title, 1)
        self.renames_button = button(tr("Применить названия"), "flat")
        self.renames_button.setToolTip(
            tr("Отмеченные — переименовать в программе; у всех запомнить новое название портала")
        )
        renames.addWidget(self.renames_button)
        root.addLayout(renames)
        self.renames = QTableWidget(0, 5)
        self.renames.setHorizontalHeaderLabels(
            [
                tr("VÖEN"),
                tr("Было на портале"),
                tr("Стало на портале"),
                tr("Сейчас в программе"),
                tr("Новое название в программе"),
            ]
        )
        self.renames.verticalHeader().hide()
        self.renames.setShowGrid(False)
        renames_header = self.renames.horizontalHeader()
        renames_header.setDefaultAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        for column in range(1, 5):
            renames_header.setSectionResizeMode(column, QHeaderView.ResizeMode.Stretch)
        self.renames.setColumnWidth(0, 140)
        root.addWidget(self.renames, 1)
        self.renamed: list[RenamedCounterparty] = []

    def _build_actions(self, root: QVBoxLayout) -> None:
        actions = QHBoxLayout()
        actions.addStretch(1)
        close = button(tr("Закрыть"), "flat")
        close.clicked.connect(self.reject)
        actions.addWidget(close)
        self.import_button = button(tr("Создать черновики"), "primary")
        self.import_button.setEnabled(False)
        actions.addWidget(self.import_button)
        root.addLayout(actions)
