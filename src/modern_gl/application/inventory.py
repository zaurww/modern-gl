"""Quantitative/value inventory use cases and landed-cost allocation.

Quantities live in a separate immutable movement register. Every posted inventory
document creates an ordinary GL document in the same SQLite transaction.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation

from modern_gl.application.ledger import Ledger, PostingInput
from modern_gl.domain.dates import iso_date
from modern_gl.domain.errors import NotFoundError, PeriodClosedError, ValidationError
from modern_gl.domain.money import SCALE as MONEY_SCALE
from modern_gl.domain.money import to_minor
from modern_gl.i18n import tr
from modern_gl.infrastructure.db import transaction

QUANTITY_SCALE = 6
QUANTITY_FACTOR = 10**QUANTITY_SCALE
_QUANTITY_QUANTUM = Decimal(1).scaleb(-QUANTITY_SCALE)


@dataclass(frozen=True)
class ReceiptLine:
    item_id: int
    warehouse_id: int
    quantity: str | int | Decimal
    amount: str | int | Decimal
    memo: str = ""


@dataclass(frozen=True)
class IssueLine:
    item_id: int
    warehouse_id: int
    quantity: str | int | Decimal
    expense_account_id: int
    expense_subconto: Sequence[int | None] = ()
    memo: str = ""


@dataclass(frozen=True)
class TransferLine:
    item_id: int
    from_warehouse_id: int
    to_warehouse_id: int
    quantity: str | int | Decimal
    memo: str = ""


def to_quantity(value: str | int | Decimal) -> int:
    """Convert a user quantity to millionths of a base unit, without float rounding."""
    if isinstance(value, bool) or isinstance(value, float):
        raise TypeError("quantities must be str, int or Decimal, never float")
    if isinstance(value, str):
        value = value.strip().replace(" ", "").replace(" ", "").replace(",", ".")
    try:
        result = Decimal(value)
    except InvalidOperation:
        raise ValueError(tr("не число: {value}", value=value)) from None
    if not result.is_finite():
        raise ValueError(tr("не число: {value}", value=value))
    if result != result.quantize(_QUANTITY_QUANTUM):
        raise ValueError(
            tr("больше {n} знаков после запятой: {value}", n=QUANTITY_SCALE, value=value)
        )
    return int(result.scaleb(QUANTITY_SCALE))


def format_quantity(quantity: int, precision: int = 3) -> str:
    """Format an internal quantity without insignificant zeroes."""
    value = Decimal(quantity).scaleb(-QUANTITY_SCALE)
    text = f"{value:.{precision}f}"
    return text.rstrip("0").rstrip(".") if "." in text else text


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _money(minor: int) -> Decimal:
    """Convert stored minor units back to the exact value expected by PostingInput."""
    return Decimal(minor).scaleb(-MONEY_SCALE)


def _pad_subconto(values: Sequence[int | None]) -> tuple[int | None, int | None, int | None]:
    if len(values) > 3:
        raise ValidationError(tr("больше 3 субконто"))
    return tuple([*values, *([None] * (3 - len(values)))])  # type: ignore[return-value]


def _round_ratio(numerator: int, denominator: int) -> int:
    """Round a non-negative rational to an integer, halves away from zero."""
    if numerator < 0 or denominator <= 0:
        raise ValueError("_round_ratio expects a non-negative numerator and positive denominator")
    quotient, remainder = divmod(numerator, denominator)
    return quotient + int(remainder * 2 >= denominator)


def _allocate_minor(total: int, weights: Sequence[tuple[int, int]]) -> dict[int, int]:
    """Allocate every minor unit deterministically by largest remainder."""
    if total <= 0:
        raise ValidationError(tr("сумма должна быть положительной"))
    if not weights or any(weight < 0 for _, weight in weights):
        raise ValidationError(tr("неверная база распределения"))
    denominator = sum(weight for _, weight in weights)
    if denominator <= 0:
        raise ValidationError(tr("база распределения равна нулю"))
    result: dict[int, int] = {}
    remainders: list[tuple[int, int]] = []
    assigned = 0
    for key, weight in weights:
        value, remainder = divmod(total * weight, denominator)
        result[key] = value
        assigned += value
        remainders.append((remainder, key))
    for _, key in sorted(remainders, key=lambda pair: (-pair[0], pair[1]))[: total - assigned]:
        result[key] += 1
    return result


class Inventory:
    """Write-side API for inventory catalogs, movements and landed cost."""

    def __init__(self, conn: sqlite3.Connection, actor: str = "local") -> None:
        self.conn = conn
        self.actor = actor
        self.ledger = Ledger(conn, actor=actor)

    # ---- catalogs -----------------------------------------------------------------

    def add_unit(self, company_id: int, code: str, name: str, precision: int = 3) -> int:
        code, name = code.strip(), name.strip()
        if not code or not name:
            raise ValidationError(tr("код и название единицы обязательны"))
        if not 0 <= precision <= QUANTITY_SCALE:
            raise ValidationError(tr("точность количества должна быть от 0 до 6"))
        with transaction(self.conn):
            self._company(company_id)
            try:
                unit_id = self.conn.execute(
                    "INSERT INTO inventory_units (company_id, code, name, precision) "
                    "VALUES (?, ?, ?, ?)",
                    (company_id, code, name, precision),
                ).lastrowid
            except sqlite3.IntegrityError as exc:
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
    ) -> int:
        """Create an item and its shared `item` subconto value (or adopt an existing one)."""
        name = name.strip()
        if not name:
            raise ValidationError(tr("название товара обязательно"))
        with transaction(self.conn):
            self._unit(company_id, unit_id)
            self._validate_inventory_account(company_id, inventory_account_id)
            item_kind = self._kind_id(company_id, "item")
            if subconto_value_id is None:
                subconto_value_id = self.ledger.add_subconto_value(
                    company_id, item_kind, name, (code or "").strip() or None
                )
            else:
                value = self._subconto_value(company_id, subconto_value_id)
                if value["kind_id"] != item_kind:
                    raise ValidationError(tr("элемент относится не к справочнику товаров"))
            try:
                item_id = self.conn.execute(
                    "INSERT INTO inventory_items "
                    "(company_id, subconto_value_id, unit_id, inventory_account_id) "
                    "VALUES (?, ?, ?, ?)",
                    (company_id, subconto_value_id, unit_id, inventory_account_id),
                ).lastrowid
            except sqlite3.IntegrityError as exc:
                raise ValidationError(tr("этот товар уже подключён к складскому учёту")) from exc
            self._audit(
                company_id,
                "inventory_item",
                item_id,
                "create",
                {"subconto_value_id": subconto_value_id, "name": name},
            )
        return item_id

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
                warehouse_id = self.conn.execute(
                    "INSERT INTO warehouses (company_id, subconto_value_id) VALUES (?, ?)",
                    (company_id, subconto_value_id),
                ).lastrowid
            except sqlite3.IntegrityError as exc:
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
                type_id = self.conn.execute(
                    "INSERT INTO landed_cost_types (company_id, code, name) VALUES (?, ?, ?)",
                    (company_id, code, name),
                ).lastrowid
            except sqlite3.IntegrityError as exc:
                raise ValidationError(tr("такой вид дополнительных расходов уже есть")) from exc
            self._audit(
                company_id,
                "landed_cost_type",
                type_id,
                "create",
                {"code": code, "name": name},
            )
        return type_id

    # ---- operational documents ----------------------------------------------------

    def post_receipt(
        self,
        company_id: int,
        doc_date: date | str,
        lines: Sequence[ReceiptLine],
        credit_account_id: int,
        credit_subconto: Sequence[int | None] = (),
        memo: str = "",
        *,
        opening: bool = False,
    ) -> int:
        """Post a receipt/opening balance and its Dr inventory / Cr offset entries."""
        if not lines:
            raise ValidationError(tr("складской документ без строк"))
        offset_sc = _pad_subconto(credit_subconto)
        with transaction(self.conn):
            inv_id = self._insert_document(
                company_id, doc_date, "opening" if opening else "receipt", memo
            )
            postings: list[PostingInput] = []
            for line_no, source in enumerate(lines, 1):
                item = self._item(company_id, source.item_id)
                warehouse = self._warehouse(company_id, source.warehouse_id)
                quantity = self._quantity(item, source.quantity, line_no)
                amount = self._positive_amount(source.amount, line_no)
                line_id = self._insert_line(
                    inv_id,
                    company_id,
                    line_no,
                    item["id"],
                    warehouse["id"],
                    None,
                    quantity,
                    amount,
                    amount,
                    0,
                    credit_account_id,
                    offset_sc,
                    None,
                    source.memo,
                )
                self._insert_movement(
                    company_id,
                    inv_id,
                    line_id,
                    doc_date,
                    item["id"],
                    warehouse["id"],
                    "opening" if opening else "receipt",
                    quantity,
                    amount,
                )
                postings.append(
                    PostingInput(
                        item["inventory_account_id"],
                        credit_account_id,
                        _money(amount),
                        self._inventory_subconto(company_id, item, warehouse),
                        credit_subconto,
                        source.memo,
                    )
                )
            self._finish(inv_id, company_id, doc_date, postings, memo)
        return inv_id

    def post_issue(
        self,
        company_id: int,
        doc_date: date | str,
        lines: Sequence[IssueLine],
        memo: str = "",
    ) -> int:
        """Issue stock at the moving weighted-average cost."""
        if not lines:
            raise ValidationError(tr("складской документ без строк"))
        with transaction(self.conn):
            inv_id = self._insert_document(company_id, doc_date, "issue", memo)
            postings: list[PostingInput] = []
            for line_no, source in enumerate(lines, 1):
                item = self._item(company_id, source.item_id)
                warehouse = self._warehouse(company_id, source.warehouse_id)
                quantity = self._quantity(item, source.quantity, line_no)
                balance_qty, balance_amount = self._balance(
                    company_id, item["id"], warehouse["id"], inv_id
                )
                self._require_stock(item, warehouse, quantity, balance_qty)
                amount = (
                    balance_amount
                    if quantity == balance_qty
                    else _round_ratio(balance_amount * quantity, balance_qty)
                )
                expense_sc = _pad_subconto(source.expense_subconto)
                line_id = self._insert_line(
                    inv_id,
                    company_id,
                    line_no,
                    item["id"],
                    warehouse["id"],
                    None,
                    quantity,
                    amount,
                    0,
                    amount,
                    source.expense_account_id,
                    expense_sc,
                    None,
                    source.memo,
                )
                self._consume_receipts(company_id, inv_id, line_id, item["id"], quantity)
                self._insert_movement(
                    company_id,
                    inv_id,
                    line_id,
                    doc_date,
                    item["id"],
                    warehouse["id"],
                    "issue",
                    -quantity,
                    -amount,
                )
                postings.append(
                    PostingInput(
                        source.expense_account_id,
                        item["inventory_account_id"],
                        _money(amount),
                        source.expense_subconto,
                        self._inventory_subconto(company_id, item, warehouse),
                        source.memo,
                    )
                )
            self._finish(inv_id, company_id, doc_date, postings, memo)
        return inv_id

    def post_transfer(
        self,
        company_id: int,
        doc_date: date | str,
        lines: Sequence[TransferLine],
        memo: str = "",
    ) -> int:
        """Move stock between warehouses without changing company-wide quantity/value."""
        if not lines:
            raise ValidationError(tr("складской документ без строк"))
        with transaction(self.conn):
            inv_id = self._insert_document(company_id, doc_date, "transfer", memo)
            postings: list[PostingInput] = []
            for line_no, source in enumerate(lines, 1):
                if source.from_warehouse_id == source.to_warehouse_id:
                    raise ValidationError(tr("склад отправитель и получатель совпадают"))
                item = self._item(company_id, source.item_id)
                from_warehouse = self._warehouse(company_id, source.from_warehouse_id)
                to_warehouse = self._warehouse(company_id, source.to_warehouse_id)
                quantity = self._quantity(item, source.quantity, line_no)
                balance_qty, balance_amount = self._balance(
                    company_id, item["id"], from_warehouse["id"], inv_id
                )
                self._require_stock(item, from_warehouse, quantity, balance_qty)
                amount = (
                    balance_amount
                    if quantity == balance_qty
                    else _round_ratio(balance_amount * quantity, balance_qty)
                )
                line_id = self._insert_line(
                    inv_id,
                    company_id,
                    line_no,
                    item["id"],
                    from_warehouse["id"],
                    to_warehouse["id"],
                    quantity,
                    amount,
                    amount,
                    0,
                    None,
                    (None, None, None),
                    None,
                    source.memo,
                )
                for warehouse, movement_type, sign in (
                    (from_warehouse, "transfer_out", -1),
                    (to_warehouse, "transfer_in", 1),
                ):
                    self._insert_movement(
                        company_id,
                        inv_id,
                        line_id,
                        doc_date,
                        item["id"],
                        warehouse["id"],
                        movement_type,
                        sign * quantity,
                        sign * amount,
                    )
                postings.append(
                    PostingInput(
                        item["inventory_account_id"],
                        item["inventory_account_id"],
                        _money(amount),
                        self._inventory_subconto(company_id, item, to_warehouse),
                        self._inventory_subconto(company_id, item, from_warehouse),
                        source.memo,
                    )
                )
            self._finish(inv_id, company_id, doc_date, postings, memo)
        return inv_id

    def post_landed_cost(
        self,
        company_id: int,
        doc_date: date | str,
        receipt_line_ids: Sequence[int],
        total_amount: str | int | Decimal,
        credit_account_id: int,
        credit_subconto: Sequence[int | None] = (),
        memo: str = "",
        *,
        method: str = "value",
        manual_amounts: Mapping[int, str | int | Decimal] | None = None,
        cost_type_id: int | None = None,
    ) -> int:
        """Allocate landed cost to receipt lines and split it into stock/expense parts.

        `method` is `value`, `quantity`, or `manual`. If part of a receipt has already
        been issued, that share is posted to the original issue expense account.
        """
        ids = list(dict.fromkeys(receipt_line_ids))
        if not ids:
            raise ValidationError(tr("не выбраны поступления для распределения"))
        amount = self._positive_amount(total_amount, 0)
        if method not in {"value", "quantity", "manual"}:
            raise ValidationError(tr("неизвестный способ распределения"))
        with transaction(self.conn):
            if cost_type_id is not None:
                self._cost_type(company_id, cost_type_id)
            receipts = [self._receipt_line(company_id, line_id) for line_id in ids]
            if method == "manual":
                if manual_amounts is None or set(manual_amounts) != set(ids):
                    raise ValidationError(tr("ручные суммы заданы не для всех поступлений"))
                allocations = {
                    line_id: self._nonnegative_amount(value)
                    for line_id, value in manual_amounts.items()
                }
                if sum(allocations.values()) != amount:
                    raise ValidationError(tr("сумма ручного распределения не равна расходу"))
            else:
                field = "amount" if method == "value" else "quantity"
                allocations = _allocate_minor(amount, [(row["id"], row[field]) for row in receipts])

            inv_id = self._insert_document(
                company_id, doc_date, "landed_cost", memo, cost_type_id=cost_type_id
            )
            credit_sc = _pad_subconto(credit_subconto)
            postings: list[PostingInput] = []
            for line_no, receipt in enumerate(receipts, 1):
                allocated = allocations[receipt["id"]]
                if allocated == 0:
                    continue
                consumptions = self._receipt_consumptions(company_id, receipt["id"])
                consumed_quantity = sum(row["quantity"] for row in consumptions)
                remaining_quantity = receipt["quantity"] - consumed_quantity
                inventory_amount = _round_ratio(allocated * remaining_quantity, receipt["quantity"])
                expense_amount = allocated - inventory_amount
                item = self._item(company_id, receipt["item_id"])
                source_warehouse = self._warehouse(company_id, receipt["warehouse_id"])
                line_id = self._insert_line(
                    inv_id,
                    company_id,
                    line_no,
                    item["id"],
                    source_warehouse["id"],
                    None,
                    0,
                    allocated,
                    inventory_amount,
                    expense_amount,
                    credit_account_id,
                    credit_sc,
                    receipt["id"],
                    "",
                )

                if inventory_amount:
                    balances = self._item_warehouse_quantities(company_id, item["id"])
                    if not balances:
                        expense_amount += inventory_amount
                        inventory_amount = 0
                        self.conn.execute(
                            "UPDATE inventory_lines SET inventory_amount = 0, "
                            "expense_amount = ? WHERE id = ?",
                            (expense_amount, line_id),
                        )
                    else:
                        by_warehouse = _allocate_minor(inventory_amount, balances)
                        for warehouse_id, share in by_warehouse.items():
                            if not share:
                                continue
                            warehouse = self._warehouse(company_id, warehouse_id)
                            self._insert_movement(
                                company_id,
                                inv_id,
                                line_id,
                                doc_date,
                                item["id"],
                                warehouse_id,
                                "landed_cost",
                                0,
                                share,
                            )
                            postings.append(
                                PostingInput(
                                    item["inventory_account_id"],
                                    credit_account_id,
                                    _money(share),
                                    self._inventory_subconto(company_id, item, warehouse),
                                    credit_subconto,
                                    memo,
                                )
                            )

                if expense_amount:
                    if not consumptions:
                        raise ValidationError(tr("не найдены списания для распределения расхода"))
                    by_issue = _allocate_minor(
                        expense_amount,
                        [(row["issue_line_id"], row["quantity"]) for row in consumptions],
                    )
                    issues = {row["issue_line_id"]: row for row in consumptions}
                    for issue_line_id, share in by_issue.items():
                        if not share:
                            continue
                        issue = issues[issue_line_id]
                        self.conn.execute(
                            "INSERT INTO landed_cost_expense_allocations "
                            "(company_id, document_id, landed_cost_line_id, issue_line_id, amount) "
                            "VALUES (?, ?, ?, ?, ?)",
                            (company_id, inv_id, line_id, issue_line_id, share),
                        )
                        postings.append(
                            PostingInput(
                                issue["offset_account_id"],
                                credit_account_id,
                                _money(share),
                                (issue["offset_sc1"], issue["offset_sc2"], issue["offset_sc3"]),
                                credit_subconto,
                                memo,
                            )
                        )
            self._finish(inv_id, company_id, doc_date, postings, memo)
        return inv_id

    def delete_document(self, company_id: int, document_id: int) -> None:
        """Remove a posted inventory document in an open period, with a full audit copy."""
        with transaction(self.conn):
            doc = self._document(company_id, document_id)
            closed = self._company(company_id)["closed_through"]
            if closed is not None and doc["doc_date"] <= closed:
                raise PeriodClosedError(
                    tr(
                        "складской документ №{number} от {date}: период закрыт по {closed}",
                        number=doc["number"],
                        date=doc["doc_date"],
                        closed=closed,
                    )
                )
            snapshot = self._snapshot(doc)
            try:
                self._require_removable(company_id, document_id)
                self.conn.execute(
                    "UPDATE inventory_documents SET status = 'draft' WHERE id = ?",
                    (document_id,),
                )
                gl_document_id = doc["gl_document_id"]
                self.conn.execute(
                    "UPDATE inventory_documents SET gl_document_id = NULL WHERE id = ?",
                    (document_id,),
                )
                if gl_document_id is not None:
                    self.ledger.delete_document(company_id, gl_document_id)
                self.conn.execute("DELETE FROM inventory_documents WHERE id = ?", (document_id,))
            except sqlite3.IntegrityError as exc:
                raise ValidationError(
                    tr("документ связан с последующими складскими операциями")
                ) from exc
            self._audit(company_id, "inventory_document", document_id, "delete", snapshot)

    # ---- internals -----------------------------------------------------------------

    def _insert_document(
        self,
        company_id: int,
        doc_date: date | str,
        doc_type: str,
        memo: str,
        *,
        cost_type_id: int | None = None,
    ) -> int:
        self._company(company_id)
        value_date = iso_date(doc_date)
        latest = self.conn.execute(
            "SELECT MAX(doc_date) FROM inventory_documents "
            "WHERE company_id = ? AND status = 'posted'",
            (company_id,),
        ).fetchone()[0]
        if latest is not None and value_date < latest:
            raise ValidationError(
                tr(
                    "складские документы проводятся по порядку дат; "
                    "последняя проведённая дата {date}",
                    date=latest,
                )
            )
        number = self.conn.execute(
            "UPDATE companies SET last_inventory_number = last_inventory_number + 1 "
            "WHERE id = ? RETURNING last_inventory_number",
            (company_id,),
        ).fetchone()[0]
        return self.conn.execute(
            "INSERT INTO inventory_documents "
            "(company_id, number, doc_date, doc_type, memo, status, landed_cost_type_id, "
            "created_at) VALUES (?, ?, ?, ?, ?, 'draft', ?, ?)",
            (company_id, number, value_date, doc_type, memo, cost_type_id, _now()),
        ).lastrowid

    def _insert_line(
        self,
        document_id: int,
        company_id: int,
        line_no: int,
        item_id: int,
        warehouse_id: int | None,
        to_warehouse_id: int | None,
        quantity: int,
        amount: int,
        inventory_amount: int,
        expense_amount: int,
        offset_account_id: int | None,
        offset_subconto: Sequence[int | None],
        source_receipt_line_id: int | None,
        memo: str,
    ) -> int:
        sc = _pad_subconto(offset_subconto)
        return self.conn.execute(
            "INSERT INTO inventory_lines (company_id, document_id, line_no, item_id, "
            "warehouse_id, to_warehouse_id, quantity, amount, inventory_amount, "
            "expense_amount, offset_account_id, offset_sc1, offset_sc2, offset_sc3, "
            "source_receipt_line_id, memo) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                company_id,
                document_id,
                line_no,
                item_id,
                warehouse_id,
                to_warehouse_id,
                quantity,
                amount,
                inventory_amount,
                expense_amount,
                offset_account_id,
                *sc,
                source_receipt_line_id,
                memo,
            ),
        ).lastrowid

    def _insert_movement(
        self,
        company_id: int,
        document_id: int,
        line_id: int,
        doc_date: date | str,
        item_id: int,
        warehouse_id: int,
        movement_type: str,
        quantity: int,
        amount: int,
    ) -> None:
        self.conn.execute(
            "INSERT INTO stock_movements (company_id, document_id, line_id, doc_date, item_id, "
            "warehouse_id, movement_type, quantity, amount) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                company_id,
                document_id,
                line_id,
                iso_date(doc_date),
                item_id,
                warehouse_id,
                movement_type,
                quantity,
                amount,
            ),
        )

    def _finish(
        self,
        inventory_document_id: int,
        company_id: int,
        doc_date: date | str,
        postings: Sequence[PostingInput],
        memo: str,
    ) -> None:
        if not postings:
            raise ValidationError(tr("складской документ не создал проводок"))
        gl_document_id = self.ledger.post_new(company_id, doc_date, postings, memo)
        self.conn.execute(
            "UPDATE inventory_documents SET status = 'posted', gl_document_id = ?, "
            "posted_at = ? WHERE id = ?",
            (gl_document_id, _now(), inventory_document_id),
        )
        doc = self._document(company_id, inventory_document_id)
        self._audit(
            company_id,
            "inventory_document",
            inventory_document_id,
            "post",
            {"number": doc["number"], "type": doc["doc_type"], "gl_document_id": gl_document_id},
        )

    def _consume_receipts(
        self,
        company_id: int,
        document_id: int,
        issue_line_id: int,
        item_id: int,
        quantity: int,
    ) -> None:
        rows = self.conn.execute(
            """
            SELECT l.id, l.quantity - COALESCE(SUM(c.quantity), 0) AS available
            FROM inventory_lines l
            JOIN inventory_documents d ON d.id = l.document_id AND d.company_id = l.company_id
            LEFT JOIN stock_consumptions c ON c.receipt_line_id = l.id
            WHERE l.company_id = ? AND l.item_id = ? AND d.status = 'posted'
              AND d.doc_type IN ('opening', 'receipt')
            GROUP BY l.id, l.quantity, d.doc_date, d.id, l.line_no
            HAVING available > 0
            ORDER BY d.doc_date, d.id, l.line_no
            """,
            (company_id, item_id),
        ).fetchall()
        remaining = quantity
        for row in rows:
            used = min(remaining, row["available"])
            if used:
                self.conn.execute(
                    "INSERT INTO stock_consumptions "
                    "(company_id, document_id, issue_line_id, receipt_line_id, quantity) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (company_id, document_id, issue_line_id, row["id"], used),
                )
                remaining -= used
            if remaining == 0:
                return
        raise ValidationError(tr("не удалось определить поступления для списания"))

    def _balance(
        self, company_id: int, item_id: int, warehouse_id: int, current_document_id: int | None
    ) -> tuple[int, int]:
        row = self.conn.execute(
            """
            SELECT COALESCE(SUM(m.quantity), 0) AS quantity,
                   COALESCE(SUM(m.amount), 0) AS amount
            FROM stock_movements m
            JOIN inventory_documents d ON d.id = m.document_id
            WHERE m.company_id = ? AND m.item_id = ? AND m.warehouse_id = ?
              AND (d.status = 'posted' OR d.id = ?)
            """,
            (company_id, item_id, warehouse_id, current_document_id),
        ).fetchone()
        return row["quantity"], row["amount"]

    def _item_warehouse_quantities(self, company_id: int, item_id: int) -> list[tuple[int, int]]:
        return [
            (row["warehouse_id"], row["quantity"])
            for row in self.conn.execute(
                """
                SELECT m.warehouse_id, SUM(m.quantity) AS quantity
                FROM stock_movements m
                JOIN inventory_documents d ON d.id = m.document_id
                WHERE m.company_id = ? AND m.item_id = ? AND d.status = 'posted'
                GROUP BY m.warehouse_id HAVING quantity > 0
                ORDER BY m.warehouse_id
                """,
                (company_id, item_id),
            )
        ]

    def _receipt_consumptions(self, company_id: int, receipt_line_id: int) -> list[sqlite3.Row]:
        return self.conn.execute(
            """
            SELECT c.issue_line_id, c.quantity, l.offset_account_id,
                   l.offset_sc1, l.offset_sc2, l.offset_sc3
            FROM stock_consumptions c
            JOIN inventory_lines l ON l.id = c.issue_line_id
            JOIN inventory_documents d ON d.id = l.document_id
            WHERE c.company_id = ? AND c.receipt_line_id = ? AND d.status = 'posted'
            ORDER BY c.issue_line_id
            """,
            (company_id, receipt_line_id),
        ).fetchall()

    def _require_removable(self, company_id: int, document_id: int) -> None:
        """A removal must not make a later physical/value balance negative."""
        affected = self.conn.execute(
            "SELECT DISTINCT item_id, warehouse_id FROM stock_movements WHERE document_id = ?",
            (document_id,),
        ).fetchall()
        for pair in affected:
            quantity = amount = 0
            movements = self.conn.execute(
                """
                SELECT m.quantity, m.amount
                FROM stock_movements m
                JOIN inventory_documents d ON d.id = m.document_id
                WHERE m.company_id = ? AND m.item_id = ? AND m.warehouse_id = ?
                  AND m.document_id <> ? AND d.status = 'posted'
                ORDER BY m.doc_date, d.id, m.id
                """,
                (company_id, pair["item_id"], pair["warehouse_id"], document_id),
            )
            for movement in movements:
                quantity += movement["quantity"]
                amount += movement["amount"]
                if quantity < 0 or amount < 0:
                    raise ValidationError(
                        tr("документ связан с последующими складскими операциями")
                    )

    def _inventory_subconto(
        self, company_id: int, item: sqlite3.Row, warehouse: sqlite3.Row
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

    def _account_kind_codes(
        self, company_id: int, account: sqlite3.Row
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

    def _quantity(self, item: sqlite3.Row, value: str | int | Decimal, line_no: int) -> int:
        try:
            quantity = to_quantity(value)
        except (TypeError, ValueError) as exc:
            raise ValidationError(tr("строка {line}: {error}", line=line_no, error=exc)) from exc
        if quantity <= 0:
            raise ValidationError(
                tr("строка {line}: количество должно быть положительным", line=line_no)
            )
        precision = item["unit_precision"]
        if quantity % (10 ** (QUANTITY_SCALE - precision)):
            raise ValidationError(
                tr("строка {line}: для единицы допустимо знаков: {n}", line=line_no, n=precision)
            )
        return quantity

    @staticmethod
    def _positive_amount(value: str | int | Decimal, line_no: int) -> int:
        try:
            amount = to_minor(value)
        except (TypeError, ValueError) as exc:
            prefix = tr("строка {line}: ", line=line_no) if line_no else ""
            raise ValidationError(f"{prefix}{exc}") from exc
        if amount <= 0:
            raise ValidationError(tr("сумма должна быть положительной"))
        return amount

    @staticmethod
    def _nonnegative_amount(value: str | int | Decimal) -> int:
        try:
            amount = to_minor(value)
        except (TypeError, ValueError) as exc:
            raise ValidationError(str(exc)) from exc
        if amount < 0:
            raise ValidationError(tr("сумма не может быть отрицательной"))
        return amount

    @staticmethod
    def _require_stock(
        item: sqlite3.Row, warehouse: sqlite3.Row, requested: int, available: int
    ) -> None:
        if requested > available:
            raise ValidationError(
                tr(
                    "недостаточно товара «{item}» на складе «{warehouse}»: "
                    "доступно {available}, требуется {requested}",
                    item=item["name"],
                    warehouse=warehouse["name"],
                    available=format_quantity(available, item["unit_precision"]),
                    requested=format_quantity(requested, item["unit_precision"]),
                )
            )

    def _company(self, company_id: int) -> sqlite3.Row:
        row = self.conn.execute("SELECT * FROM companies WHERE id = ?", (company_id,)).fetchone()
        if row is None:
            raise NotFoundError(tr("компания {id} не найдена", id=company_id))
        return row

    def _unit(self, company_id: int, unit_id: int) -> sqlite3.Row:
        row = self.conn.execute(
            "SELECT * FROM inventory_units WHERE company_id = ? AND id = ?",
            (company_id, unit_id),
        ).fetchone()
        if row is None:
            raise NotFoundError(tr("единица измерения не найдена"))
        return row

    def _item(self, company_id: int, item_id: int) -> sqlite3.Row:
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

    def _warehouse(self, company_id: int, warehouse_id: int) -> sqlite3.Row:
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

    def _cost_type(self, company_id: int, type_id: int) -> sqlite3.Row:
        row = self.conn.execute(
            "SELECT * FROM landed_cost_types WHERE company_id = ? AND id = ? AND active = 1",
            (company_id, type_id),
        ).fetchone()
        if row is None:
            raise NotFoundError(tr("вид дополнительных расходов не найден"))
        return row

    def _account(self, company_id: int, account_id: int) -> sqlite3.Row:
        row = self.conn.execute(
            "SELECT * FROM accounts WHERE company_id = ? AND id = ?",
            (company_id, account_id),
        ).fetchone()
        if row is None:
            raise NotFoundError(tr("счёт не найден"))
        return row

    def _subconto_value(self, company_id: int, value_id: int) -> sqlite3.Row:
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

    def _document(self, company_id: int, document_id: int) -> sqlite3.Row:
        row = self.conn.execute(
            "SELECT * FROM inventory_documents WHERE company_id = ? AND id = ?",
            (company_id, document_id),
        ).fetchone()
        if row is None:
            raise NotFoundError(tr("складской документ не найден"))
        return row

    def _receipt_line(self, company_id: int, line_id: int) -> sqlite3.Row:
        row = self.conn.execute(
            """
            SELECT l.* FROM inventory_lines l
            JOIN inventory_documents d ON d.id = l.document_id
            WHERE l.company_id = ? AND l.id = ? AND d.status = 'posted'
              AND d.doc_type IN ('opening', 'receipt')
            """,
            (company_id, line_id),
        ).fetchone()
        if row is None:
            raise ValidationError(tr("строка поступления не найдена или не проведена"))
        return row

    def _snapshot(self, doc: sqlite3.Row) -> dict:
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
            "lines": lines,
        }

    def _audit(
        self, company_id: int, entity: str, entity_id: int, action: str, details: dict
    ) -> None:
        self.conn.execute(
            "INSERT INTO audit_events (company_id, at, actor, entity, entity_id, action, details) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                company_id,
                _now(),
                self.actor,
                entity,
                entity_id,
                action,
                json.dumps(details, ensure_ascii=False),
            ),
        )
