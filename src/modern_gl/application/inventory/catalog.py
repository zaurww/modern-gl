"""Inventory catalogs: units, items, warehouses and kinds of landed cost."""

from __future__ import annotations

from collections.abc import Collection, Iterator, Mapping
from contextlib import contextmanager
from decimal import Decimal

from modern_gl.application.common import where_used
from modern_gl.application.inventory.amounts import blank, to_quantity
from modern_gl.application.inventory.base import InventoryBase
from modern_gl.application.inventory.model import (
    INCOMING_REASONS,
    QUANTITY_SCALE,
    NewItem,
    UsualUnit,
)
from modern_gl.domain.accounts import FX_GAIN
from modern_gl.domain.errors import ValidationError
from modern_gl.i18n import fold, tr
from modern_gl.infrastructure.db import IntegrityError, insert, transaction


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

    def edit_item(
        self,
        company_id: int,
        item_id: int,
        name: str,
        code: str | None,
        group_id: int | None,
        unit_id: int,
        inventory_account_id: int,
        min_quantity: str | int | Decimal | None = None,
    ) -> None:
        """The item's window saved: its name, code and group in the directory, its unit
        and stock account, its minimum stock — all or nothing."""
        with transaction(self.conn):
            self.set_min_quantity(company_id, item_id, min_quantity)
            value_id = self._item(company_id, item_id)["subconto_value_id"]
            self.ledger.update_subconto_value(company_id, value_id, name, code)
            self.ledger.set_subconto_value_parent(company_id, value_id, group_id)
            self.update_item(company_id, item_id, unit_id, inventory_account_id)

    def update_item(
        self, company_id: int, item_id: int, unit_id: int, inventory_account_id: int
    ) -> None:
        """Another unit or stock account. The unit — while no document has the item: its
        quantities are in the old one. The account — with documents too: the warehouse
        posts them again on the new one (`_repost_item`). The name and
        group change in the directory."""
        with transaction(self.conn):
            item = self._item(company_id, item_id)
            if (item["unit_id"], item["inventory_account_id"]) == (unit_id, inventory_account_id):
                return
            self._unit(company_id, unit_id)
            self._validate_inventory_account(company_id, inventory_account_id)
            if item["unit_id"] != unit_id:
                reason = where_used(self.conn, company_id, "inventory_items", item_id)
                if reason is not None:
                    raise ValidationError(
                        tr("единицу товара менять нельзя: {reason}", reason=reason)
                    )
            self.conn.execute(
                "UPDATE inventory_items SET unit_id = ?, inventory_account_id = ? "
                "WHERE company_id = ? AND id = ?",
                (unit_id, inventory_account_id, company_id, item_id),
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
            if item["inventory_account_id"] != inventory_account_id:
                self._repost_item(company_id, item_id)

    def set_item_account(self, company_id: int, item_id: int, inventory_account_id: int) -> None:
        """Another stock account of the item, picked on a purchase line: its unit stays."""
        unit_id = self._item(company_id, item_id)["unit_id"]
        self.update_item(company_id, item_id, unit_id, inventory_account_id)

    def set_min_quantity(
        self, company_id: int, item_id: int, quantity: str | int | Decimal | None
    ) -> None:
        """The item's minimum stock (on all warehouses together); empty or 0 — none."""
        minimum = None if quantity is None or blank(quantity) else to_quantity(quantity)
        if minimum is not None and minimum < 0:
            raise ValidationError(tr("минимальный остаток не может быть меньше нуля"))
        with transaction(self.conn):
            item = self._item(company_id, item_id)
            minimum = minimum or None
            if item["min_quantity"] == minimum:
                return
            self.conn.execute(
                "UPDATE inventory_items SET min_quantity = ? WHERE company_id = ? AND id = ?",
                (minimum, company_id, item_id),
            )
            self._audit(
                company_id,
                "inventory_item",
                item_id,
                "set_minimum",
                {"before": item["min_quantity"], "after": minimum},
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
                self.conn.execute(
                    f"DELETE FROM {table} WHERE company_id = ? AND id = ?",
                    (company_id, row["id"]),
                )
            self.ledger.delete_subconto_value(company_id, value_id)

    def unused_items(self, company_id: int) -> list[tuple[int, str]]:
        """(directory element, name) of the items nothing refers to, by name: no document,
        draft or posting has them. One pass for a window, not for a list on a page."""
        rows = self.conn.execute(
            "SELECT i.id, v.id AS value_id, v.name FROM inventory_items i "
            "JOIN subconto_values v ON v.company_id = i.company_id "
            "AND v.id = i.subconto_value_id WHERE i.company_id = ? ORDER BY v.name",
            (company_id,),
        ).fetchall()
        return [
            (row["value_id"], row["name"])
            for row in rows
            if where_used(self.conn, company_id, "inventory_items", row["id"]) is None
            and where_used(
                self.conn,
                company_id,
                "subconto_values",
                row["value_id"],
                ignore=("inventory_items",),
            )
            is None
        ]

    def delete_values(self, company_id: int, value_ids: Collection[int]) -> None:
        """Several elements at once: all of them or, if one is used, none."""
        with transaction(self.conn):
            for value_id in value_ids:
                self.delete_value(company_id, value_id)

    @contextmanager
    def adding_items(self, company_id: int, new: Mapping[int, NewItem]) -> Iterator[dict[int, int]]:
        """A document saved with the new items of its lines, in one transaction: `new` — a
        stand-in id of the form -> the item; the block gets stand-in -> item. An error in
        the block takes the items back: no document, no items. A name an active item has
        by now takes that item."""
        with transaction(self.conn):
            known = self._items_by_name(company_id)
            made = {}
            for stand_in, item in new.items():
                key = fold(item.name.strip())
                if key not in known:
                    unit = self._unit_of(company_id, item.unit)
                    known[key] = self.add_new_item(company_id, item.name, unit, item.account_id)
                made[stand_in] = known[key]
            yield made

    def _unit_of(self, company_id: int, unit: int | str) -> int:
        """A unit by its id, its code or name; a new one if there is none."""
        if isinstance(unit, int):
            return unit
        needle = fold(unit.strip())
        for row in self.conn.execute(
            "SELECT id, code, name FROM inventory_units WHERE company_id = ? ORDER BY id",
            (company_id,),
        ).fetchall():
            if needle in {fold(row["code"]), fold(row["name"])}:
                return row["id"]
        return self.add_unit(company_id, unit, unit)

    def _items_by_name(self, company_id: int) -> dict[str, int]:
        return {
            fold(row["name"]): row["id"]
            for row in self.conn.execute(
                "SELECT i.id, v.name FROM inventory_items i "
                "JOIN subconto_values v ON v.company_id = i.company_id "
                "AND v.id = i.subconto_value_id WHERE i.company_id = ? AND v.active = 1",
                (company_id,),
            )
        }

    def add_new_item(
        self,
        company_id: int,
        name: str,
        unit: int | UsualUnit,
        inventory_account_id: int,
        code: str | None = None,
        *,
        group_id: int | None = None,
        first_warehouse: str | None = None,
        min_quantity: str | int | Decimal | None = None,
    ) -> int:
        """The item dialog's «Сохранить», in one transaction: a usual unit is taken by its
        code or made, and a company with no warehouse yet gets `first_warehouse` — a
        beginner's first item needs nothing set up before it."""
        with transaction(self.conn):
            unit_id = unit if isinstance(unit, int) else self._usual_unit(company_id, unit)
            item_id = self.add_item(
                company_id, name, unit_id, inventory_account_id, code, group_id=group_id
            )
            has_warehouse = self.conn.execute(
                "SELECT 1 FROM warehouses WHERE company_id = ? LIMIT 1", (company_id,)
            ).fetchone()
            if first_warehouse and has_warehouse is None:
                self.add_warehouse(company_id, first_warehouse)
            self.set_min_quantity(company_id, item_id, min_quantity)
        return item_id

    def add_named_items(
        self,
        company_id: int,
        names: list[str],
        unit: int | UsualUnit,
        inventory_account_id: int,
        *,
        first_warehouse: str | None = None,
    ) -> list[int]:
        """Purchase lines made goods, in one transaction: an item for each name, in the
        same order. A name an active item has already takes that item, the same name twice
        is one item — nothing is added twice."""
        with transaction(self.conn):
            known = self._items_by_name(company_id)
            result = []
            for name in names:
                key = fold(name.strip())
                if key not in known:
                    known[key] = self.add_new_item(
                        company_id,
                        name,
                        unit,
                        inventory_account_id,
                        first_warehouse=first_warehouse,
                    )
                result.append(known[key])
        return result

    def _usual_unit(self, company_id: int, unit: UsualUnit) -> int:
        row = self.conn.execute(
            "SELECT id FROM inventory_units WHERE company_id = ? AND code = ?",
            (company_id, unit.code.strip()),
        ).fetchone()
        if row is not None:
            return row["id"]
        return self.add_unit(company_id, unit.code, unit.name, unit.precision)

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

    def incoming_account(self, company_id: int, reason: str) -> int | None:
        """The account a mədaxil of this reason credits (D91): the one chosen in the
        settings; a surplus or a gift without one — the other income (FX_GAIN's account)."""
        role = INCOMING_REASONS[reason][1]
        account = self.ledger.account_role(company_id, role)
        if account is None and reason in ("surplus", "gift"):
            account = self.ledger.account_role(company_id, FX_GAIN)
        return account
