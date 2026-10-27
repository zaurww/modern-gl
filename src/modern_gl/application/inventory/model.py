"""Constants, the lines a caller gives and the documents it gets back."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from modern_gl.domain.accounts import (
    COST_OF_SALES,
    INCOMING_CONTRIBUTION,
    INCOMING_GIFT,
    INCOMING_PRODUCTION,
    INCOMING_SURPLUS,
    OUTPUT_VAT,
    SALES_REVENUE,
    SALES_VAT,
)
from modern_gl.i18n import N_

QUANTITY_SCALE = 6
QUANTITY_FACTOR = 10**QUANTITY_SCALE
ALLOCATION_METHODS = ("value", "quantity", "manual")
# VAT rates are in hundredths of a percent; a receipt starts with the standard rate.
VAT_RATE_SCALE = 10_000
STANDARD_VAT_RATE = 1800
VAT_DOCUMENTS = frozenset({"receipt", "sale"})  # the documents a line's VAT is on
# the account a receipt's accrual goes to when the chart has none (D65)
ACCRUED_CODE = "76H"
# the accounts a sale posts to (roles) as the settings name them
SALE_ROLE_NAMES = {
    SALES_REVENUE: "Выручка",
    COST_OF_SALES: "Себестоимость продаж",
    OUTPUT_VAT: N_("НДС к уплате"),
    SALES_VAT: N_("НДС начисляется со счёта"),
}


# «Mədaxil» (D91): why goods come in without a purchase, its name and the account role
INCOMING_REASONS = {
    "surplus": (N_("Излишки (инвентаризация)"), INCOMING_SURPLUS),
    "contribution": (N_("Вклад учредителя"), INCOMING_CONTRIBUTION),
    "production": (N_("Собственное производство"), INCOMING_PRODUCTION),
    "gift": (N_("Безвозмездное получение (подарок)"), INCOMING_GIFT),
}
# documents whose lines bring goods in at their amount: Dt stock / Kt the line's account
INCOMING_TYPES = {"opening", "receipt", "incoming"}
INCOMING_SQL = "(" + ", ".join(f"'{t}'" for t in sorted(INCOMING_TYPES)) + ")"  # for IN


@dataclass(frozen=True)
class ReceiptHeader:
    """What a receipt, an opening balance or a mədaxil (D91) says besides its lines: the
    account it is owed on, its kind and its terms — one value instead of a dozen
    arguments passed from method to method."""

    doc_date: date | str
    credit_account_id: int | None
    credit_subconto: Sequence[int | None] = ()
    memo: str = ""
    opening: bool = False
    incoming_reason: str | None = None  # a mədaxil without a purchase (D91)
    vat_rate: int | None = None  # remembered for a purchase only
    currency_id: int | None = None
    currency_rate: str | int | Decimal | None = None
    invoice: str = ""
    invoice_kind: str = ""
    awaits_invoice: bool = False  # the goods came before their e-qaimə (D119)

    @property
    def doc_type(self) -> str:
        return "incoming" if self.incoming_reason else "opening" if self.opening else "receipt"


@dataclass(frozen=True)
class ReceiptLine:
    """Receipt/opening line. In a draft, everything except the item may be left empty.

    A receipt's line without an item is a service, a fixed asset or any expense: no stock,
    its value goes to `expense_account_id` with `expense_subconto`; the memo says what it is."""

    item_id: int | None
    warehouse_id: int | None
    quantity: str | int | Decimal | None
    amount: str | int | Decimal | None
    memo: str = ""
    credit_account_id: int | None = None
    credit_subconto: Sequence[int | None] = ()
    line_id: int | None = None  # the stored line it edits; None = a new line
    vat_amount: str | int | Decimal | None = None  # a receipt's VAT; the amount is without it
    currency_amount: str | int | Decimal | None = None  # a receipt in a currency: the amount
    expense_account_id: int | None = None  # a line without an item: where its value goes
    expense_subconto: Sequence[int | None] = ()
    # a line without an item whose expense belongs to an earlier month (D65): any day of
    # that month; the receipt accrues it on the month's last day
    expense_date: date | str | None = None


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
class SaleLine:
    """A line of a sale: goods (an item taken from a warehouse at the average cost) or a
    service (no item, no warehouse; the memo says what it is). The amount is the revenue
    without VAT; the customer's account and subconto default to the document's.

    `sale_subconto`: values for the subconto of the sale's own accounts (revenue, cost of
    sales, the VAT charge) that the customer, the item and the warehouse do not give — a
    sales group, a channel (D61); each account takes them by kind."""

    item_id: int | None
    warehouse_id: int | None
    quantity: str | int | Decimal | None
    amount: str | int | Decimal | None
    vat_amount: str | int | Decimal | None = None
    memo: str = ""
    customer_account_id: int | None = None
    customer_subconto: Sequence[int | None] = ()
    line_id: int | None = None
    sale_subconto: Sequence[int | None] = ()


@dataclass(frozen=True)
class UsualUnit:
    """A unit offered before the company has it: made with the item that takes it."""

    code: str
    name: str
    precision: int = 3


# offered by the item dialog (in Russian, translated there): a first item needs no setup
USUAL_UNITS = (
    UsualUnit("шт", N_("Штука"), 0),
    UsualUnit(N_("кг"), N_("Килограмм")),
    UsualUnit(N_("л"), N_("Литр")),
    UsualUnit("м", N_("Метр")),
    UsualUnit(N_("м²"), N_("Квадратный метр")),
    UsualUnit("уп.", "Упаковка", 0),
)


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
    item_id: int | None  # None: a service line of a sale
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
    # a posted sale: where the cost of the goods went; a receipt's line without an item:
    # the account its value goes to, with these subconto; a sale's line: the values for its
    # sale accounts' subconto (SaleLine.sale_subconto)
    cost_account_id: int | None = None
    cost_subconto: tuple[int | None, int | None, int | None] = (None, None, None)
    # a receipt's line without an item accrued in an earlier month: its last day (D65)
    expense_date: str | None = None


@dataclass(frozen=True)
class AccrualData:
    """A receipt's accrual of one month (D65): the GL document dated its last day."""

    expense_date: str
    gl_document_id: int


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
    # a receipt with lines of earlier months (D65): an accrual per month, earliest first
    accruals: tuple[AccrualData, ...] = ()
    incoming_reason: str | None = None  # a mədaxil's reason: a key of INCOMING_REASONS
    awaits_invoice: bool = False  # a purchase whose e-qaimə comes later (D119)

    @property
    def editable(self) -> bool:
        """A draft, or a posted document edited in place in an open period."""
        return self.status != "posted" or not self.closed
