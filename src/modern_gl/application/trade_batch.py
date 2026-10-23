"""Purchase and sale drafts posted in bulk (D73): the invoices of one supplier come every
month and are booked the same way, so the user filters them and posts them at once.

A purchase line without an item and without an account (a service, fuel) is "open": it
takes the account the user chose for the whole batch (D87), else the account and subconto
of the last posted purchase of the same name — from this supplier, else from anyone — else
of the supplier's last expense line (`queries.remembered_expense`, D76). A sale line
without its own subconto is open the same way when the sale accounts ask for one (a sales
group, D61): the batch's choice, else what the item or service had the last time.
The drafts post in date order, so one posted earlier in the batch teaches the later ones —
and the next batch: what was chosen is remembered by posting it, nothing else is stored.
Each draft is its own transaction: one that cannot post stays a draft and the reason is
reported."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from modern_gl.application.inventory import Inventory
from modern_gl.application.queries import remembered_expense, remembered_sale_subconto
from modern_gl.domain.errors import LedgerError
from modern_gl.infrastructure.db import Connection, Row, transaction


@dataclass(frozen=True)
class Booking:
    """Where the open lines of a batch go: a purchase's expense account and its subconto,
    and the account it is owed on (60, 76…; None: the one the draft has, D110); a sale's
    subconto only (`account_id` None: the revenue account is the company's one)."""

    account_id: int | None
    subconto: tuple[int | None, ...] = ()
    offset_account_id: int | None = None


@dataclass(frozen=True)
class OpenLines:
    """What a batch would ask: its open lines and, when they all went to one place the
    last time, that place (offered, so posting alike again is one Enter)."""

    doc_type: str  # 'receipt' or 'sale': the open lines of these drafts are counted
    count: int
    suggested: Booking | None
    # the account the open purchase lines are owed on now, when it is one (60 of the import)
    offset_account_id: int | None = None


@dataclass
class BulkPosting:
    posted: list[int] = field(default_factory=list)  # document ids
    filled: int = 0  # open lines given a place (chosen or like the last time)
    failed: list[tuple[int, str]] = field(default_factory=list)  # (number, why)


def open_lines(inventory: Inventory, company_id: int, document_ids: Sequence[int]) -> OpenLines:
    """The open lines of the purchase drafts among `document_ids` (of the sale drafts when
    there are no purchases)."""
    drafts = _drafts(inventory.conn, company_id, document_ids)
    doc_type = "sale" if drafts and all(d["doc_type"] == "sale" for d in drafts) else "receipt"
    places: set[Booking | None] = set()
    offsets: set[int | None] = set()
    count = 0
    for doc in drafts:
        if doc["doc_type"] != doc_type:
            continue
        for line in _open(inventory, company_id, doc):
            count += 1
            places.add(_remembered(inventory, company_id, doc, line))
            offsets.add(line["offset_account_id"])
    suggested = next(iter(places)) if len(places) == 1 else None
    offset = next(iter(offsets)) if len(offsets) == 1 and doc_type == "receipt" else None
    return OpenLines(doc_type, count, suggested, offset)


def post_drafts(
    inventory: Inventory,
    company_id: int,
    document_ids: Sequence[int],
    booking: Booking | None = None,
) -> BulkPosting:
    """Post the purchase and sale drafts among `document_ids`, earliest first. `booking`
    is for the open lines of the drafts of its kind (purchases when it has an account,
    sales when not); without it each open line goes where it went the last time."""
    result = BulkPosting()
    for doc in _drafts(inventory.conn, company_id, document_ids):
        try:
            with transaction(inventory.conn):
                filled = _fill(inventory, company_id, doc, booking)
                inventory.post_document(company_id, doc["id"])
        except LedgerError as exc:
            result.failed.append((doc["number"], str(exc)))
            continue
        result.posted.append(doc["id"])
        result.filled += filled
    return result


def _drafts(conn: Connection, company_id: int, document_ids: Sequence[int]) -> list[Row]:
    if not document_ids:
        return []
    marks = ", ".join("?" * len(document_ids))
    return conn.execute(
        f"SELECT id, number, doc_type FROM inventory_documents "
        f"WHERE company_id = ? AND id IN ({marks}) AND status = 'draft' "
        f"AND doc_type IN ('receipt', 'sale') ORDER BY doc_date, number",
        (company_id, *document_ids),
    ).fetchall()


def _open(inventory: Inventory, company_id: int, doc: Row) -> list[Row]:
    """A purchase's lines without an item and an account; a sale's lines without their own
    subconto, when the sale accounts ask for one."""
    if doc["doc_type"] == "receipt":
        where = "item_id IS NULL AND cost_account_id IS NULL"
    elif inventory.sale_kinds(company_id):
        where = "cost_sc1 IS NULL AND cost_sc2 IS NULL AND cost_sc3 IS NULL"
    else:
        return []
    return inventory.conn.execute(
        f"SELECT id, item_id, memo, offset_account_id FROM inventory_lines "
        f"WHERE company_id = ? AND document_id = ? AND {where} ORDER BY line_no",
        (company_id, doc["id"]),
    ).fetchall()


def _remembered(inventory: Inventory, company_id: int, doc: Row, line: Row) -> Booking | None:
    conn = inventory.conn
    party, memo = _counterparty(conn, company_id, doc["id"]), line["memo"] or ""
    if doc["doc_type"] == "receipt":
        found = remembered_expense(conn, company_id, memo, party)
        return Booking(found[0], tuple(found[1])) if found else None
    values = remembered_sale_subconto(
        conn, company_id, line["item_id"], memo, party, except_document=doc["id"]
    )
    return Booking(None, values) if values else None


def _fill(inventory: Inventory, company_id: int, doc: Row, booking: Booking | None) -> int:
    is_purchase = doc["doc_type"] == "receipt"
    chosen = booking if booking and (booking.account_id is not None) == is_purchase else None
    filled = 0
    for line in _open(inventory, company_id, doc):
        place = chosen or _remembered(inventory, company_id, doc, line)
        if place is None:
            continue
        if place.account_id is not None:
            inventory.fill_expense_account(
                company_id,
                doc["id"],
                line["id"],
                place.account_id,
                place.subconto,
                place.offset_account_id,
            )
        else:
            inventory.fill_sale_subconto(company_id, doc["id"], line["id"], place.subconto)
        filled += 1
    return filled


def _counterparty(conn: Connection, company_id: int, document_id: int) -> int | None:
    row = conn.execute(
        """
        SELECT v.id FROM inventory_lines x
        JOIN subconto_values v
          ON v.company_id = x.company_id AND v.id IN (x.offset_sc1, x.offset_sc2, x.offset_sc3)
        JOIN subconto_kinds k ON k.id = v.kind_id AND k.code = 'counterparty'
        WHERE x.company_id = ? AND x.document_id = ?
        ORDER BY x.line_no LIMIT 1
        """,
        (company_id, document_id),
    ).fetchone()
    return row["id"] if row else None
