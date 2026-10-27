"""The supplier of a purchase, the customer of a sale — once, in the header, as every
program for it asks (1C, Zoho, ERPNext): the lines take it and do not show their account
and subconto. Lines with different ones show their own («Разные по строкам»)."""

from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout

from modern_gl.desktop.inventory_document_page.form import InventoryDocumentForm
from modern_gl.desktop.new_cell_value import add_typed_value
from modern_gl.desktop.pick import PickBox
from modern_gl.desktop.widgets import button
from modern_gl.domain.errors import LedgerError
from modern_gl.i18n import tr

CAPTIONS = {
    "receipt": "Поставщик",
    "sale": "Покупатель",
    "purchase_return": "Поставщик",
    "sale_return": "Покупатель",
}


class PartyPart(InventoryDocumentForm):
    def _build_party(self, root: QVBoxLayout) -> None:
        row = QHBoxLayout()
        row.setSpacing(8)
        self.party_caption = QLabel(tr(CAPTIONS.get(self.doc_type, "Поставщик")))
        self.party_caption.setObjectName("secondary")
        self.party = PickBox(tr("кто — название или VÖEN"))
        self.party.setFixedWidth(300)
        self.party.can_add = True  # a new one is added right here, as in a cell
        self.contract_caption = QLabel(tr("Договор"))
        self.contract_caption.setObjectName("secondary")
        self.contract = PickBox(tr("без договора"))
        self.contract.setFixedWidth(220)
        self.contract.can_add = True
        self.by_lines_button = button(
            tr("Разные по строкам"),
            "flat",
            tr("У строк разные поставщики или счета расчётов: показать их в каждой строке"),
        )
        for widget in (
            self.party_caption,
            self.party,
            self.contract_caption,
            self.contract,
            self.by_lines_button,
        ):
            row.addWidget(widget)
        row.addStretch(1)
        root.addLayout(row)
        self.party_row = row
        self.party.activated.connect(lambda _i: self._party_chosen())
        self.party.added.connect(self._party_added)
        self.contract.activated.connect(lambda _i: self._party_chosen(keep_contract=True))
        self.contract.added.connect(self._contract_added)
        self.by_lines_button.clicked.connect(self._show_by_lines)

    # ---- where the party sits on its account -----------------------------------------

    def _positions(self) -> tuple[int | None, int | None]:
        """(counterparty, contract) positions on the header's account; None — none."""
        account_id = self.model.party_account
        if account_id is None:
            return None, None
        catalog = self.s.catalog
        account = catalog.accounts[account_id]
        party = next(
            (i for i, kind in enumerate(account.sc_kinds) if kind and catalog.has_tax_id(kind)),
            None,
        )
        contract = next(
            (
                i
                for i in range(3)
                if party is not None and i != party and catalog.owner_slot(account, i) == party
            ),
            None,
        )
        return party, contract

    def _kind(self, position: int | None) -> int | None:
        account_id = self.model.party_account
        if position is None or account_id is None:
            return None
        return self.s.catalog.accounts[account_id].sc_kinds[position]

    # ---- showing ---------------------------------------------------------------------

    def _show_party(self) -> None:
        """The header's party as the lines have it; the row is there only for a purchase
        or a sale whose account takes a counterparty."""
        party, contract = self._positions()
        shown = self.model.has_party() and party is not None
        for widget in (self.party_caption, self.party, self.contract_caption, self.contract):
            widget.setVisible(shown)
        self.by_lines_button.setVisible(shown and self.model.party_in_header())
        if not shown or party is None:
            return
        read_only = self.model.read_only
        self.party.setEnabled(not read_only)
        self.contract.setEnabled(not read_only)
        chosen = None if self.model.by_lines else self.model.party_subconto[party]
        self._fill(self.party, self._kind(party), None, chosen)
        self.party.setPlaceholderText(
            tr("разные — в строках") if self.model.by_lines else tr("кто — название или VÖEN")
        )
        has_contract = contract is not None
        self.contract_caption.setVisible(has_contract)
        self.contract.setVisible(has_contract)
        if has_contract:
            value = None if self.model.by_lines else self.model.party_subconto[contract]
            self._fill(self.contract, self._kind(contract), chosen, value)

    def _fill(self, box: PickBox, kind_id: int | None, owner: int | None, chosen) -> None:
        box.clear()
        if kind_id is not None:
            for value in self.s.catalog.values(kind_id, owner):
                box.addItem(value.label, value.id, value.name)
        box.setCurrentIndex(box.findData(chosen) if chosen is not None else -1)

    # ---- choosing ---------------------------------------------------------------------

    def _party_chosen(self, keep_contract: bool = False) -> None:
        party, contract = self._positions()
        if party is None:
            return
        subconto: list[int | None] = [None, None, None]
        subconto[party] = self.party.currentData()
        if contract is not None and keep_contract:
            subconto[contract] = self.contract.currentData()
        self.model.set_party(self.model.party_account, subconto)
        self._show_party()
        self.table.configure_columns()
        self.expense_columns = self._expense_columns()
        self._changed()

    def _party_added(self, name: str) -> None:
        self._add_value(self._positions()[0], name, None, self.party)

    def _contract_added(self, name: str) -> None:
        self._add_value(self._positions()[1], name, self.party.currentData(), self.contract)

    def _add_value(self, position: int | None, name: str, owner, box: PickBox) -> None:
        kind_id = self._kind(position)
        if kind_id is None:
            return
        try:
            value_id = add_typed_value(self.s, kind_id, name, owner)
        except LedgerError as exc:
            self.show_error(str(exc))
            return
        box.addItem(name, value_id)
        box.setCurrentIndex(box.findData(value_id))
        self._party_chosen(keep_contract=box is self.contract)

    def _show_by_lines(self) -> None:
        """Each line its own supplier (customer) and account: the columns are shown."""
        self.model.by_lines = True
        self.table.configure_columns()
        self.expense_columns = self._expense_columns()
        self._show_party()
