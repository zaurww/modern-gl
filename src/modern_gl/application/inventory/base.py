"""State and lookups shared by every group of inventory use cases."""

from __future__ import annotations

from collections.abc import Sequence

from modern_gl.application.common import company_row, write_audit
from modern_gl.application.ledger import Ledger
from modern_gl.domain.errors import NotFoundError, PeriodClosedError, ValidationError
from modern_gl.i18n import tr
from modern_gl.infrastructure.db import Connection, Row


class InventoryBase:
    def __init__(self, conn: Connection, actor: str = "local") -> None:
        self.conn = conn
        self.actor = actor
        self.ledger = Ledger(conn, actor=actor)

    def _company(self, company_id: int) -> Row:
        return company_row(self.conn, company_id)

    def _unit(self, company_id: int, unit_id: int) -> Row:
        row = self.conn.execute(
            "SELECT * FROM inventory_units WHERE company_id = ? AND id = ?",
            (company_id, unit_id),
        ).fetchone()
        if row is None:
            raise NotFoundError(tr("единица измерения не найдена"))
        return row

    def _item(self, company_id: int, item_id: int) -> Row:
        row = self.conn.execute(
            """
            SELECT i.*, v.name, v.code, v.active, u.precision AS unit_precision,
                   u.name AS unit_name, u.code AS unit_code
            FROM inventory_items i
            JOIN subconto_values v ON v.id = i.subconto_value_id
            JOIN inventory_units u ON u.id = i.unit_id
            WHERE i.company_id = ? AND i.id = ?
            """,
            (company_id, item_id),
        ).fetchone()
        if row is None:
            raise NotFoundError(tr("товар не найден"))
        if not row["active"]:
            raise ValidationError(tr("товар скрыт"))
        return row

    def _warehouse(self, company_id: int, warehouse_id: int) -> Row:
        row = self.conn.execute(
            """
            SELECT w.*, v.name, v.code, v.active
            FROM warehouses w JOIN subconto_values v ON v.id = w.subconto_value_id
            WHERE w.company_id = ? AND w.id = ?
            """,
            (company_id, warehouse_id),
        ).fetchone()
        if row is None:
            raise NotFoundError(tr("склад не найден"))
        if not row["active"]:
            raise ValidationError(tr("склад скрыт"))
        return row

    def _cost_type(self, company_id: int, type_id: int) -> Row:
        row = self.conn.execute(
            "SELECT * FROM landed_cost_types WHERE company_id = ? AND id = ? AND active = 1",
            (company_id, type_id),
        ).fetchone()
        if row is None:
            raise NotFoundError(tr("вид дополнительных расходов не найден"))
        return row

    def _account(self, company_id: int, account_id: int) -> Row:
        row = self.conn.execute(
            "SELECT * FROM accounts WHERE company_id = ? AND id = ?",
            (company_id, account_id),
        ).fetchone()
        if row is None:
            raise NotFoundError(tr("счёт не найден"))
        return row

    def _subconto_value(self, company_id: int, value_id: int) -> Row:
        row = self.conn.execute(
            "SELECT * FROM subconto_values WHERE company_id = ? AND id = ?",
            (company_id, value_id),
        ).fetchone()
        if row is None:
            raise NotFoundError(tr("элемент справочника не найден"))
        return row

    def _kind_id(self, company_id: int, code: str) -> int:
        row = self.conn.execute(
            "SELECT id FROM subconto_kinds WHERE company_id = ? AND code = ?",
            (company_id, code),
        ).fetchone()
        if row is None:
            raise ValidationError(tr("не найден справочник {code}", code=code))
        return row["id"]

    def _document(self, company_id: int, document_id: int) -> Row:
        row = self.conn.execute(
            "SELECT * FROM inventory_documents WHERE company_id = ? AND id = ?",
            (company_id, document_id),
        ).fetchone()
        if row is None:
            raise NotFoundError(tr("складской документ не найден"))
        return row

    def _receipt_line(self, company_id: int, line_id: int) -> Row:
        row = self.conn.execute(
            """
            SELECT l.* FROM inventory_lines l
            JOIN inventory_documents d ON d.id = l.document_id
            WHERE l.company_id = ? AND l.id = ? AND d.status = 'posted'
              AND d.doc_type IN ('opening', 'receipt', 'incoming')
            """,
            (company_id, line_id),
        ).fetchone()
        if row is None:
            raise ValidationError(tr("строка поступления не найдена или не проведена"))
        return row

    def _charges(self, document_id: int) -> list[Row]:
        return self.conn.execute(
            "SELECT * FROM landed_cost_charges WHERE document_id = ? ORDER BY line_no",
            (document_id,),
        ).fetchall()

    def _currency_id(self, company_id: int, currency_id: int) -> int:
        row = self.conn.execute(
            "SELECT id FROM currencies WHERE company_id = ? AND id = ?", (company_id, currency_id)
        ).fetchone()
        if row is None:
            raise NotFoundError(tr("валюта не найдена"))
        return row["id"]

    def _closed(self, doc: Row) -> bool:
        closed = self._company(doc["company_id"])["closed_through"]
        return closed is not None and doc["doc_date"] <= closed

    def _require_inventory_draft(self, company_id: int, document_id: int) -> Row:
        doc = self._document(company_id, document_id)
        if doc["status"] != "draft":
            raise ValidationError(tr("сначала отмените проведение складского документа"))
        return doc

    def _require_open_period(self, doc: Row) -> None:
        closed = self._company(doc["company_id"])["closed_through"]
        if closed is not None and doc["doc_date"] <= closed:
            raise PeriodClosedError(
                tr(
                    "складской документ №{number} от {date}: период закрыт по {closed}",
                    number=doc["number"],
                    date=doc["doc_date"],
                    closed=closed,
                )
            )

    def _account_kind_ids(self, account: Row) -> tuple[int | None, ...]:
        return tuple(account[f"sc{position}_kind_id"] for position in range(1, 4))

    def _account_kind_codes(
        self, company_id: int, account: Row
    ) -> tuple[str | None, str | None, str | None]:
        result: list[str | None] = []
        for position in range(1, 4):
            kind_id = account[f"sc{position}_kind_id"]
            if kind_id is None:
                result.append(None)
                continue
            row = self.conn.execute(
                "SELECT code FROM subconto_kinds WHERE company_id = ? AND id = ?",
                (company_id, kind_id),
            ).fetchone()
            result.append(row["code"] if row else None)
        return tuple(result)  # type: ignore[return-value]

    def _by_kind(
        self, company_id: int, account_id: int, values: Sequence[int | None]
    ) -> tuple[int | None, ...]:
        """The account's subconto filled from `values` of the same kinds."""
        by_kind = {
            self._subconto_value(company_id, value_id)["kind_id"]: value_id
            for value_id in values
            if value_id is not None
        }
        kinds = self._account_kind_ids(self._account(company_id, account_id))
        return tuple(None if kind is None else by_kind.get(kind) for kind in kinds)

    def _inventory_subconto(
        self, company_id: int, item: Row, warehouse: Row
    ) -> tuple[int | None, ...]:
        account = self._account(company_id, item["inventory_account_id"])
        kind_codes = self._account_kind_codes(company_id, account)
        values: list[int | None] = []
        for code in kind_codes:
            if code == "item":
                values.append(item["subconto_value_id"])
            elif code == "warehouse":
                values.append(warehouse["subconto_value_id"])
            elif code is None:
                values.append(None)
            else:
                raise ValidationError(
                    tr(
                        "счёт {account} требует дополнительное субконто {kind}",
                        account=account["code"] or account["name"],
                        kind=code,
                    )
                )
        while values and values[-1] is None:
            values.pop()
        return tuple(values)

    def _validate_inventory_account(self, company_id: int, account_id: int) -> None:
        account = self._account(company_id, account_id)
        if account["is_group"] or not account["active"]:
            raise ValidationError(tr("складской счёт должен быть активным счётом проводок"))
        codes = {code for code in self._account_kind_codes(company_id, account) if code}
        if not {"item", "warehouse"}.issubset(codes):
            raise ValidationError(tr("на складском счёте нужны субконто Товар и Склад"))

    def _check_not_stock(self, company_id: int, account_id: int, line_no: int) -> None:
        """A line without an item never goes to a stock account: the GL would show goods
        the warehouse does not have."""
        account = self._account(company_id, account_id)
        if {"item", "warehouse"} <= set(self._account_kind_codes(company_id, account)):
            raise ValidationError(
                tr(
                    "строка {line}: счёт {account} складской — выберите товар в колонке "
                    "«Товар», тогда он придёт на склад",
                    line=line_no,
                    account=account["code"] or account["name"],
                )
            )

    def _snapshot(self, doc: Row) -> dict:
        lines = [
            {key: row[key] for key in row.keys() if key not in {"company_id", "document_id"}}
            for row in self.conn.execute(
                "SELECT * FROM inventory_lines WHERE document_id = ? ORDER BY line_no",
                (doc["id"],),
            )
        ]
        return {
            "number": doc["number"],
            "doc_date": doc["doc_date"],
            "doc_type": doc["doc_type"],
            "memo": doc["memo"],
            "landed_cost_type_id": doc["landed_cost_type_id"],
            "gl_document_id": doc["gl_document_id"],
            "vat_rate": doc["vat_rate"],
            "allocation_method": doc["allocation_method"],
            "currency_id": doc["currency_id"],
            "currency_rate": doc["currency_rate"],
            "invoice": doc["invoice"],
            "invoice_kind": doc["invoice_kind"],
            "expense_date": doc["expense_date"],
            "accrual_document_id": doc["accrual_document_id"],
            "lines": lines,
            "charges": [
                {key: row[key] for key in row.keys() if key not in {"company_id", "document_id"}}
                for row in self._charges(doc["id"])
            ],
        }

    def _audit(
        self, company_id: int, entity: str, entity_id: int, action: str, details: dict
    ) -> None:
        write_audit(self.conn, company_id, self.actor, entity, entity_id, action, details)
