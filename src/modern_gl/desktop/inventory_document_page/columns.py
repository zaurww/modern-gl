"""The columns of a warehouse document's lines, their headers and pasting from Excel."""

from __future__ import annotations

from dataclasses import dataclass, field

from modern_gl.application.inventory import (
    STANDARD_VAT_RATE,
)
from modern_gl.application.inventory import VAT_DOCUMENTS as INVENTORY_VAT_DOCUMENTS
from modern_gl.application.table_text import header_names, subconto_header
from modern_gl.i18n import N_, fold

ITEM = "item"
WAREHOUSE = "warehouse"
TO_WAREHOUSE = "to_warehouse"
QUANTITY = "quantity"
UNIT = "unit"
PRICE = "price"
AMOUNT = "amount"
CURRENCY_AMOUNT = "currency_amount"
VAT = "vat"
ACCOUNT = "account"
SC1 = "sc1"
SC2 = "sc2"
SC3 = "sc3"
# a receipt's line without an item (a service, a fixed asset): the account it goes to
EXPENSE = "expense"
ESC1 = "esc1"
ESC2 = "esc2"
ESC3 = "esc3"
# a receipt's (sale's) line without an item: the earlier month its expense (income)
# belongs to (D65)
EXPENSE_MONTH = "expense_month"
SEVERAL_MONTHS = -1  # the choice that splits the line over a range of months
# a sale line: the subconto of the sale's own accounts (46; 90.1 / 90.2 / 90.3) that
# the customer, the item and the warehouse do not give — a sales group, a channel (D61)
SALE1 = "sale1"
SALE2 = "sale2"
SALE3 = "sale3"
MEMO = "memo"
# a receipt's line is goods (through a warehouse) or a service (to an account): the choice
KIND = "kind"
GOODS, SERVICE = 1, 0
# named by where the line goes, not by what it is: a fixed asset may go to a warehouse (07)
KIND_NAMES = {GOODS: N_("Склад"), SERVICE: N_("Счёт")}
SC_KEYS = {SC1, SC2, SC3}  # the subconto of the line's offset (supplier, customer) account
ESC_KEYS = {ESC1, ESC2, ESC3}
SALE_KEYS = {SALE1, SALE2, SALE3}
SUBCONTO_KEYS = SC_KEYS | ESC_KEYS | SALE_KEYS
# cells that store the edited value as is
STORED_FIELDS = {
    ITEM: "item_id",
    WAREHOUSE: "warehouse_id",
    TO_WAREHOUSE: "to_warehouse_id",
    QUANTITY: "quantity",
    AMOUNT: "amount",
    MEMO: "memo",
}
LIST_KEYS = {ITEM, KIND, WAREHOUSE, TO_WAREHOUSE, ACCOUNT, EXPENSE, EXPENSE_MONTH} | SUBCONTO_KEYS
# the name of a line keeps this much; these columns narrow first, down to NARROW_MIN
ITEM_MIN = 300
NARROW_MIN = 84
SOFT_KEYS = {WAREHOUSE, TO_WAREHOUSE, ACCOUNT, EXPENSE, EXPENSE_MONTH} | SUBCONTO_KEYS
NUMBER_KEYS = {QUANTITY, PRICE, AMOUNT, CURRENCY_AMOUNT, VAT}
# the VAT of a receipt or a sale: rate in hundredths of a percent, None = without VAT
VAT_RATES = [(STANDARD_VAT_RATE, "18%"), (None, N_("Без НДС"))]
VAT_DOCUMENTS = INVENTORY_VAT_DOCUMENTS  # kept here for the pages

HEADERS = {
    ITEM: N_("Товар"),
    KIND: N_("Куда"),
    WAREHOUSE: N_("Склад"),
    TO_WAREHOUSE: N_("Склад-получатель"),
    QUANTITY: N_("Количество"),
    UNIT: N_("Ед."),
    PRICE: N_("Цена"),
    AMOUNT: N_("Сумма"),
    CURRENCY_AMOUNT: N_("В валюте"),
    VAT: N_("НДС"),
    ACCOUNT: N_("Корр. счёт"),  # the header stays short; its tooltip says more
    SC1: N_("Субконто"),
    SC2: "",
    SC3: "",
    EXPENSE: N_("Счёт"),  # a service, a fixed asset or an expense: not only costs
    ESC1: N_("Субконто"),
    ESC2: "",
    ESC3: "",
    EXPENSE_MONTH: N_("Расход за"),
    SALE1: "",  # the name of the directory
    SALE2: "",
    SALE3: "",
    MEMO: N_("Комментарий"),
}
# a sale line is goods or a service: a line without an item, its memo says what it is
SALE_HEADERS = {
    ITEM: N_("Товар / услуга"),
    MEMO: N_("Содержание"),
    EXPENSE_MONTH: N_("Доход за"),  # a service of an earlier month (D65 for sales)
}
# a receipt line without an item: a service, a fixed asset or any expense bought
RECEIPT_HEADERS = {ITEM: N_("Товар / услуга / ОС"), MEMO: N_("Содержание")}
# the first subconto of the offset account, when the account itself is not shown (D90)
PARTY_HEADERS = {
    "receipt": "Поставщик",
    "sale": "Покупатель",
    "purchase_return": "Поставщик",
    "sale_return": "Покупатель",
}

HINT = (  # the keys of the page (desktop/shortcuts.py), under its table
    "next_field",
    "previous_field",
    "insert",
    "duplicate_row",
    "split_row",
    "delete",
    "paste_rows",
    "save",
    "post",
    "post_and_new",
)


# Excel header -> column; "Субконто" columns go in a row after the account
PASTE_HEADERS = [
    (header_names(N_("Товар"), N_("Наименование"), "Номенклатура", "Mal", "Malın adı", "Ad"), ITEM),
    (header_names(N_("Склад"), "Anbar"), WAREHOUSE),
    (header_names(N_("Склад-получатель")), TO_WAREHOUSE),
    (header_names(N_("Количество"), N_("Кол-во"), "Miqdar"), QUANTITY),
    (
        header_names(N_("Ед."), "Ед", "Единица", N_("Единица измерения"), "Vahid", "Ölçü vahidi"),
        UNIT,
    ),
    (header_names(N_("Цена"), "Qiymət"), PRICE),
    (header_names(N_("Сумма"), "Məbləğ", "Сумма без НДС", "ƏDV-siz məbləğ"), AMOUNT),
    (header_names(N_("НДС"), "Сумма НДС", N_("ƏDV"), "ƏDV məbləği"), VAT),
    (header_names(N_("Корр. счёт"), N_("Счёт"), "Hesab"), ACCOUNT),
    (header_names(N_("Расход за"), "Месяц расхода", "Xərc dövrü", "Xərc ayı"), EXPENSE_MONTH),
    (header_names(N_("Доход за"), "Месяц дохода", "Gəlir dövrü", "Gəlir ayı"), EXPENSE_MONTH),
    (header_names(N_("Комментарий"), N_("Содержание"), "Şərh", "Məzmun"), MEMO),
]
# accounts before their subconto, the quantity before a price, a pasted amount over a price
PASTE_ORDER = [
    ITEM,
    WAREHOUSE,
    TO_WAREHOUSE,
    QUANTITY,
    ACCOUNT,
    SC1,
    SC2,
    SC3,
    PRICE,
    CURRENCY_AMOUNT,
    AMOUNT,
    VAT,
    EXPENSE,
    ESC1,
    ESC2,
    ESC3,
    EXPENSE_MONTH,
]


class UnknownNameError(LookupError):
    """A pasted name that is not in its list yet: an item, a warehouse or a subconto."""

    def __init__(self, key: str, text: str, kind_id: int | None = None) -> None:
        super().__init__(text)
        self.key, self.text, self.kind_id = key, text, kind_id


@dataclass
class InventoryPaste:
    rows: int = 0
    errors: list[str] = field(default_factory=list)
    # row, column key, name, subconto kind (None for an item or a warehouse)
    unknown: list[tuple[int, str, str, int | None]] = field(default_factory=list)
    units: dict[str, str] = field(default_factory=dict)  # a new item -> its pasted unit


def header_key(cell: str) -> str | None:
    """The column an Excel title stands for, if it is one."""
    name = " ".join(fold(cell.strip()).split())
    return next((key for names, key in PASTE_HEADERS if name in names), None)


def paste_columns(cells: list[str], columns: list[str]) -> list[str | None] | None:
    """The columns of a header line, or None if the line is not a header."""
    result: list[str | None] = []
    position = 0
    for cell in cells:
        name = " ".join(fold(cell.strip()).split())
        key = header_key(cell)
        if key is None and (sub := subconto_header(name, position)) is not None:
            _side, position = sub  # a warehouse line has one side of subconto
            key = f"sc{position}" if 1 <= position <= 3 else None
        result.append(key if key in columns else None)
    return result if sum(k is not None for k in result) >= 2 else None


@dataclass
class InventoryGridRow:
    item_id: int | None = None
    warehouse_id: int | None = None
    to_warehouse_id: int | None = None
    quantity: int | None = None
    amount: int | None = None
    offset_account_id: int | None = None
    offset_subconto: list[int | None] = field(default_factory=lambda: [None, None, None])
    memo: str = ""
    line_id: int | None = None  # the stored line; landed cost refers to it
    vat_amount: int | None = None
    vat_typed: bool = False  # typed by hand: a new amount or rate no longer recalculates it
    currency_amount: int | None = None  # a receipt in a currency
    # a receipt's line without an item: the account and subconto its value goes to
    expense_account_id: int | None = None
    expense_subconto: list[int | None] = field(default_factory=lambda: [None, None, None])
    # a sale's line: a value for each of the model's `sale_kinds`
    sale_subconto: list[int | None] = field(default_factory=lambda: [None, None, None])
    # a receipt's service of an earlier month (D65): the last day of that month
    expense_date: str | None = None
    returned_line_id: int | None = None  # a return's line: the purchase's (sale's) it returns

    def is_empty(self) -> bool:
        """Nothing typed yet: the account and subconto prefilled by default do not count."""
        return (
            self.item_id is None
            and self.warehouse_id is None
            and self.to_warehouse_id is None
            and self.quantity is None
            and self.amount is None
            and not self.memo.strip()
        )

    def copy(self) -> InventoryGridRow:
        return InventoryGridRow(
            self.item_id,
            self.warehouse_id,
            self.to_warehouse_id,
            self.quantity,
            self.amount,
            self.offset_account_id,
            list(self.offset_subconto),
            self.memo,
            vat_amount=self.vat_amount,
            vat_typed=self.vat_typed,
            currency_amount=self.currency_amount,
            expense_account_id=self.expense_account_id,
            expense_subconto=list(self.expense_subconto),
            sale_subconto=list(self.sale_subconto),
            expense_date=self.expense_date,
        )  # a copy is a new line: no line id
