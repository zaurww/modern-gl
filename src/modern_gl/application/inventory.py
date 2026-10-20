"""Quantitative/value inventory use cases and landed-cost allocation.

Quantities live in a separate immutable movement register. Every posted inventory
document creates an ordinary GL document in the same SQLite transaction.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

from modern_gl.application.common import company_row, insert, now, pad_subconto, write_audit
from modern_gl.application.ledger import Ledger, PostingInput
from modern_gl.domain.accounts import INPUT_VAT
from modern_gl.domain.currency import parse_rate, to_base, unit_rate
from modern_gl.domain.dates import iso_date, ru_date
from modern_gl.domain.errors import (
    LedgerError,
    NotFoundError,
    PeriodClosedError,
    ValidationError,
)
from modern_gl.domain.invoice import EQAIME, KINDS, normalize_invoice
from modern_gl.domain.money import SCALE as MONEY_SCALE
from modern_gl.domain.money import format_minor, round_ratio, to_minor
from modern_gl.i18n import tr
from modern_gl.infrastructure.db import transaction

QUANTITY_SCALE = 6
QUANTITY_FACTOR = 10**QUANTITY_SCALE
_QUANTITY_QUANTUM = Decimal(1).scaleb(-QUANTITY_SCALE)
ALLOCATION_METHODS = ("value", "quantity", "manual")
# VAT rates are in hundredths of a percent; a receipt starts with the standard rate.
VAT_RATE_SCALE = 10_000
STANDARD_VAT_RATE = 1800

# Within one day, arrivals come before what leaves: the sequence of posting is
# (date, rank, number). There is no time of day.
_SEQUENCE_RANK = {"opening": 0, "receipt": 1, "landed_cost": 2, "transfer": 3, "issue": 3}


def _sequence_key(doc: sqlite3.Row) -> tuple[str, int, int]:
    return doc["doc_date"], _SEQUENCE_RANK[doc["doc_type"]], doc["number"]


@dataclass(frozen=True)
class ReceiptLine:
    """Receipt/opening line. In a draft, everything except the item may be left empty."""

    item_id: int
    warehouse_id: int | None
    quantity: str | int | Decimal | None
    amount: str | int | Decimal | None
    memo: str = ""
    credit_account_id: int | None = None
    credit_subconto: Sequence[int | None] = ()
    line_id: int | None = None  # the stored line it edits; None = a new line
    vat_amount: str | int | Decimal | None = None  # a receipt's VAT; the amount is without it
    currency_amount: str | int | Decimal | None = None  # a receipt in a currency: the amount


@dataclass(frozen=True)
class IssueLine:
    item_id: int
    warehouse_id: int | None
    quantity: str | int | Decimal | None
    expense_account_id: int | None
    expense_subconto: Sequence[int | None] = ()
    memo: str = ""
    line_id: int | None = None


@dataclass(frozen=True)
class TransferLine:
    item_id: int
    from_warehouse_id: int | None
    to_warehouse_id: int | None
    quantity: str | int | Decimal | None
    memo: str = ""
    line_id: int | None = None


@dataclass(frozen=True)
class LandedCostTarget:
    """A receipt line of the batch; `amount` is its share in the manual allocation."""

    receipt_line_id: int
    amount: str | int | Decimal | None = None
    line_id: int | None = None


@dataclass(frozen=True)
class LandedCostCharge:
    """An expense of the batch: typed in the document (the broker's or customs' account,
    amount, VAT) or an existing GL posting (its document and line number) whose debit is
    moved to stock."""

    amount: str | int | Decimal | None
    account_id: int | None = None
    subconto: Sequence[int | None] = ()
    vat_amount: str | int | Decimal | None = None
    cost_type_id: int | None = None
    source_document_id: int | None = None
    source_line_no: int | None = None
    memo: str = ""
    # an expense in a currency: its amount there and the rate (manat per unit)
    currency_id: int | None = None
    currency_rate: str | int | Decimal | None = None
    currency_amount: str | int | Decimal | None = None


@dataclass(frozen=True)
class LandedCostChargeData:
    id: int
    line_no: int
    cost_type_id: int | None
    account_id: int | None
    subconto: tuple[int | None, int | None, int | None]
    amount: int
    vat_amount: int
    source_document_id: int | None
    source_line_no: int | None
    memo: str
    currency_id: int | None = None
    currency_rate: int | None = None  # millionths of a manat per unit
    currency_amount: int | None = None


@dataclass(frozen=True)
class InventoryLineData:
    id: int
    line_no: int
    item_id: int
    warehouse_id: int | None
    to_warehouse_id: int | None
    quantity: int
    amount: int
    inventory_amount: int
    expense_amount: int
    offset_account_id: int | None
    offset_subconto: tuple[int | None, int | None, int | None]
    source_receipt_line_id: int | None
    memo: str
    vat_amount: int = 0
    currency_amount: int | None = None


@dataclass(frozen=True)
class InventoryDocumentData:
    id: int
    number: int
    doc_date: str
    doc_type: str
    memo: str
    status: str
    landed_cost_type_id: int | None
    gl_document_id: int | None
    lines: tuple[InventoryLineData, ...]
    closed: bool = False  # dated in a closed period: cannot be changed
    vat_rate: int | None = None  # a receipt's VAT rate (1800 = 18%); None: without VAT
    allocation_method: str | None = None  # landed cost: value / quantity / manual
    charges: tuple[LandedCostChargeData, ...] = ()  # landed cost: its expenses
    currency_id: int | None = None  # a receipt in a currency
    currency_rate: int | None = None  # millionths of a manat per unit
    invoice: str = ""  # a receipt's e-qaimə number (or customs declaration number)
    invoice_kind: str = ""  # domain.invoice: "" an e-qaimə, "customs" a declaration

    @property
    def editable(self) -> bool:
        """A draft, or a posted document edited in place in an open period."""
        return self.status != "posted" or not self.closed


def to_quantity(value: str | int | Decimal) -> int:
    """Convert a user quantity to millionths of a base unit, without float rounding."""
    if isinstance(value, (bool, float)):
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


def vat_of(amount: int, rate: int | None) -> int:
    """VAT on an amount without VAT, rounded to a minor unit (half away from zero)."""
    return 0 if not rate else round_ratio(amount * rate, VAT_RATE_SCALE)


def format_quantity(quantity: int, precision: int = 3) -> str:
    """Format an internal quantity without insignificant zeroes."""
    value = Decimal(quantity).scaleb(-QUANTITY_SCALE)
    text = f"{value:.{precision}f}"
    return text.rstrip("0").rstrip(".") if "." in text else text


def _blank(value: object) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _money(minor: int) -> Decimal:
    """Convert stored minor units back to the exact value expected by PostingInput."""
    return Decimal(minor).scaleb(-MONEY_SCALE)


def allocate_minor(total: int, weights: Sequence[tuple[int, int]]) -> dict[int, int]:
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


def split_charges(
    charges: Sequence[tuple[int, int]], targets: Mapping[int, int]
) -> dict[tuple[int, int], int]:
    """(charge, target) -> share: every charge is spread over the targets so that each
    charge and each target total come out exact (charges and targets sum to the same).

    Each charge goes in proportion to what the targets can still take, so the last one
    takes exactly the rest."""
    capacity = dict(targets)
    result: dict[tuple[int, int], int] = {}
    for charge_id, amount in charges:
        if amount <= 0:
            continue
        weights = [(key, left) for key, left in capacity.items() if left > 0]
        for key, share in allocate_minor(amount, weights).items():
            if share:
                result[(charge_id, key)] = share
                capacity[key] -= share
    return result


@dataclass(frozen=True)
class _Credit:
    """A credit piece of landed cost postings: a charge's share of one receipt line."""

    account_id: int
    subconto: Sequence[int | None]
    amount: int
    memo: str
    currency_id: int | None = None
    currency_amount: int = 0


def _pair(
    debits: Sequence[tuple[int, Sequence[int | None], int]], credits: Sequence[_Credit]
) -> list[PostingInput]:
    """Postings from debit pieces (account, subconto, amount) and credit pieces of the same
    total, matched in order. A credit piece in a currency split over several postings
    shares its currency amount in proportion to the manat amounts."""
    pieces: list[tuple[int, int, int]] = []  # debit index, credit index, amount
    d_left = [amount for _, _, amount in debits]
    c_left = [credit.amount for credit in credits]
    i = j = 0
    while i < len(debits) and j < len(credits):
        amount = min(d_left[i], c_left[j])
        if amount:
            pieces.append((i, j, amount))
        d_left[i] -= amount
        c_left[j] -= amount
        i += d_left[i] == 0
        j += c_left[j] == 0
    in_currency: dict[int, int] = {}
    for j, credit in enumerate(credits):
        mine = [(k, piece[2]) for k, piece in enumerate(pieces) if piece[1] == j]
        if credit.currency_id is not None and credit.currency_amount > 0 and mine:
            in_currency.update(allocate_minor(credit.currency_amount, mine))
    return [
        PostingInput(
            debits[i][0],
            credits[j].account_id,
            _money(amount),
            tuple(debits[i][1]),
            tuple(credits[j].subconto),
            credits[j].memo,
            credits[j].currency_id,
            None if credits[j].currency_id is None else _money(in_currency.get(k, 0)),
        )
        for k, (i, j, amount) in enumerate(pieces)
    ]


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
                unit_id = insert(
                    self.conn,
                    "INSERT INTO inventory_units (company_id, code, name, precision) "
                    "VALUES (?, ?, ?, ?)",
                    (company_id, code, name, precision),
                )
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
                item_id = insert(
                    self.conn,
                    "INSERT INTO inventory_items "
                    "(company_id, subconto_value_id, unit_id, inventory_account_id) "
                    "VALUES (?, ?, ?, ?)",
                    (company_id, subconto_value_id, unit_id, inventory_account_id),
                )
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
                warehouse_id = insert(
                    self.conn,
                    "INSERT INTO warehouses (company_id, subconto_value_id) VALUES (?, ?)",
                    (company_id, subconto_value_id),
                )
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
                type_id = insert(
                    self.conn,
                    "INSERT INTO landed_cost_types (company_id, code, name) VALUES (?, ?, ?)",
                    (company_id, code, name),
                )
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

    def load_document(self, company_id: int, document_id: int) -> InventoryDocumentData:
        """Load a warehouse document with its source and calculated line fields."""
        doc = self._document(company_id, document_id)
        rows = self.conn.execute(
            "SELECT * FROM inventory_lines WHERE company_id = ? AND document_id = ? "
            "ORDER BY line_no",
            (company_id, document_id),
        ).fetchall()
        return InventoryDocumentData(
            doc["id"],
            doc["number"],
            doc["doc_date"],
            doc["doc_type"],
            doc["memo"],
            doc["status"],
            doc["landed_cost_type_id"],
            doc["gl_document_id"],
            tuple(
                InventoryLineData(
                    row["id"],
                    row["line_no"],
                    row["item_id"],
                    row["warehouse_id"],
                    row["to_warehouse_id"],
                    row["quantity"],
                    row["amount"],
                    row["inventory_amount"],
                    row["expense_amount"],
                    row["offset_account_id"],
                    (row["offset_sc1"], row["offset_sc2"], row["offset_sc3"]),
                    row["source_receipt_line_id"],
                    row["memo"],
                    row["vat_amount"],
                    row["currency_amount"],
                )
                for row in rows
            ),
            closed=self._closed(doc),
            vat_rate=doc["vat_rate"],
            allocation_method=doc["allocation_method"],
            charges=tuple(
                LandedCostChargeData(
                    row["id"],
                    row["line_no"],
                    row["cost_type_id"],
                    row["account_id"],
                    (row["sc1"], row["sc2"], row["sc3"]),
                    row["amount"],
                    row["vat_amount"],
                    row["source_document_id"],
                    row["source_line_no"],
                    row["memo"],
                    row["currency_id"],
                    row["currency_rate"],
                    row["currency_amount"],
                )
                for row in self._charges(document_id)
            ),
            currency_id=doc["currency_id"],
            currency_rate=doc["currency_rate"],
            invoice=doc["invoice"] or "",
            invoice_kind=doc["invoice_kind"] or "",
        )

    def _closed(self, doc: sqlite3.Row) -> bool:
        closed = self._company(doc["company_id"])["closed_through"]
        return closed is not None and doc["doc_date"] <= closed

    def create_receipt_draft(
        self,
        company_id: int,
        doc_date: date | str,
        lines: Sequence[ReceiptLine],
        credit_account_id: int | None,
        credit_subconto: Sequence[int | None] = (),
        memo: str = "",
        *,
        opening: bool = False,
        vat_rate: int | None = None,
        currency_id: int | None = None,
        currency_rate: str | int | Decimal | None = None,
        invoice: str = "",
        invoice_kind: str = "",
    ) -> int:
        """Save an editable receipt/opening document without affecting stock or GL.

        A draft may be unfinished: only the item of each line is required. Line amounts
        are without VAT; each line's VAT is given (`vat_rate` only remembers the rate)."""
        with transaction(self.conn):
            document_id = self._insert_document(
                company_id,
                doc_date,
                "opening" if opening else "receipt",
                memo,
            )
            self._set_vat_rate(document_id, None if opening else vat_rate)
            self._set_currency(company_id, document_id, currency_id, currency_rate)
            self._set_invoice(document_id, "" if opening else invoice, invoice_kind)
            self._write_receipt_draft(
                company_id, document_id, lines, credit_account_id, credit_subconto
            )
            self._audit(
                company_id,
                "inventory_document",
                document_id,
                "create_draft",
                {"type": "opening" if opening else "receipt"},
            )
        return document_id

    def create_issue_draft(
        self,
        company_id: int,
        doc_date: date | str,
        lines: Sequence[IssueLine],
        memo: str = "",
    ) -> int:
        """Save an editable issue document without affecting stock or GL."""
        with transaction(self.conn):
            document_id = self._insert_document(company_id, doc_date, "issue", memo)
            self._write_issue_draft(company_id, document_id, lines)
            self._audit(
                company_id,
                "inventory_document",
                document_id,
                "create_draft",
                {"type": "issue"},
            )
        return document_id

    def create_transfer_draft(
        self,
        company_id: int,
        doc_date: date | str,
        lines: Sequence[TransferLine],
        memo: str = "",
    ) -> int:
        """Save an editable transfer document without affecting stock or GL."""
        with transaction(self.conn):
            document_id = self._insert_document(company_id, doc_date, "transfer", memo)
            self._write_transfer_draft(company_id, document_id, lines)
            self._audit(
                company_id,
                "inventory_document",
                document_id,
                "create_draft",
                {"type": "transfer"},
            )
        return document_id

    def update_receipt_draft(
        self,
        company_id: int,
        document_id: int,
        doc_date: date | str,
        lines: Sequence[ReceiptLine],
        credit_account_id: int | None,
        credit_subconto: Sequence[int | None] = (),
        memo: str = "",
        *,
        vat_rate: int | None = None,
        currency_id: int | None = None,
        currency_rate: str | int | Decimal | None = None,
        invoice: str = "",
        invoice_kind: str = "",
    ) -> None:
        with transaction(self.conn):
            doc = self._require_inventory_draft(company_id, document_id)
            if doc["doc_type"] not in {"opening", "receipt"}:
                raise ValidationError(tr("тип складского документа нельзя изменить"))
            self._update_draft_header(company_id, document_id, doc_date, memo)
            self._set_vat_rate(document_id, vat_rate if doc["doc_type"] == "receipt" else None)
            self._set_currency(company_id, document_id, currency_id, currency_rate)
            receipt = doc["doc_type"] == "receipt"
            self._set_invoice(document_id, invoice if receipt else "", invoice_kind)
            self._release_lines(company_id, document_id, lines)
            self._write_receipt_draft(
                company_id, document_id, lines, credit_account_id, credit_subconto
            )
            self._audit(company_id, "inventory_document", document_id, "update_draft", {})

    def update_issue_draft(
        self,
        company_id: int,
        document_id: int,
        doc_date: date | str,
        lines: Sequence[IssueLine],
        memo: str = "",
    ) -> None:
        with transaction(self.conn):
            doc = self._require_inventory_draft(company_id, document_id)
            if doc["doc_type"] != "issue":
                raise ValidationError(tr("тип складского документа нельзя изменить"))
            self._update_draft_header(company_id, document_id, doc_date, memo)
            self._release_lines(company_id, document_id, lines)
            self._write_issue_draft(company_id, document_id, lines)
            self._audit(company_id, "inventory_document", document_id, "update_draft", {})

    def update_transfer_draft(
        self,
        company_id: int,
        document_id: int,
        doc_date: date | str,
        lines: Sequence[TransferLine],
        memo: str = "",
    ) -> None:
        with transaction(self.conn):
            doc = self._require_inventory_draft(company_id, document_id)
            if doc["doc_type"] != "transfer":
                raise ValidationError(tr("тип складского документа нельзя изменить"))
            self._update_draft_header(company_id, document_id, doc_date, memo)
            self._release_lines(company_id, document_id, lines)
            self._write_transfer_draft(company_id, document_id, lines)
            self._audit(company_id, "inventory_document", document_id, "update_draft", {})

    def post_document(self, company_id: int, document_id: int) -> None:
        """Post a saved warehouse draft and calculate all derived amounts atomically.

        A draft dated before already posted documents goes into its place in the sequence:
        the later documents are recalculated (their cost may change)."""
        with transaction(self.conn):
            self._require_inventory_draft(company_id, document_id)
            self._post_in_sequence(company_id, document_id)

    @contextmanager
    def reposting(self, company_id: int, document_id: int) -> Iterator[None]:
        """Edit a posted document in place, as in 1C.

        Inside the block the document is a draft (`update_*_draft` works on it); on exit it
        is posted again, keeping its number and its GL document, and every later warehouse
        document is recalculated. Any error rolls everything back."""
        with transaction(self.conn):
            doc = self._document(company_id, document_id)
            if doc["status"] != "posted":
                raise ValidationError(tr("складской документ не проведён"))
            self._require_open_period(doc)
            snapshot = self._snapshot(doc)
            later = self._withdraw_after(company_id, doc)
            self._withdraw(company_id, doc)
            yield
            edited = self._require_inventory_draft(company_id, document_id)
            self._require_open_period(edited)
            later += self._withdraw_after(company_id, edited)  # it may have moved earlier
            self._apply_in_order(company_id, document_id, later)
            self._audit(company_id, "inventory_document", document_id, "repost", snapshot)

    def unpost_document(self, company_id: int, document_id: int) -> None:
        """Return a posted warehouse document to an editable draft in an open period.
        Later documents are recalculated without it."""
        with transaction(self.conn):
            doc = self._document(company_id, document_id)
            if doc["status"] != "posted":
                raise ValidationError(tr("складской документ уже является черновиком"))
            snapshot = self._snapshot(doc)
            self._unpost(company_id, doc)
            self._audit(company_id, "inventory_document", document_id, "unpost", snapshot)

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
        vat_rate: int | None = None,
        currency_id: int | None = None,
        currency_rate: str | int | Decimal | None = None,
        invoice: str = "",
        invoice_kind: str = "",
    ) -> int:
        """Post a receipt/opening balance and its Dr inventory / Cr offset entries
        (and Dr input VAT / Cr offset for the lines' VAT)."""
        if not lines:
            raise ValidationError(tr("складской документ без строк"))
        with transaction(self.conn):
            inv_id = self.create_receipt_draft(
                company_id,
                doc_date,
                lines,
                credit_account_id,
                credit_subconto,
                memo,
                opening=opening,
                vat_rate=vat_rate,
                currency_id=currency_id,
                currency_rate=currency_rate,
                invoice=invoice,
                invoice_kind=invoice_kind,
            )
            self._post_in_sequence(company_id, inv_id)
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
            inv_id = self.create_issue_draft(company_id, doc_date, lines, memo)
            self._post_in_sequence(company_id, inv_id)
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
            inv_id = self.create_transfer_draft(company_id, doc_date, lines, memo)
            self._post_in_sequence(company_id, inv_id)
        return inv_id

    def create_landed_cost_draft(
        self,
        company_id: int,
        doc_date: date | str,
        targets: Sequence[LandedCostTarget],
        charges: Sequence[LandedCostCharge],
        method: str = "value",
        memo: str = "",
        *,
        cost_type_id: int | None = None,
    ) -> int:
        """Save a «Расходы по партии» document: the receipt lines of a batch, its expenses
        and how they are allocated (by value, by quantity or by hand). A draft may be
        unfinished; posting checks everything."""
        with transaction(self.conn):
            if cost_type_id is not None:
                self._cost_type(company_id, cost_type_id)
            document_id = self._insert_document(
                company_id, doc_date, "landed_cost", memo, cost_type_id=cost_type_id
            )
            self._write_landed_cost_draft(company_id, document_id, targets, charges, method)
            self._audit(
                company_id,
                "inventory_document",
                document_id,
                "create_draft",
                {"type": "landed_cost"},
            )
        return document_id

    def update_landed_cost_draft(
        self,
        company_id: int,
        document_id: int,
        doc_date: date | str,
        targets: Sequence[LandedCostTarget],
        charges: Sequence[LandedCostCharge],
        method: str = "value",
        memo: str = "",
    ) -> None:
        with transaction(self.conn):
            doc = self._require_inventory_draft(company_id, document_id)
            if doc["doc_type"] != "landed_cost":
                raise ValidationError(tr("тип складского документа нельзя изменить"))
            self._update_draft_header(company_id, document_id, doc_date, memo)
            self._release_lines(company_id, document_id, targets)
            self._write_landed_cost_draft(company_id, document_id, targets, charges, method)
            self._audit(company_id, "inventory_document", document_id, "update_draft", {})

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
        """Post one expense allocated to receipt lines (a «Расходы по партии» document
        with a single charge). If part of a receipt has already been issued, that share
        is posted to the original issue expense account."""
        ids = list(dict.fromkeys(receipt_line_ids))
        if not ids:
            raise ValidationError(tr("не выбраны поступления для распределения"))
        if method == "manual" and (manual_amounts is None or set(manual_amounts) != set(ids)):
            raise ValidationError(tr("ручные суммы заданы не для всех поступлений"))
        manual = manual_amounts or {}
        with transaction(self.conn):
            inv_id = self.create_landed_cost_draft(
                company_id,
                doc_date,
                [LandedCostTarget(i, manual.get(i)) for i in ids],
                [
                    LandedCostCharge(
                        total_amount,
                        credit_account_id,
                        credit_subconto,
                        cost_type_id=cost_type_id,
                    )
                ],
                method,
                memo,
                cost_type_id=cost_type_id,
            )
            self._post_in_sequence(company_id, inv_id)
        return inv_id

    # ---- posting in date order ------------------------------------------------------

    def _post_in_sequence(self, company_id: int, document_id: int) -> None:
        """Post a draft into its place in the date order, recalculating later documents."""
        doc = self._document(company_id, document_id)
        self._apply_in_order(company_id, document_id, self._withdraw_after(company_id, doc))

    def _unpost(self, company_id: int, doc: sqlite3.Row) -> None:
        """Take a posted document out of the sequence: it becomes a draft without GL
        postings, and the documents after it are recalculated without it."""
        self._require_open_period(doc)
        later = self._withdraw_after(company_id, doc)
        self._withdraw(company_id, doc)
        gl_document_id = doc["gl_document_id"]
        self.conn.execute(
            "UPDATE inventory_documents SET gl_document_id = NULL, posted_at = NULL WHERE id = ?",
            (doc["id"],),
        )
        if gl_document_id is not None:
            self.ledger.delete_document(company_id, gl_document_id)
        self._apply_in_order(company_id, None, later)

    def _withdraw_after(self, company_id: int, doc: sqlite3.Row) -> list[int]:
        """Withdraw every posted document that comes after `doc` (latest first)."""
        key = _sequence_key(doc)
        later = sorted(
            (
                row
                for row in self.conn.execute(
                    "SELECT * FROM inventory_documents "
                    "WHERE company_id = ? AND status = 'posted' AND doc_date >= ? AND id <> ?",
                    (company_id, doc["doc_date"], doc["id"]),
                )
                if _sequence_key(row) > key
            ),
            key=_sequence_key,
            reverse=True,
        )
        for row in later:
            self._withdraw(company_id, row)
        return [row["id"] for row in later]

    def _withdraw(self, company_id: int, doc: sqlite3.Row) -> None:
        """Remove the stock effect of a posted document; it stays a draft that still
        points to its GL document, so posting it again keeps that document's number."""
        document_id = doc["id"]
        self.conn.execute(
            "UPDATE inventory_documents SET status = 'draft' WHERE id = ?", (document_id,)
        )
        for table in (
            "landed_cost_expense_allocations",
            "landed_cost_shares",
            "stock_consumptions",
            "stock_movements",
        ):
            self.conn.execute(f"DELETE FROM {table} WHERE document_id = ?", (document_id,))
        if doc["doc_type"] in {"issue", "transfer"}:
            self.conn.execute(
                "UPDATE inventory_lines SET amount = 0, inventory_amount = 0, "
                "expense_amount = 0 WHERE document_id = ?",
                (document_id,),
            )
        elif doc["doc_type"] == "landed_cost":
            self.conn.execute(
                "UPDATE inventory_lines SET inventory_amount = 0, expense_amount = 0 "
                "WHERE document_id = ?",
                (document_id,),
            )

    def _apply_in_order(
        self, company_id: int, document_id: int | None, later: Sequence[int]
    ) -> None:
        """Post `document_id` and the withdrawn `later` documents in date order. A later
        document that no longer fits (not enough stock…) names itself in the error."""
        docs = [self._document(company_id, i) for i in dict.fromkeys(later)]
        if document_id is not None:
            docs.append(self._document(company_id, document_id))
        for doc in sorted(docs, key=_sequence_key):
            if doc["id"] == document_id:
                self._apply(company_id, doc)
                continue
            try:
                self._apply(company_id, doc)
            except LedgerError as exc:
                raise ValidationError(
                    tr(
                        "после изменения не проводится складской документ №{n} от {date}: {error}",
                        n=doc["number"],
                        date=ru_date(doc["doc_date"]),
                        error=exc,
                    )
                ) from exc

    def _apply(self, company_id: int, doc: sqlite3.Row) -> None:
        """Post a draft: movements, derived amounts and its GL document."""
        lines = self.conn.execute(
            "SELECT * FROM inventory_lines WHERE document_id = ? ORDER BY line_no",
            (doc["id"],),
        ).fetchall()
        if not lines:
            raise ValidationError(tr("складской документ без строк"))
        if doc["doc_type"] == "landed_cost":
            postings = self._apply_landed_cost(company_id, doc, lines)
        else:
            postings = [self._apply_line(company_id, doc, line) for line in lines]
            if doc["doc_type"] == "receipt":
                postings += self._vat_postings(
                    company_id,
                    (doc["invoice"] or "", doc["invoice_kind"] or ""),
                    [
                        (
                            line["offset_account_id"],
                            (line["offset_sc1"], line["offset_sc2"], line["offset_sc3"]),
                            line["vat_amount"],
                        )
                        for line in lines
                    ],
                )
        self._finish(doc["id"], company_id, doc["doc_date"], postings, doc["memo"])

    def _apply_line(self, company_id: int, doc: sqlite3.Row, line: sqlite3.Row) -> PostingInput:
        document_id = doc["id"]
        self._require_complete(doc["doc_type"], line)
        item = self._item(company_id, line["item_id"])
        warehouse = self._warehouse(company_id, line["warehouse_id"])
        offset_sc = (line["offset_sc1"], line["offset_sc2"], line["offset_sc3"])
        if doc["doc_type"] in {"opening", "receipt"}:
            amount = line["amount"]
            self._insert_movement(
                company_id,
                document_id,
                line["id"],
                doc["doc_date"],
                item["id"],
                warehouse["id"],
                doc["doc_type"],
                line["quantity"],
                amount,
            )
            in_currency = doc["currency_id"] is not None and doc["doc_type"] == "receipt"
            return PostingInput(
                item["inventory_account_id"],
                line["offset_account_id"],
                _money(amount),
                self._inventory_subconto(company_id, item, warehouse),
                offset_sc,
                line["memo"],
                doc["currency_id"] if in_currency else None,
                _money(line["currency_amount"] or 0) if in_currency else None,
                doc["invoice"] or "",
                doc["invoice_kind"] or "",
            )

        balance_qty, balance_amount = self._balance(
            company_id, item["id"], warehouse["id"], document_id
        )
        self._require_stock(item, warehouse, line["quantity"], balance_qty)
        amount = (
            balance_amount
            if line["quantity"] == balance_qty
            else round_ratio(balance_amount * line["quantity"], balance_qty)
        )
        self.conn.execute(
            "UPDATE inventory_lines SET amount = ?, inventory_amount = ?, "
            "expense_amount = ? WHERE id = ?",
            (
                amount,
                amount if doc["doc_type"] == "transfer" else 0,
                amount if doc["doc_type"] == "issue" else 0,
                line["id"],
            ),
        )
        if doc["doc_type"] == "issue":
            self._consume_receipts(
                company_id, document_id, line["id"], item["id"], line["quantity"]
            )
            self._insert_movement(
                company_id,
                document_id,
                line["id"],
                doc["doc_date"],
                item["id"],
                warehouse["id"],
                "issue",
                -line["quantity"],
                -amount,
            )
            return PostingInput(
                line["offset_account_id"],
                item["inventory_account_id"],
                _money(amount),
                offset_sc,
                self._inventory_subconto(company_id, item, warehouse),
                line["memo"],
            )

        to_warehouse = self._warehouse(company_id, line["to_warehouse_id"])
        if warehouse["id"] == to_warehouse["id"]:
            raise ValidationError(tr("склад отправитель и получатель совпадают"))
        for target, movement_type, sign in (
            (warehouse, "transfer_out", -1),
            (to_warehouse, "transfer_in", 1),
        ):
            self._insert_movement(
                company_id,
                document_id,
                line["id"],
                doc["doc_date"],
                item["id"],
                target["id"],
                movement_type,
                sign * line["quantity"],
                sign * amount,
            )
        return PostingInput(
            item["inventory_account_id"],
            item["inventory_account_id"],
            _money(amount),
            self._inventory_subconto(company_id, item, to_warehouse),
            self._inventory_subconto(company_id, item, warehouse),
            line["memo"],
        )

    def _vat_postings(
        self,
        company_id: int,
        invoice: tuple[str, str],  # (number, kind) of the receipt's e-qaimə / declaration
        items: Sequence[tuple[int, tuple[int | None, ...], int]],
    ) -> list[PostingInput]:
        """Dr input VAT / Cr the settlement account for (account, subconto, VAT) items: one
        posting per supplier (the same account and subconto). The VAT account takes the
        supplier's subconto by kind."""
        totals: dict[tuple[int, tuple[int | None, ...]], int] = {}
        for account_id, subconto, vat in items:
            if vat:
                key = (account_id, tuple(subconto))
                totals[key] = totals.get(key, 0) + vat
        if not totals:
            return []
        vat_account_id = self.ledger.account_role(company_id, INPUT_VAT)
        if vat_account_id is None:
            raise ValidationError(
                tr("не указан счёт НДС к возмещению — выберите его в настройках склада")
            )
        vat_kinds = self._account_kind_ids(self._account(company_id, vat_account_id))
        result = []
        for (account_id, offset_sc), amount in totals.items():
            by_kind = {
                self._subconto_value(company_id, value_id)["kind_id"]: value_id
                for value_id in offset_sc
                if value_id is not None
            }
            result.append(
                PostingInput(
                    vat_account_id,
                    account_id,
                    _money(amount),
                    tuple(None if kind is None else by_kind.get(kind) for kind in vat_kinds),
                    offset_sc,
                    tr("НДС"),
                    invoice=invoice[0],
                    invoice_kind=invoice[1],
                )
            )
        return result

    def _apply_landed_cost(
        self, company_id: int, doc: sqlite3.Row, lines: Sequence[sqlite3.Row]
    ) -> list[PostingInput]:
        """Allocate the charges over the batch, then split each receipt line's share between
        the stock still on hand and the expense accounts of what was already issued."""
        charges = self._charges(doc["id"])
        if not charges:
            raise ValidationError(tr("в документе нет расходов"))
        for charge in charges:
            self._require_charge_complete(company_id, doc, charge)
        total = sum(charge["amount"] for charge in charges)
        receipts = {
            line["id"]: self._landed_cost_source(company_id, line["source_receipt_line_id"])
            for line in lines
        }
        targets = self._landed_cost_targets(doc, lines, receipts, total)
        shares = split_charges([(c["id"], c["amount"]) for c in charges], targets)
        for (charge_id, line_id), share in shares.items():
            self.conn.execute(
                "INSERT INTO landed_cost_shares "
                "(company_id, document_id, charge_id, line_id, amount) VALUES (?, ?, ?, ?, ?)",
                (company_id, doc["id"], charge_id, line_id, share),
            )
        in_currency: dict[tuple[int, int], int] = {}  # a charge's currency amount by line
        for charge in charges:
            mine = [(line_id, v) for (c, line_id), v in shares.items() if c == charge["id"]]
            if charge["currency_id"] is not None and charge["currency_amount"] and mine:
                for line_id, value in allocate_minor(charge["currency_amount"], mine).items():
                    in_currency[(charge["id"], line_id)] = value
        postings: list[PostingInput] = []
        for line in lines:
            allocated = targets[line["id"]]
            debits, inventory_amount, expense_amount = (
                self._landed_cost_debits(company_id, doc, line, receipts[line["id"]], allocated)
                if allocated
                else ([], 0, 0)
            )
            credits = [
                _Credit(
                    charge["account_id"],
                    (charge["sc1"], charge["sc2"], charge["sc3"]),
                    shares[(charge["id"], line["id"])],
                    self._charge_memo(company_id, doc, charge),
                    charge["currency_id"],
                    in_currency.get((charge["id"], line["id"]), 0),
                )
                for charge in charges
                if (charge["id"], line["id"]) in shares
            ]
            postings += _pair(debits, credits)
            self.conn.execute(
                "UPDATE inventory_lines SET amount = ?, inventory_amount = ?, "
                "expense_amount = ? WHERE id = ?",
                (allocated, inventory_amount, expense_amount, line["id"]),
            )
        return postings + self._vat_postings(
            company_id,
            ("", ""),
            [
                (charge["account_id"], (charge["sc1"], charge["sc2"], charge["sc3"]), vat)
                for charge in charges
                if (vat := charge["vat_amount"])
            ],
        )

    def _landed_cost_targets(
        self,
        doc: sqlite3.Row,
        lines: Sequence[sqlite3.Row],
        receipts: Mapping[int, sqlite3.Row],
        total: int,
    ) -> dict[int, int]:
        """Line id -> its share of all the charges."""
        if not lines:
            raise ValidationError(tr("не выбраны поступления для распределения"))
        method = doc["allocation_method"] or "value"
        if method == "manual":
            allocated = sum(line["amount"] for line in lines)
            if allocated != total:
                raise ValidationError(
                    tr(
                        "распределено {allocated}, а расходов {total}",
                        allocated=format_minor(allocated),
                        total=format_minor(total),
                    )
                )
            return {line["id"]: line["amount"] for line in lines}
        field = "amount" if method == "value" else "quantity"
        return allocate_minor(total, [(line["id"], receipts[line["id"]][field]) for line in lines])

    def _landed_cost_debits(
        self,
        company_id: int,
        doc: sqlite3.Row,
        line: sqlite3.Row,
        receipt: sqlite3.Row,
        allocated: int,
    ) -> tuple[list[tuple[int, Sequence[int | None], int]], int, int]:
        """Where a receipt line's share goes: (debit pieces, to stock, to expense)."""
        consumptions = self._receipt_consumptions(company_id, receipt["id"])
        consumed_quantity = sum(row["quantity"] for row in consumptions)
        remaining_quantity = receipt["quantity"] - consumed_quantity
        inventory_amount = round_ratio(allocated * remaining_quantity, receipt["quantity"])
        expense_amount = allocated - inventory_amount
        debits: list[tuple[int, Sequence[int | None], int]] = []
        if inventory_amount:
            stock = self._landed_cost_to_stock(
                company_id,
                doc["id"],
                line["id"],
                doc["doc_date"],
                self._item(company_id, receipt["item_id"]),
                inventory_amount,
            )
            if stock is None:  # nothing left in stock: all of it is expense
                expense_amount += inventory_amount
                inventory_amount = 0
            else:
                debits += stock
        if expense_amount:
            debits += self._landed_cost_to_expense(
                company_id, doc["id"], line["id"], consumptions, expense_amount
            )
        return debits, inventory_amount, expense_amount

    def _charges(self, document_id: int) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM landed_cost_charges WHERE document_id = ? ORDER BY line_no",
            (document_id,),
        ).fetchall()

    def _charge_memo(self, company_id: int, doc: sqlite3.Row, charge: sqlite3.Row) -> str:
        if charge["memo"]:
            return charge["memo"]
        if charge["cost_type_id"] is not None:
            return self._cost_type(company_id, charge["cost_type_id"])["name"]
        return doc["memo"]

    def _require_charge_complete(
        self, company_id: int, doc: sqlite3.Row, charge: sqlite3.Row
    ) -> None:
        n = charge["line_no"]
        if charge["amount"] <= 0:
            raise ValidationError(tr("расход {n}: не указана сумма", n=n))
        if charge["account_id"] is None:
            raise ValidationError(tr("расход {n}: не указан счёт", n=n))
        if charge["source_document_id"] is None:
            return
        posting = self._cost_source(
            company_id, charge["source_document_id"], charge["source_line_no"]
        )
        used = self.conn.execute(
            "SELECT COALESCE(SUM(c.amount), 0) FROM landed_cost_charges c "
            "JOIN inventory_documents d ON d.id = c.document_id "
            "WHERE c.company_id = ? AND c.source_document_id = ? AND c.source_line_no = ? "
            "AND d.status = 'posted' AND c.document_id <> ?",
            (company_id, charge["source_document_id"], charge["source_line_no"], doc["id"]),
        ).fetchone()[0]
        if used + charge["amount"] > posting["amount"]:
            raise ValidationError(
                tr(
                    "расход {n}: проводка документа №{number} — {amount}, уже распределено "
                    "{used}, осталось {left}",
                    n=n,
                    number=posting["number"],
                    amount=format_minor(posting["amount"]),
                    used=format_minor(used),
                    left=format_minor(max(posting["amount"] - used, 0)),
                )
            )

    def _cost_source(self, company_id: int, document_id: int, line_no: int) -> sqlite3.Row:
        """A GL posting an expense line takes: posted, in the common book, not one the
        warehouse made itself, with a positive amount."""
        row = self.conn.execute(
            """
            SELECT p.*, d.number, d.status, l.code AS layer,
                   EXISTS (SELECT 1 FROM inventory_documents i
                           WHERE i.gl_document_id = d.id) AS from_inventory
            FROM postings p
            JOIN documents d ON d.id = p.document_id
            JOIN layers l ON l.id = d.layer_id
            WHERE p.company_id = ? AND p.document_id = ? AND p.line_no = ?
            """,
            (company_id, document_id, line_no),
        ).fetchone()
        if row is None or row["status"] != "posted":
            raise ValidationError(tr("проводка-источник расхода не найдена или не проведена"))
        if row["from_inventory"]:
            raise ValidationError(tr("проводку складского документа нельзя взять как расход"))
        if row["layer"] != "common" or row["amount"] <= 0:
            raise ValidationError(
                tr("как расход можно взять только обычную проводку с положительной суммой")
            )
        return row

    def _write_landed_cost_draft(
        self,
        company_id: int,
        document_id: int,
        targets: Sequence[LandedCostTarget],
        charges: Sequence[LandedCostCharge],
        method: str,
    ) -> None:
        if method not in ALLOCATION_METHODS:
            raise ValidationError(tr("неизвестный способ распределения"))
        if not targets:
            raise ValidationError(tr("не выбраны поступления для распределения"))
        self.conn.execute(
            "UPDATE inventory_documents SET allocation_method = ? WHERE id = ?",
            (method, document_id),
        )
        seen: set[int] = set()
        for line_no, target in enumerate(targets, 1):
            receipt = self._receipt_line(company_id, target.receipt_line_id)
            if receipt["id"] in seen:
                raise ValidationError(tr("строка поступления выбрана дважды"))
            seen.add(receipt["id"])
            amount = (
                0
                if target.amount is None or _blank(target.amount)
                else self._nonnegative_amount(target.amount)
            )
            self._insert_line(
                document_id,
                company_id,
                line_no,
                receipt["item_id"],
                receipt["warehouse_id"],
                None,
                0,
                amount,
                0,
                0,
                None,
                (),
                receipt["id"],
                "",
                line_id=target.line_id,
            )
        self.conn.execute("DELETE FROM landed_cost_charges WHERE document_id = ?", (document_id,))
        for line_no, charge in enumerate(charges, 1):
            self._insert_charge(company_id, document_id, line_no, charge)

    def _insert_charge(
        self, company_id: int, document_id: int, line_no: int, charge: LandedCostCharge
    ) -> None:
        amount = (
            0
            if charge.amount is None or _blank(charge.amount)
            else self._positive_amount(charge.amount, line_no)
        )
        vat = (
            0
            if charge.vat_amount is None or _blank(charge.vat_amount)
            else self._nonnegative_amount(charge.vat_amount)
        )
        currency_id = rate = currency_amount = None
        if charge.currency_id is not None:
            if charge.source_document_id is not None:
                raise ValidationError(tr("расход {n}: проводка-источник уже в манатах", n=line_no))
            if vat:
                raise ValidationError(
                    tr("расход {n}: в расходе в валюте НДС не указывается", n=line_no)
                )
            currency_id = self._currency_id(company_id, charge.currency_id)
            rate = self._rate(charge.currency_rate)
            value = charge.currency_amount
            currency_amount = (
                0 if value is None or _blank(value) else self._positive_amount(value, line_no)
            )
            amount = to_base(currency_amount, unit_rate(rate))
        if charge.cost_type_id is not None:
            self._cost_type(company_id, charge.cost_type_id)
        if charge.source_document_id is not None:
            if charge.source_line_no is None:
                raise ValidationError(tr("не указана строка проводки-источника"))
            if vat:
                raise ValidationError(
                    tr("расход {n}: НДС уже учтён в документе-источнике", n=line_no)
                )
            posting = self._cost_source(
                company_id, charge.source_document_id, charge.source_line_no
            )
            account_id = posting["debit_account_id"]
            subconto = (posting["dt_sc1"], posting["dt_sc2"], posting["dt_sc3"])
        else:
            account_id = charge.account_id
            if account_id is not None:
                self._account(company_id, account_id)
            subconto = pad_subconto(charge.subconto)
        self.conn.execute(
            "INSERT INTO landed_cost_charges (company_id, document_id, line_no, cost_type_id, "
            "account_id, sc1, sc2, sc3, amount, vat_amount, source_document_id, "
            "source_line_no, memo, currency_id, currency_rate, currency_amount) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                company_id,
                document_id,
                line_no,
                charge.cost_type_id,
                account_id,
                *subconto,
                amount,
                vat,
                charge.source_document_id,
                charge.source_line_no if charge.source_document_id is not None else None,
                charge.memo.strip(),
                currency_id,
                rate,
                currency_amount,
            ),
        )

    def _landed_cost_source(self, company_id: int, line_id: int) -> sqlite3.Row:
        row = self.conn.execute(
            """
            SELECT l.*, d.number, d.status FROM inventory_lines l
            JOIN inventory_documents d ON d.id = l.document_id
            WHERE l.company_id = ? AND l.id = ?
            """,
            (company_id, line_id),
        ).fetchone()
        if row is None or row["status"] != "posted":
            raise ValidationError(
                tr(
                    "расходы распределены на поступление №{n}, которое не проведено",
                    n=row["number"] if row else "?",
                )
            )
        return row

    def _landed_cost_to_stock(
        self,
        company_id: int,
        inv_id: int,
        line_id: int,
        doc_date: date | str,
        item: sqlite3.Row,
        amount: int,
    ) -> list[tuple[int, Sequence[int | None], int]] | None:
        """Add `amount` to the item's stock value in each warehouse in proportion to its
        quantity there. None when no warehouse has the item any more."""
        balances = self._item_warehouse_quantities(company_id, item["id"])
        if not balances:
            return None
        postings = []
        for warehouse_id, share in allocate_minor(amount, balances).items():
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
                (
                    item["inventory_account_id"],
                    self._inventory_subconto(company_id, item, warehouse),
                    share,
                )
            )
        return postings

    def _landed_cost_to_expense(
        self,
        company_id: int,
        inv_id: int,
        line_id: int,
        consumptions: list[sqlite3.Row],
        amount: int,
    ) -> list[tuple[int, Sequence[int | None], int]]:
        """Charge `amount` to the expense accounts of the issues that consumed the receipt,
        in proportion to the quantity each took."""
        if not consumptions:
            raise ValidationError(tr("не найдены списания для распределения расхода"))
        by_issue = allocate_minor(
            amount, [(row["issue_line_id"], row["quantity"]) for row in consumptions]
        )
        issues = {row["issue_line_id"]: row for row in consumptions}
        postings = []
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
                (
                    issue["offset_account_id"],
                    (issue["offset_sc1"], issue["offset_sc2"], issue["offset_sc3"]),
                    share,
                )
            )
        return postings

    def delete_document(self, company_id: int, document_id: int) -> None:
        """Remove an inventory document (a posted one in an open period), with a full
        audit copy. Later documents are recalculated without it."""
        with transaction(self.conn):
            doc = self._document(company_id, document_id)
            snapshot = self._snapshot(doc)
            if doc["status"] == "posted":
                self._unpost(company_id, doc)
            self._require_lines_unreferenced(company_id, document_id, keep=())
            self.conn.execute("DELETE FROM inventory_documents WHERE id = ?", (document_id,))
            self._audit(company_id, "inventory_document", document_id, "delete", snapshot)

    # ---- internals -----------------------------------------------------------------

    def _write_receipt_draft(
        self,
        company_id: int,
        document_id: int,
        lines: Sequence[ReceiptLine],
        credit_account_id: int | None,
        credit_subconto: Sequence[int | None],
    ) -> None:
        if not lines:
            raise ValidationError(tr("складской документ без строк"))
        doc = self._document(company_id, document_id)
        doc_type = doc["doc_type"]
        for line_no, source in enumerate(lines, 1):
            item = self._item(company_id, source.item_id)
            warehouse_id = self._draft_warehouse(company_id, source.warehouse_id)
            quantity = self._draft_quantity(item, source.quantity, line_no)
            currency_amount, amount = self._line_amounts(doc, source, line_no)
            vat = (
                0
                if source.vat_amount is None or _blank(source.vat_amount)
                else self._nonnegative_amount(source.vat_amount)
            )
            if vat and doc_type != "receipt":
                raise ValidationError(tr("НДС указывается только в поступлении"))
            if vat and doc["currency_id"] is not None:
                raise ValidationError(
                    tr("в поступлении в валюте НДС не указывается: импортный НДС — в расходах")
                )
            line_credit_account = source.credit_account_id or credit_account_id
            if line_credit_account is not None:
                self._account(company_id, line_credit_account)
            line_credit_sc = pad_subconto(source.credit_subconto or credit_subconto)
            self._insert_line(
                document_id,
                company_id,
                line_no,
                item["id"],
                warehouse_id,
                None,
                quantity,
                amount,
                amount,
                0,
                line_credit_account,
                line_credit_sc,
                None,
                source.memo.strip(),
                line_id=source.line_id,
                vat_amount=vat,
                currency_amount=currency_amount,
            )

    def _line_amounts(
        self, doc: sqlite3.Row, source: ReceiptLine, line_no: int
    ) -> tuple[int | None, int]:
        """(amount in the currency, amount in manat) of a receipt line. In a currency the
        manat amount follows from the document's rate."""
        if doc["currency_id"] is None:
            if _blank(source.amount):
                return None, 0
            return None, self._positive_amount(source.amount, line_no)
        value = source.currency_amount
        if value is None or _blank(value):
            return 0, 0
        currency_amount = self._positive_amount(value, line_no)
        return currency_amount, to_base(currency_amount, unit_rate(doc["currency_rate"]))

    def _set_currency(
        self,
        company_id: int,
        document_id: int,
        currency_id: int | None,
        rate: str | int | Decimal | None,
    ) -> None:
        if currency_id is None:
            self.conn.execute(
                "UPDATE inventory_documents SET currency_id = NULL, currency_rate = NULL "
                "WHERE id = ?",
                (document_id,),
            )
            return
        if self._document(company_id, document_id)["doc_type"] != "receipt":
            raise ValidationError(tr("в валюте может быть только поступление"))
        self.conn.execute(
            "UPDATE inventory_documents SET currency_id = ?, currency_rate = ? WHERE id = ?",
            (self._currency_id(company_id, currency_id), self._rate(rate), document_id),
        )

    def _currency_id(self, company_id: int, currency_id: int) -> int:
        row = self.conn.execute(
            "SELECT id FROM currencies WHERE company_id = ? AND id = ?", (company_id, currency_id)
        ).fetchone()
        if row is None:
            raise NotFoundError(tr("валюта не найдена"))
        return row["id"]

    @staticmethod
    def _rate(rate: str | int | Decimal | None) -> int:
        """A typed rate (manat per unit) -> millionths."""
        if rate is None or _blank(rate):
            raise ValidationError(tr("не указан курс валюты"))
        try:
            return parse_rate(rate)
        except (TypeError, ValueError) as exc:
            raise ValidationError(str(exc)) from exc

    def _write_issue_draft(
        self, company_id: int, document_id: int, lines: Sequence[IssueLine]
    ) -> None:
        if not lines:
            raise ValidationError(tr("складской документ без строк"))
        for line_no, source in enumerate(lines, 1):
            item = self._item(company_id, source.item_id)
            warehouse_id = self._draft_warehouse(company_id, source.warehouse_id)
            quantity = self._draft_quantity(item, source.quantity, line_no)
            if source.expense_account_id is not None:
                self._account(company_id, source.expense_account_id)
            expense_sc = pad_subconto(source.expense_subconto)
            self._insert_line(
                document_id,
                company_id,
                line_no,
                item["id"],
                warehouse_id,
                None,
                quantity,
                0,
                0,
                0,
                source.expense_account_id,
                expense_sc,
                None,
                source.memo.strip(),
                line_id=source.line_id,
            )

    def _write_transfer_draft(
        self, company_id: int, document_id: int, lines: Sequence[TransferLine]
    ) -> None:
        if not lines:
            raise ValidationError(tr("складской документ без строк"))
        for line_no, source in enumerate(lines, 1):
            if (
                source.from_warehouse_id is not None
                and source.from_warehouse_id == source.to_warehouse_id
            ):
                raise ValidationError(tr("склад отправитель и получатель совпадают"))
            item = self._item(company_id, source.item_id)
            from_warehouse_id = self._draft_warehouse(company_id, source.from_warehouse_id)
            to_warehouse_id = self._draft_warehouse(company_id, source.to_warehouse_id)
            quantity = self._draft_quantity(item, source.quantity, line_no)
            self._insert_line(
                document_id,
                company_id,
                line_no,
                item["id"],
                from_warehouse_id,
                to_warehouse_id,
                quantity,
                0,
                0,
                0,
                None,
                (),
                None,
                source.memo.strip(),
                line_id=source.line_id,
            )

    def _release_lines(
        self,
        company_id: int,
        document_id: int,
        lines: Sequence[ReceiptLine]
        | Sequence[IssueLine]
        | Sequence[TransferLine]
        | Sequence[LandedCostTarget],
    ) -> None:
        """Before a draft is rewritten: drop the lines that are gone, renumber the rest
        out of the way (line numbers are unique within a document)."""
        keep = {line.line_id for line in lines if line.line_id is not None}
        self._require_lines_unreferenced(company_id, document_id, keep)
        placeholders = ",".join("?" * len(keep))
        self.conn.execute(
            f"DELETE FROM inventory_lines WHERE document_id = ? AND id NOT IN ({placeholders})",
            (document_id, *keep),
        )
        self.conn.execute(
            "UPDATE inventory_lines SET line_no = -line_no WHERE document_id = ?", (document_id,)
        )

    def _require_lines_unreferenced(
        self, company_id: int, document_id: int, keep: set[int] | tuple[()]
    ) -> None:
        """A receipt line that landed cost was allocated to cannot disappear."""
        used = [
            row
            for row in self.conn.execute(
                """
                SELECT own.id, own.line_no, d.number
                FROM inventory_lines own
                JOIN inventory_lines lc ON lc.source_receipt_line_id = own.id
                JOIN inventory_documents d ON d.id = lc.document_id
                WHERE own.company_id = ? AND own.document_id = ? AND lc.document_id <> ?
                ORDER BY own.line_no
                """,
                (company_id, document_id, document_id),
            )
            if row["id"] not in keep
        ]
        if used:
            raise ValidationError(
                tr(
                    "строка {line}: на неё распределены дополнительные расходы "
                    "(документ №{n}) — сначала удалите их",
                    line=abs(used[0]["line_no"]),
                    n=used[0]["number"],
                )
            )

    def _update_draft_header(
        self, company_id: int, document_id: int, doc_date: date | str, memo: str
    ) -> None:
        value_date = iso_date(doc_date)
        self.conn.execute(
            "UPDATE inventory_documents SET doc_date = ?, memo = ? WHERE company_id = ? AND id = ?",
            (value_date, memo.strip(), company_id, document_id),
        )

    def _set_invoice(self, document_id: int, invoice: str, kind: str = EQAIME) -> None:
        """The receipt's e-qaimə, or the customs declaration of imported goods."""
        if kind not in KINDS:
            raise ValidationError(tr("неизвестный вид документа: {kind}", kind=kind))
        number = normalize_invoice(invoice)
        self.conn.execute(
            "UPDATE inventory_documents SET invoice = ?, invoice_kind = ? WHERE id = ?",
            (number, (kind or None) if number else None, document_id),
        )

    def _set_vat_rate(self, document_id: int, rate: int | None) -> None:
        if rate is not None and not 0 <= rate <= VAT_RATE_SCALE:
            raise ValidationError(tr("ставка НДС должна быть от 0 до 100%"))
        self.conn.execute(
            "UPDATE inventory_documents SET vat_rate = ? WHERE id = ?", (rate, document_id)
        )

    def _draft_warehouse(self, company_id: int, warehouse_id: int | None) -> int | None:
        return None if warehouse_id is None else self._warehouse(company_id, warehouse_id)["id"]

    def _draft_quantity(
        self, item: sqlite3.Row, value: str | int | Decimal | None, line_no: int
    ) -> int:
        return 0 if _blank(value) else self._quantity(item, value, line_no)

    @staticmethod
    def _require_complete(doc_type: str, line: sqlite3.Row) -> None:
        """A draft may be unfinished; posting needs every field of the line."""
        line_no = line["line_no"]
        if line["warehouse_id"] is None:
            raise ValidationError(tr("строка {line}: не указан склад", line=line_no))
        if line["quantity"] <= 0:
            raise ValidationError(tr("строка {line}: не указано количество", line=line_no))
        if doc_type == "transfer":
            if line["to_warehouse_id"] is None:
                raise ValidationError(tr("строка {line}: не указан склад-получатель", line=line_no))
            return
        if doc_type in {"opening", "receipt"} and line["amount"] <= 0:
            raise ValidationError(tr("строка {line}: не указана сумма", line=line_no))
        if line["offset_account_id"] is None:
            raise ValidationError(tr("строка {line}: не указан счёт", line=line_no))

    def _require_inventory_draft(self, company_id: int, document_id: int) -> sqlite3.Row:
        doc = self._document(company_id, document_id)
        if doc["status"] != "draft":
            raise ValidationError(tr("сначала отмените проведение складского документа"))
        return doc

    def _require_open_period(self, doc: sqlite3.Row) -> None:
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
        number = self.conn.execute(
            "UPDATE companies SET last_inventory_number = last_inventory_number + 1 "
            "WHERE id = ? RETURNING last_inventory_number",
            (company_id,),
        ).fetchone()[0]
        return insert(
            self.conn,
            "INSERT INTO inventory_documents "
            "(company_id, number, doc_date, doc_type, memo, status, landed_cost_type_id, "
            "created_at) VALUES (?, ?, ?, ?, ?, 'draft', ?, ?)",
            (company_id, number, value_date, doc_type, memo, cost_type_id, now()),
        )

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
        *,
        line_id: int | None = None,
        vat_amount: int = 0,
        currency_amount: int | None = None,
    ) -> int:
        sc = pad_subconto(offset_subconto)
        if line_id is not None:  # an edited line keeps its id: landed cost refers to it
            updated = self.conn.execute(
                "UPDATE inventory_lines SET line_no = ?, item_id = ?, warehouse_id = ?, "
                "to_warehouse_id = ?, quantity = ?, amount = ?, inventory_amount = ?, "
                "expense_amount = ?, offset_account_id = ?, offset_sc1 = ?, offset_sc2 = ?, "
                "offset_sc3 = ?, source_receipt_line_id = ?, memo = ?, vat_amount = ?, "
                "currency_amount = ? WHERE company_id = ? AND document_id = ? AND id = ?",
                (
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
                    vat_amount,
                    currency_amount,
                    company_id,
                    document_id,
                    line_id,
                ),
            ).rowcount
            if updated:
                return line_id
        return insert(
            self.conn,
            "INSERT INTO inventory_lines (company_id, document_id, line_no, item_id, "
            "warehouse_id, to_warehouse_id, quantity, amount, inventory_amount, "
            "expense_amount, offset_account_id, offset_sc1, offset_sc2, offset_sc3, "
            "source_receipt_line_id, memo, vat_amount, currency_amount) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
                vat_amount,
                currency_amount,
            ),
        )

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
        """Mark the document posted with its GL document. A recalculated document rewrites
        its existing GL document, which keeps its number."""
        if not postings:
            raise ValidationError(tr("складской документ не создал проводок"))
        doc = self._document(company_id, inventory_document_id)
        gl_document_id = doc["gl_document_id"]
        if gl_document_id is None:
            gl_document_id = self.ledger.post_new(company_id, doc_date, postings, memo)
        else:
            self.ledger.rewrite_linked(company_id, gl_document_id, doc_date, postings, memo)
        self.conn.execute(
            "UPDATE inventory_documents SET status = 'posted', gl_document_id = ?, "
            "posted_at = COALESCE(posted_at, ?) WHERE id = ?",
            (gl_document_id, now(), inventory_document_id),
        )
        if doc["posted_at"] is None:  # recalculation after an edit is not a new posting
            self._audit(
                company_id,
                "inventory_document",
                inventory_document_id,
                "post",
                {
                    "number": doc["number"],
                    "type": doc["doc_type"],
                    "gl_document_id": gl_document_id,
                },
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

    def _account_kind_ids(self, account: sqlite3.Row) -> tuple[int | None, ...]:
        return tuple(account[f"sc{position}_kind_id"] for position in range(1, 4))

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

    def _quantity(self, item: sqlite3.Row, value: str | int | Decimal | None, line_no: int) -> int:
        if value is None or _blank(value):
            raise ValidationError(tr("строка {line}: не указано количество", line=line_no))
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
    def _positive_amount(value: str | int | Decimal | None, line_no: int) -> int:
        if value is None or _blank(value):
            if line_no:
                raise ValidationError(tr("строка {line}: не указана сумма", line=line_no))
            raise ValidationError(tr("сумма должна быть положительной"))
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
        return company_row(self.conn, company_id)

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

    def _line_warehouse(
        self, company_id: int, warehouse_id: int | None, line_no: int
    ) -> sqlite3.Row:
        if warehouse_id is None:
            raise ValidationError(tr("строка {line}: не указан склад", line=line_no))
        return self._warehouse(company_id, warehouse_id)

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
            "vat_rate": doc["vat_rate"],
            "allocation_method": doc["allocation_method"],
            "currency_id": doc["currency_id"],
            "currency_rate": doc["currency_rate"],
            "invoice": doc["invoice"],
            "invoice_kind": doc["invoice_kind"],
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
