"""Inventory catalogs: units, items, warehouses and kinds of landed cost."""

from __future__ import annotations

from modern_gl.application.common import insert, where_used
from modern_gl.application.inventory.base import InventoryBase
from modern_gl.application.inventory.model import QUANTITY_SCALE
from modern_gl.domain.errors import ValidationError
from modern_gl.i18n import tr
from modern_gl.infrastructure.db import IntegrityError, transaction


class CatalogCommands(InventoryBase):
    def add_unit(self, company_id: int, code: str, name: str, precision: int = 3) -> int:
        code, name = code.strip(), name.strip()
        if not code or not name:
            raise ValidationError(tr("код и название единицы обязательны"))
        if not 0 <= precision <= QUANTITY_SCALE:
            raise ValidationError(tr("точность количества должна быть от 0 до 6"))
        with transaction(self.conn):
            self._company(company_id)
            try:
                unit_id = insert(
                    self.conn,
                    "INSERT INTO inventory_units (company_id, code, name, precision) "
                    "VALUES (?, ?, ?, ?)",
                    (company_id, code, name, precision),
                )
            except IntegrityError as exc:
                raise ValidationError(tr("единица с таким кодом уже существует")) from exc
            self._audit(company_id, "inventory_unit", unit_id, "create", {"code": code})
        return unit_id

    def add_item(
        self,
        company_id: int,
        name: str,
        unit_id: int,
        inventory_account_id: int,
        code: str | None = None,
        *,
        subconto_value_id: int | None = None,
        group_id: int | None = None,
    ) -> int:
        """Create an item and its shared `item` subconto value (or adopt an existing one);
        a new value goes into the group `group_id` of the item directory."""
        name = name.strip()
        if not name:
            raise ValidationError(tr("название товара обязательно"))
        with transaction(self.conn):
            self._unit(company_id, unit_id)
            self._validate_inventory_account(company_id, inventory_account_id)
            item_kind = self._kind_id(company_id, "item")
            if subconto_value_id is None:
                subconto_value_id = self.ledger.add_subconto_value(
                    company_id, item_kind, name, (code or "").strip() or None, parent_id=group_id
                )
            else:
                value = self._subconto_value(company_id, subconto_value_id)
                if value["kind_id"] != item_kind or value["is_group"]:
                    raise ValidationError(tr("элемент относится не к справочнику товаров"))
            try:
                item_id = insert(
                    self.conn,
                    "INSERT INTO inventory_items "
                    "(company_id, subconto_value_id, unit_id, inventory_account_id) "
                    "VALUES (?, ?, ?, ?)",
                    (company_id, subconto_value_id, unit_id, inventory_account_id),
                )
            except IntegrityError as exc:
                raise ValidationError(tr("этот товар уже подключён к складскому учёту")) from exc
            self._audit(
                company_id,
                "inventory_item",
                item_id,
                "create",
                {"subconto_value_id": subconto_value_id, "name": name},
            )
        return item_id

    def update_item(
        self, company_id: int, item_id: int, unit_id: int, inventory_account_id: int
    ) -> None:
        """Another unit or stock account, while no document has the item: its quantities
        and postings were made in the old ones. The name and group change in the directory."""
        with transaction(self.conn):
            item = self._item(company_id, item_id)
            if (item["unit_id"], item["inventory_account_id"]) == (unit_id, inventory_account_id):
                return
            self._unit(company_id, unit_id)
            self._validate_inventory_account(company_id, inventory_account_id)
            reason = where_used(self.conn, company_id, "inventory_items", item_id)
            if reason is not None:
                raise ValidationError(
                    tr("единицу и счёт товара менять нельзя: {reason}", reason=reason)
                )
            self.conn.execute(
                "UPDATE inventory_items SET unit_id = ?, inventory_account_id = ? WHERE id = ?",
                (unit_id, inventory_account_id, item_id),
            )
            self._audit(
                company_id,
                "inventory_item",
                item_id,
                "update",
                {
                    "before": [item["unit_id"], item["inventory_account_id"]],
                    "after": [unit_id, inventory_account_id],
                },
            )

    def delete_value(self, company_id: int, value_id: int) -> None:
        """Delete a directory element; an item or a warehouse with it, when no document
        has it (`Ledger.delete_subconto_value` checks the rest)."""
        with transaction(self.conn):
            value = self._subconto_value(company_id, value_id)
            for table in ("inventory_items", "warehouses"):
                row = self.conn.execute(
                    f"SELECT id FROM {table} WHERE company_id = ? AND subconto_value_id = ?",
                    (company_id, value_id),
                ).fetchone()
                if row is None:
                    continue
                reason = where_used(self.conn, company_id, table, row["id"])
                if reason is not None:
                    raise ValidationError(
                        tr(
                            "«{name}» нельзя удалить: {reason}. Его можно скрыть.",
                            name=value["name"],
                            reason=reason,
                        )
                    )
                self.conn.execute(f"DELETE FROM {table} WHERE id = ?", (row["id"],))
            self.ledger.delete_subconto_value(company_id, value_id)

    def add_warehouse(
        self,
        company_id: int,
        name: str,
        code: str | None = None,
        *,
        subconto_value_id: int | None = None,
    ) -> int:
        """Create a warehouse and its shared `warehouse` subconto value."""
        name = name.strip()
        if not name:
            raise ValidationError(tr("название склада обязательно"))
        with transaction(self.conn):
            warehouse_kind = self._kind_id(company_id, "warehouse")
            if subconto_value_id is None:
                subconto_value_id = self.ledger.add_subconto_value(
                    company_id, warehouse_kind, name, (code or "").strip() or None
                )
            else:
                value = self._subconto_value(company_id, subconto_value_id)
                if value["kind_id"] != warehouse_kind:
                    raise ValidationError(tr("элемент относится не к справочнику складов"))
            try:
                warehouse_id = insert(
                    self.conn,
                    "INSERT INTO warehouses (company_id, subconto_value_id) VALUES (?, ?)",
                    (company_id, subconto_value_id),
                )
            except IntegrityError as exc:
                raise ValidationError(tr("этот склад уже подключён к складскому учёту")) from exc
            self._audit(
                company_id,
                "warehouse",
                warehouse_id,
                "create",
                {"subconto_value_id": subconto_value_id, "name": name},
            )
        return warehouse_id

    def add_landed_cost_type(self, company_id: int, name: str, code: str | None = None) -> int:
        """Add a reporting category such as freight, customs, insurance or brokerage."""
        name = name.strip()
        code = (code or "").strip() or None
        if not name:
            raise ValidationError(tr("название вида расходов обязательно"))
        with transaction(self.conn):
            self._company(company_id)
            try:
                type_id = insert(
                    self.conn,
                    "INSERT INTO landed_cost_types (company_id, code, name) VALUES (?, ?, ?)",
                    (company_id, code, name),
                )
            except IntegrityError as exc:
                raise ValidationError(tr("такой вид дополнительных расходов уже есть")) from exc
            self._audit(
                company_id,
                "landed_cost_type",
                type_id,
                "create",
                {"code": code, "name": name},
            )
        return type_id
