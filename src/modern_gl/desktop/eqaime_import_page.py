"""«E-qaimələri yüklə»: e-qaimə of a period from the tax portal, shown line by line with
what each line would become, then imported as purchase and sale drafts (D45)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date

from PySide6.QtCore import QObject, Qt, QThread, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from modern_gl.application.eqaime_import import (
    EInvoice,
    InvoicePlan,
    LinePlan,
    import_drafts,
    parse_invoice,
    plan_import,
)
from modern_gl.application.inventory import Inventory, format_quantity, to_quantity
from modern_gl.desktop.session import Session
from modern_gl.desktop.theme import P, fonts
from modern_gl.desktop.widgets import button, date_edit, edited_date, money
from modern_gl.domain.dates import ru_date
from modern_gl.domain.errors import LedgerError
from modern_gl.i18n import tr
from modern_gl.infrastructure.etaxes import EtaxesClient, PortalError

COLUMNS = ["Дата", "E-qaimə", "Контрагент / строка", "VÖEN / код", "Вид", "Сумма", "ƏDV", "Станет"]


def fetch_invoices(
    client: EtaxesClient,
    date_from: date,
    date_to: date,
    purchases: bool,
    sales: bool,
    progress: Callable[[str], None],
) -> list[EInvoice]:
    """The e-qaimə of the period with their lines: received (purchases), sent (sales)."""
    result = []
    for outgoing, wanted in ((False, purchases), (True, sales)):
        if not wanted:
            continue
        rows = list(client.invoices(outgoing, date_from, date_to))
        for n, row in enumerate(rows, 1):
            progress(tr("Загружено e-qaimə: {n} из {total}", n=n, total=len(rows)))
            detail = client.detail(str(row.get("id")), str(row.get("sourceSystem") or "avis"))
            result.append(parse_invoice(row, detail, outgoing))
    return result


class _Loader(QObject):
    progress = Signal(str)
    loaded = Signal(list)
    failed = Signal(str)

    def __init__(self, job: Callable[[Callable[[str], None]], list[EInvoice]]) -> None:
        super().__init__()
        self.job = job

    def run(self) -> None:
        try:
            self.loaded.emit(self.job(self.progress.emit))
        except PortalError as exc:
            self.failed.emit(str(exc))


class EqaimeImportDialog(QDialog):
    """Period and direction → sign in → the e-qaimə with their lines → drafts."""

    def __init__(
        self,
        session: Session,
        parent: QWidget | None = None,
        sign_in: Callable[[QWidget], str | None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.s = session
        self.inventory = Inventory(session.conn, actor=session.ledger.actor)
        self.sign_in = sign_in
        self.token: str | None = None
        self.plans: list[InvoicePlan] = []
        self.created: list[int] = []
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

        bar = QHBoxLayout()
        bar.setSpacing(8)
        first = session.working_date.replace(day=1)
        self.date_from = date_edit(first)
        self.date_to = date_edit(session.working_date)
        for caption, widget in ((tr("Период с"), self.date_from), (tr("по"), self.date_to)):
            label = QLabel(caption)
            label.setObjectName("secondary")
            widget.setFixedWidth(130)
            bar.addWidget(label)
            bar.addWidget(widget)
        bar.addSpacing(10)
        self.purchases = QCheckBox(tr("Полученные (покупки)"))
        self.purchases.setChecked(True)
        self.sales = QCheckBox(tr("Отправленные (продажи)"))
        self.sales.setChecked(True)
        bar.addWidget(self.purchases)
        bar.addWidget(self.sales)
        bar.addSpacing(10)
        self.load_button = button(tr("Загрузить с портала"), "primary")
        self.load_button.clicked.connect(self.load)
        bar.addWidget(self.load_button)
        bar.addStretch(1)
        root.addLayout(bar)

        self.tree = QTreeWidget()
        self.tree.setColumnCount(len(COLUMNS))
        self.tree.setHeaderLabels([tr(c) for c in COLUMNS])
        self.tree.setRootIsDecorated(True)
        self.tree.setUniformRowHeights(True)
        self.tree.setAlternatingRowColors(False)
        header = self.tree.header()
        for column, width in enumerate((124, 150, 0, 110, 70, 100, 90, 240)):
            if width:
                self.tree.setColumnWidth(column, width)
            else:
                header.setSectionResizeMode(column, QHeaderView.ResizeMode.Stretch)
        for column in (5, 6):
            self.tree.headerItem().setTextAlignment(
                column, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
        self.tree.itemChanged.connect(lambda *_: self._show_count())
        root.addWidget(self.tree, 1)

        self.status = QLabel(
            tr(
                "Выберите период и нажмите «Загрузить с портала»: откроется вход через ASAN İmza. "
                "Импорт создаёт только черновики — каждый проверьте и проведите."
            )
        )
        self.status.setObjectName("secondary")
        self.status.setWordWrap(True)
        root.addWidget(self.status)

        actions = QHBoxLayout()
        actions.addStretch(1)
        close = button(tr("Закрыть"), "flat")
        close.clicked.connect(self.reject)
        actions.addWidget(close)
        self.import_button = button(tr("Создать черновики"), "primary")
        self.import_button.setEnabled(False)
        self.import_button.clicked.connect(self.create_drafts)
        actions.addWidget(self.import_button)
        root.addLayout(actions)

    # ---- loading -------------------------------------------------------------------

    def load(self) -> None:
        from modern_gl.desktop import portal_login

        token = self.token
        if token is None or not portal_login.token_alive(token):
            sign_in = self.sign_in or portal_login.sign_in
            token = sign_in(self)
            if not token:
                return
        self.token = token
        name = portal_login.company_name(token)
        tin = portal_login.company_tin(token)
        self.company.setText(tr("Портал: {name} · VÖEN {tin}", name=name, tin=tin))
        client = EtaxesClient(token)
        date_from, date_to = edited_date(self.date_from), edited_date(self.date_to)
        purchases, sales = self.purchases.isChecked(), self.sales.isChecked()
        self._start(
            lambda progress: fetch_invoices(client, date_from, date_to, purchases, sales, progress)
        )

    def _start(self, job: Callable[[Callable[[str], None]], list[EInvoice]]) -> None:
        """Talk to the portal off the window's thread: the window stays alive."""
        self.load_button.setEnabled(False)
        self.status.setText(tr("Загрузка с портала…"))
        self.worker = QThread(self)
        self.loader = _Loader(job)
        self.loader.moveToThread(self.worker)
        self.worker.started.connect(self.loader.run)
        self.loader.progress.connect(self.status.setText)
        self.loader.loaded.connect(self.show_invoices)
        self.loader.failed.connect(self._failed)
        for signal in (self.loader.loaded, self.loader.failed):
            signal.connect(self.worker.quit)
        self.worker.start()

    def _failed(self, message: str) -> None:
        self.load_button.setEnabled(True)
        self.status.setText(message)
        self.token = None  # a new sign-in next time

    def show_invoices(self, invoices: list[EInvoice]) -> None:
        self.load_button.setEnabled(True)
        self.plans = plan_import(self.s.conn, self.s.company_id, invoices)
        self.tree.blockSignals(True)
        self.tree.clear()
        for plan in self.plans:
            self.tree.addTopLevelItem(self._invoice_item(plan))
        self.tree.blockSignals(False)
        self._show_count()

    # ---- the list ------------------------------------------------------------------

    def _invoice_item(self, plan: InvoicePlan) -> QTreeWidgetItem:
        invoice = plan.invoice
        kind = tr("Продажа") if invoice.outgoing else tr("Покупка")
        item = QTreeWidgetItem(
            [
                ru_date(invoice.doc_date),
                invoice.number,
                invoice.party_name,
                invoice.party_tin,
                kind,
                money(invoice.amount, blank_zero=False),
                money(invoice.vat),
                self._invoice_state(plan),
            ]
        )
        item.setData(0, Qt.ItemDataRole.UserRole, plan)
        bold = item.font(2)
        bold.setBold(True)
        item.setFont(2, bold)
        for column in (5, 6):
            item.setTextAlignment(
                column, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
        if plan.importable:
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(0, Qt.CheckState.Checked)
        else:
            for column in range(len(COLUMNS)):
                item.setForeground(column, QColor(P.tertiary))
        if plan.unresolved and plan.importable:
            item.setForeground(7, QColor(P.amber))
        for line in plan.lines:
            item.addChild(self._line_item(line, invoice.outgoing))
        return item

    def _invoice_state(self, plan: InvoicePlan) -> str:
        if plan.existing is not None:
            return tr("уже есть: документ №{n}", n=plan.existing)
        if plan.skip_reason:
            return plan.skip_reason
        parts = []
        if plan.counterparty_id is None:
            parts.append(tr("новый контрагент"))
        if plan.unresolved:
            parts.append(tr("проверить строк: {n}", n=plan.unresolved))
        return ", ".join(parts) or tr("готово")

    def _line_item(self, plan: LinePlan, outgoing: bool) -> QTreeWidgetItem:
        line = plan.line
        quantity = ""
        if line.quantity is not None:
            try:
                quantity = f"{format_quantity(to_quantity(line.quantity), 6)} {line.unit}".strip()
            except ValueError:
                quantity = str(line.quantity)
        child = QTreeWidgetItem(
            [
                "",
                quantity,
                line.name or tr("(без строк)"),
                line.code,
                tr("Услуга") if line.service else tr("Товар"),
                money(line.amount, blank_zero=False),
                money(line.vat),
                self._becomes(plan, outgoing),
            ]
        )
        for column in (1, 5, 6):
            child.setTextAlignment(
                column, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
        for column in range(len(COLUMNS)):
            child.setForeground(column, QColor(P.secondary))
        unresolved = (
            plan.item_id is None and not line.service
            if outgoing
            else plan.item_id is None and plan.account_id is None
        )
        if unresolved:
            child.setForeground(7, QColor(P.amber))
        return child

    def _becomes(self, plan: LinePlan, outgoing: bool) -> str:
        catalog = self.s.catalog
        how = {"history": tr("как в прошлый раз"), "name": tr("по названию")}.get(plan.found, "")
        if plan.item_id is not None:
            name = self._item_name(plan.item_id)
            text = tr("товар «{name}»", name=name)
        elif plan.account_id is not None:
            account = catalog.accounts.get(plan.account_id)
            values = [catalog.value(v).name for v in plan.subconto if v is not None]
            text = " ".join([account.label if account else "", *values]).strip()
        elif outgoing and plan.line.service:
            text = tr("услуга")
        else:
            return tr("выберите товар или счёт")
        return f"{text} · {how}" if how else text

    def _item_name(self, item_id: int) -> str:
        row = self.s.conn.execute(
            "SELECT v.name FROM inventory_items i JOIN subconto_values v "
            "ON v.id = i.subconto_value_id WHERE i.id = ?",
            (item_id,),
        ).fetchone()
        return row["name"] if row else ""

    def _checked(self) -> list[InvoicePlan]:
        result = []
        for index in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(index)
            if item is not None and item.checkState(0) == Qt.CheckState.Checked:
                result.append(item.data(0, Qt.ItemDataRole.UserRole))
        return result

    def _show_count(self) -> None:
        chosen = self._checked()
        self.import_button.setEnabled(bool(chosen))
        self.import_button.setText(tr("Создать черновики: {n}", n=len(chosen)))
        if self.plans:
            new = sum(1 for p in self.plans if p.importable)
            self.status.setText(
                tr(
                    "E-qaimə: {total}, новых: {new}. Строки, отмеченные цветом, — без товара или "
                    "счёта: выберите их в черновике.",
                    total=len(self.plans),
                    new=new,
                )
            )

    def create_drafts(self) -> None:
        chosen = self._checked()
        if not chosen:
            return
        try:
            self.created = import_drafts(self.inventory, self.s.company_id, chosen)
        except LedgerError as exc:
            self.status.setText(str(exc))
            return
        self.s.catalog.reload()  # new counterparties
        self.accept()
