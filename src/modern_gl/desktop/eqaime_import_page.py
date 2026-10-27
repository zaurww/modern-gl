"""«E-qaimələri yüklə»: e-qaimə of a period from the tax portal, shown line by line with
what each line would become, then imported as purchase and sale drafts (D45)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date

from PySide6.QtCore import Qt, QThread
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QTableWidgetItem,
    QTreeWidgetItem,
    QWidget,
)

from modern_gl.application.eqaime import (
    AwaitingPurchase,
    EInvoice,
    InvoicePlan,
    LinePlan,
    add_counterparties,
    apply_renames,
    import_drafts,
    new_counterparties,
    plan_import,
    renamed_counterparties,
)
from modern_gl.application.eqaime.portal import read_again, rechecks
from modern_gl.application.inventory import format_quantity, to_quantity
from modern_gl.desktop.eqaime_import_form import BECOMES, COLUMNS, EXPENSE_MONTH, EqaimeImportForm
from modern_gl.desktop.eqaime_portal_loader import (
    Fetched,
    PortalLoader,
    changes_warning,
    fetch_invoices,
)
from modern_gl.desktop.import_window import say
from modern_gl.desktop.pick import PickBox
from modern_gl.desktop.session import Session
from modern_gl.desktop.theme import P, fonts
from modern_gl.desktop.widgets import money
from modern_gl.domain.dates import earlier_months, month_name, ru_date
from modern_gl.domain.errors import LedgerError
from modern_gl.i18n import tr
from modern_gl.infrastructure.etaxes import EtaxesClient
from modern_gl.reporting.inventory import item_name

# what an e-qaimə becomes (a return e-qaimə — a return, D-new)
KIND_NAMES = {
    "receipt": "Покупка",
    "sale": "Продажа",
    "purchase_return": "Возврат поставщику",
    "sale_return": "Возврат от покупателя",
}


class EqaimeImportDialog(EqaimeImportForm):
    """Period and direction → sign in → the e-qaimə with their lines → drafts."""

    def __init__(
        self,
        session: Session,
        parent: QWidget | None = None,
        sign_in: Callable[[QWidget], str | None] | None = None,
        direction: str | None = None,  # "receipt" / "sale": one direction only, from its section
        today: date | None = None,
    ) -> None:
        super().__init__(session, parent, sign_in, direction, today)
        self.load_button.clicked.connect(self.load)
        self.tree.itemChanged.connect(lambda *_: self._show_count())
        self.add_parties_button.clicked.connect(self.add_parties)
        self.renames_button.clicked.connect(self.apply_renames)
        self.import_button.clicked.connect(self.create_drafts)
        self.period_field.changed.connect(self._choice_changed)
        for box in (self.purchases, self.sales):
            box.toggled.connect(self._choice_changed)
        self._show_parties()
        self._show_renames()

    # ---- loading -------------------------------------------------------------------

    def load(self) -> None:
        from modern_gl.desktop import portal_login
        from modern_gl.desktop.portal_company import company_token

        token = company_token(self, self.s, self.sign_in)  # this company's, D113
        if not token:
            return
        self.token = token
        name = portal_login.company_name(token)
        tin = portal_login.company_tin(token)
        self.company.setText(tr("Портал: {name} · VÖEN {tin}", name=name, tin=tin))
        client = EtaxesClient(token)
        date_from, date_to = self.period_field.period()
        purchases, sales = self.purchases.isChecked(), self.sales.isChecked()
        checks = rechecks(self.s.conn, self.s.company_id, date.today())
        self._start(
            lambda progress: Fetched(
                fetch_invoices(client, date_from, date_to, purchases, sales, progress),
                read_again(client, checks, progress),
            )
        )

    def _start(self, job: Callable[[Callable[[str], None]], Fetched]) -> None:
        """Talk to the portal off the window's thread: the window stays alive."""
        self.load_button.setEnabled(False)
        self.status.setText(tr("Загрузка с портала…"))
        self.worker = QThread(self)
        self.loader = PortalLoader(job)
        self.loader.moveToThread(self.worker)
        self.worker.started.connect(self.loader.run)
        self.loader.progress.connect(self.status.setText)
        self.loader.loaded.connect(self._loaded)
        self.loader.failed.connect(self._failed)
        for signal in (self.loader.loaded, self.loader.failed):
            signal.connect(self.worker.quit)
        self.worker.start()

    def _failed(self, message: str) -> None:
        self.load_button.setEnabled(True)
        self.status.setText(message)
        self.token = None  # a new sign-in next time
        from modern_gl.desktop import portal_login

        portal_login.forget_token()

    def _loaded(self, fetched: Fetched) -> None:
        """Remember what the portal shows (D53), warn of changes in reconciled months."""
        listed = [i.listed for i in fetched.invoices if i.listed is not None]
        try:
            self.s.ledger.eqaime.remember_portal(self.s.company_id, [*fetched.rechecked, *listed])
        except LedgerError as exc:
            self.status.setText(str(exc))
        warning = changes_warning(self.s.conn, self.s.company_id)
        self.warning.setText(warning)
        self.warning.setVisible(bool(warning))
        self.show_invoices(fetched.invoices)

    def _choice_changed(self, *_args) -> None:
        """The rows were of another period or direction: back to the first step."""
        if not self.import_button.isVisibleTo(self):
            return
        self.show_invoices([], loaded=False)
        say(self.status, tr("Период изменён — загрузите его с портала."))

    def show_invoices(self, invoices: list[EInvoice], loaded: bool = True) -> None:
        self.load_button.setEnabled(True)
        for widget, shown in (
            (self.tree, loaded),
            (self.spacer, not loaded),
            (self.load_button, not loaded),
            (self.import_button, loaded),
        ):
            widget.setVisible(shown)
        self.invoices = invoices
        self.plans = plan_import(self.s.conn, self.s.company_id, invoices)
        self.new_parties = new_counterparties(self.plans)
        self._show_parties()
        self.renamed = renamed_counterparties(self.s.conn, self.s.company_id, self.plans)
        self._show_renames()
        self.tree.blockSignals(True)
        self.tree.clear()
        for plan in self.plans:
            item = self._invoice_item(plan)
            self.tree.addTopLevelItem(item)
            if plan.importable and plan.has_expenses:
                self.tree.setItemWidget(item, EXPENSE_MONTH, self._expense_month(plan))
            if plan.importable and plan.awaiting:
                self.tree.setItemWidget(item, BECOMES, self._awaiting_box(plan, item))
        self.tree.blockSignals(False)
        self._show_count()

    # ---- the list ------------------------------------------------------------------

    def _invoice_item(self, plan: InvoicePlan) -> QTreeWidgetItem:
        invoice = plan.invoice
        kind = tr(KIND_NAMES[plan.document_type])
        item = QTreeWidgetItem(
            [
                ru_date(invoice.doc_date),
                invoice.number,
                invoice.party_name,
                invoice.party_tin,
                kind,
                money(invoice.amount, blank_zero=False),
                money(invoice.vat),
                "",
                self._invoice_state(plan),
            ]
        )
        item.setData(0, Qt.ItemDataRole.UserRole, plan)
        item.setFont(2, fonts().cell_bold)
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
            item.setForeground(BECOMES, QColor(P.amber))
        for line in plan.lines:
            item.addChild(self._line_item(line, plan.as_sale, plan.return_type is not None))
        return item

    def _expense_month(self, plan: InvoicePlan) -> PickBox:
        """The month of a purchase's services: the e-qaimə's own or one of the twelve
        before it (D65); the choice goes into the plan."""
        box = PickBox()
        box.addItem(tr("месяц документа"), None)
        for last in earlier_months(plan.invoice.doc_date):
            box.addItem(month_name(last[:7]), last)
        box.setCurrentIndex(max(box.findData(plan.expense_date), 0))

        def chosen(_index: int) -> None:
            plan.expense_date = box.currentData()

        box.activated.connect(chosen)
        return box

    def _awaiting_box(self, plan: InvoicePlan, item: QTreeWidgetItem) -> PickBox:
        """The supplier's purchases waiting for an e-qaimə (D119): the e-qaimə goes into
        one of them or becomes a new draft; the choice goes into the plan."""
        box = PickBox()
        box.addItem(tr("Новый черновик: {state}", state=self._new_state(plan)), None)
        for purchase in plan.awaiting:
            box.addItem(self._awaiting_label(plan, purchase), purchase)
        box.setCurrentIndex(max(box.findData(plan.attach_to), 0))

        def chosen(_index: int) -> None:
            plan.attach_to = box.currentData()
            month = self.tree.itemWidget(item, EXPENSE_MONTH)
            if month is not None:  # the purchase has its own month
                month.setEnabled(plan.attach_to is None)
            self._show_count()

        box.activated.connect(chosen)
        chosen(box.currentIndex())
        return box

    @staticmethod
    def _awaiting_label(plan: InvoicePlan, purchase: AwaitingPurchase) -> str:
        text = tr(
            "В покупку №{n} от {date} ({amount}), ждёт e-qaimə",
            n=purchase.number,
            date=ru_date(purchase.doc_date),
            amount=money(purchase.amount, blank_zero=False),
        )
        if plan.agrees(purchase):
            return text
        return text + " · " + tr("сумма другая — проверьте покупку")

    def _invoice_state(self, plan: InvoicePlan) -> str:
        if plan.existing is not None:
            return tr("уже есть: документ №{n}", n=plan.existing)
        if plan.skip_reason:
            return plan.skip_reason
        return self._new_state(plan)

    @staticmethod
    def _new_state(plan: InvoicePlan) -> str:
        parts = [tr("ожидает подтверждения")] if plan.invoice.pending else []
        if plan.counterparty_id is None:
            parts.append(tr("новый контрагент"))
        if plan.unresolved:
            parts.append(tr("проверить строк: {n}", n=plan.unresolved))
        return ", ".join(parts) or tr("готово")

    def _line_item(self, plan: LinePlan, outgoing: bool, goods: bool = False) -> QTreeWidgetItem:
        """`goods`: a return's line, an item only."""
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
                "",
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
            plan.item_id is None
            if goods
            else plan.item_id is None and not line.service
            if outgoing
            else plan.item_id is None and plan.account_id is None
        )
        if unresolved:
            child.setForeground(BECOMES, QColor(P.amber))
        return child

    def _becomes(self, plan: LinePlan, outgoing: bool) -> str:
        catalog = self.s.catalog
        how = {"history": tr("как в прошлый раз"), "name": tr("по названию")}.get(plan.found, "")
        if plan.item_id is not None:
            name = item_name(self.s.conn, self.s.company_id, plan.item_id)
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

    def _checked(self) -> list[InvoicePlan]:
        result = []
        for index in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(index)
            if item is not None and item.checkState(0) == Qt.CheckState.Checked:
                result.append(item.data(0, Qt.ItemDataRole.UserRole))
        return result

    def outcome(self) -> str:
        """What the import did, for the toast after it."""
        parts = []
        if self.created:
            parts.append(tr("Создано черновиков: {n} — проверьте и проведите", n=len(self.created)))
        if self.attached:
            parts.append(tr("e-qaimə дописана в покупки: {n}", n=len(self.attached)))
        return " · ".join(parts)

    def _show_count(self) -> None:
        chosen = self._checked()
        self.import_button.setEnabled(bool(chosen))
        attached = sum(1 for p in chosen if p.attach_to is not None)
        text = tr("Создать черновики: {n}", n=len(chosen) - attached)
        if attached:  # written into waiting purchases (D119)
            text = tr(
                "Загрузить: черновиков {n}, в покупки {m}", n=len(chosen) - attached, m=attached
            )
        self.import_button.setText(text)
        if not self.plans and self.import_button.isVisibleTo(self):
            say(self.status, tr("На портале за этот период e-qaimə нет."))
        elif self.plans:
            new = sum(1 for p in self.plans if p.importable)
            self.status.setText(
                tr(
                    "E-qaimə: {total}, новых: {new}. Строки, отмеченные цветом, — без товара или "
                    "счёта: выберите их в черновике.",
                    total=len(self.plans),
                    new=new,
                )
            )

    # ---- counterparties --------------------------------------------------------------

    def _show_parties(self) -> None:
        self.parties.setRowCount(len(self.new_parties))
        for row, party in enumerate(self.new_parties):
            cells = [party.tax_id, party.portal_name, party.name, str(party.invoices)]
            for column, text in enumerate(cells):
                cell = QTableWidgetItem(text)
                if column != 2:  # only the name is the user's
                    cell.setFlags(cell.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    cell.setForeground(QColor(P.secondary))
                if column == 3:
                    cell.setTextAlignment(
                        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                    )
                self.parties.setItem(row, column, cell)
        shown = bool(self.new_parties)
        for widget in (self.parties_title, self.add_parties_button, self.parties):
            widget.setVisible(shown)
        self.parties_title.setText(tr("Новые контрагенты: {n}", n=len(self.new_parties)))

    def _show_renames(self) -> None:
        self.renames.setRowCount(len(self.renamed))
        for row, item in enumerate(self.renamed):
            cells = [
                item.tax_id,
                item.old_legal_name,
                item.new_legal_name,
                item.current_name,
                item.name,
            ]
            for column, text in enumerate(cells):
                cell = QTableWidgetItem(text)
                if column == 0:  # ticked: rename here
                    cell.setFlags(
                        (cell.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                        & ~Qt.ItemFlag.ItemIsEditable
                    )
                    cell.setCheckState(
                        Qt.CheckState.Checked if item.rename else Qt.CheckState.Unchecked
                    )
                elif column != 4:
                    cell.setFlags(cell.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    cell.setForeground(QColor(P.secondary))
                self.renames.setItem(row, column, cell)
        shown = bool(self.renamed)
        for widget in (self.renames_title, self.renames_button, self.renames):
            widget.setVisible(shown)
        self.renames_title.setText(tr("Название изменилось: {n}", n=len(self.renamed)))

    def apply_renames(self) -> None:
        """Ticked rows are renamed here (to the typed name); every row remembers the new
        official name, so it is not asked about again."""
        for row, item in enumerate(self.renamed):
            tick, name = self.renames.item(row, 0), self.renames.item(row, 4)
            item.rename = tick is not None and tick.checkState() == Qt.CheckState.Checked
            item.name = " ".join((name.text() if name else "").split()) or item.current_name
        try:
            apply_renames(self.s.ledger, self.s.company_id, self.renamed)
        except LedgerError as exc:
            self.status.setText(str(exc))
            return
        self.s.catalog.reload()
        renamed = sum(1 for item in self.renamed if item.rename)
        self.s.notify(tr("Переименовано контрагентов: {n}", n=renamed))
        self.renamed = []
        self._show_renames()

    def party_names(self) -> dict[str, str]:
        """key -> the name typed in the table (the suggestion if left as it is)."""
        names = {}
        for row, party in enumerate(self.new_parties):
            cell = self.parties.item(row, 2)
            text = " ".join((cell.text() if cell else "").split())
            names[party.key] = text or party.name
        return names

    def add_parties(self) -> None:
        """Add the new counterparties alone (no documents), then show the list again."""
        names = self.party_names()
        for party in self.new_parties:
            party.name = names[party.key]
        try:
            ids = add_counterparties(self.s.ledger, self.s.company_id, self.new_parties)
        except LedgerError as exc:
            self.status.setText(str(exc))
            return
        self.s.catalog.reload()
        self.s.notify(tr("Добавлено контрагентов: {n}", n=len(ids)))
        checked = {plan.invoice.portal_id for plan in self._checked()}
        self.show_invoices(self.invoices)
        for index in range(self.tree.topLevelItemCount()):  # keep what was ticked
            item = self.tree.topLevelItem(index)
            if item is None:
                continue
            plan: InvoicePlan = item.data(0, Qt.ItemDataRole.UserRole)
            if plan.importable and plan.invoice.portal_id not in checked:
                item.setCheckState(0, Qt.CheckState.Unchecked)

    # ---- drafts --------------------------------------------------------------------

    def create_drafts(self) -> None:
        chosen = self._checked()
        if not chosen:
            return
        try:
            self.created = import_drafts(
                self.inventory, self.s.company_id, chosen, self.party_names()
            )
        except LedgerError as exc:
            self.status.setText(str(exc))
            return
        self.attached = [p.attach_to.document_id for p in chosen if p.attach_to is not None]
        self.s.catalog.reload()  # new counterparties
        self.accept()
