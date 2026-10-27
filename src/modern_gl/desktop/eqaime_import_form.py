"""The e-qaimə import window's fields: period and directions, the e-qaimə with their lines,
new and renamed counterparties, the actions; the dialog acts on them."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTreeWidget,
    QWidget,
)

from modern_gl.application.eqaime import (
    EInvoice,
    InvoicePlan,
    NewCounterparty,
    RenamedCounterparty,
)
from modern_gl.application.inventory import Inventory
from modern_gl.desktop.import_window import ImportWindow, say
from modern_gl.desktop.list_table import fit_tree
from modern_gl.desktop.period_field import portal_period
from modern_gl.desktop.portal_worker import PortalRun
from modern_gl.desktop.session import Session
from modern_gl.desktop.theme import fonts
from modern_gl.desktop.widgets import button
from modern_gl.i18n import N_, tr

COLUMNS = [
    N_("Дата"),
    N_("E-qaimə"),
    N_("Контрагент / строка"),
    N_("VÖEN / код"),
    N_("Вид"),
    N_("Сумма"),
    N_("ƏDV"),
    N_("Расход за"),
    N_("Станет"),
]
EXPENSE_MONTH = COLUMNS.index(N_("Расход за"))
BECOMES = COLUMNS.index(N_("Станет"))


class EqaimeImportForm(ImportWindow):
    def __init__(
        self,
        session: Session,
        parent: QWidget | None,
        sign_in: Callable[[QWidget], str | None] | None,
        direction: str | None,
        today: date | None,
    ) -> None:
        super().__init__(parent, tr("E-qaimə с портала"), session.company_name)
        self.s = session
        self.inventory = Inventory(session.conn, actor=session.ledger.actor)
        self.sign_in = sign_in
        self.token: str | None = None
        self.plans: list[InvoicePlan] = []
        self.created: list[int] = []
        self.attached: list[int] = []  # waiting purchases given their e-qaimə (D119)
        self.portal_run: PortalRun | None = None
        self.resize(1180, 720)
        self.company = self.subtitle
        self.period_field = portal_period(today or date.today())
        self.bar.addWidget(self.period_field)
        self._build_directions(direction)
        self.bar.addStretch(1)
        self.add_notes()
        say(
            self.status,
            tr(
                "Выберите период и нажмите «Загрузить с портала»: откроется вход через ASAN İmza. "
                "Импорт создаёт только черновики — каждый проверьте и проведите."
            ),
        )
        self._build_tree()
        self._build_parties()
        self._build_renames()
        self.spacer = QWidget()  # the air under the period while there are no rows
        self.root.addWidget(self.spacer, 1)
        self.load_button = self.primary(tr("Загрузить с портала"))
        self.import_button = self.primary(tr("Создать черновики"))
        self.import_button.hide()
        self.add_footer()

    def _build_directions(self, direction: str | None) -> None:
        """Both directions, when not opened from one section."""
        self.purchases = QCheckBox(tr("Полученные (покупки)"))
        self.purchases.setChecked(True)
        self.sales = QCheckBox(tr("Отправленные (продажи)"))
        self.sales.setChecked(True)
        for box in (self.purchases, self.sales):
            self.bar.addWidget(box)
            if direction is not None:
                box.hide()
        if direction is not None:
            self.purchases.setChecked(direction == "receipt")
            self.sales.setChecked(direction == "sale")

    def _build_tree(self) -> None:
        self.tree = QTreeWidget()
        self.tree.setColumnCount(len(COLUMNS))
        self.tree.setHeaderLabels([tr(c) for c in COLUMNS])
        self.tree.setRootIsDecorated(True)
        self.tree.setUniformRowHeights(True)
        self.tree.setAlternatingRowColors(False)
        fit_tree(self.tree, 2, len(COLUMNS) - 1)  # the counterparty, what it becomes
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
        self.tree.hide()
        self.root.addWidget(self.tree, 3)

    def _build_parties(self) -> None:
        """New counterparties: the VÖEN identifies them, the name is the user's to shorten."""
        parties = QHBoxLayout()
        self.parties_title = QLabel()
        self.parties_title.setFont(fonts().heading)
        parties.addWidget(self.parties_title, 1)
        self.add_parties_button = button(tr("Добавить контрагентов"), "flat")
        self.add_parties_button.setToolTip(tr("Только контрагенты, без документов"))
        parties.addWidget(self.add_parties_button)
        self.root.addLayout(parties)
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
        self.root.addWidget(self.parties, 1)
        self.new_parties: list[NewCounterparty] = []
        self.invoices: list[EInvoice] = []

    def _build_renames(self) -> None:
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
        self.root.addLayout(renames)
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
        self.root.addWidget(self.renames, 1)
        self.renamed: list[RenamedCounterparty] = []
