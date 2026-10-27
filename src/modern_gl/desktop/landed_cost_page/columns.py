"""The columns of the two tables (expenses and receipt lines) and their rows."""

from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction

from modern_gl.domain.currency import to_base
from modern_gl.i18n import N_
from modern_gl.reporting.inventory import (
    ReceiptLineChoice,
)

COST_TYPE = "cost_type"
ACCOUNT = "account"
SC1, SC2, SC3 = "sc1", "sc2", "sc3"
AMOUNT = "amount"
CURRENCY_AMOUNT = "currency_amount"
RATE = "rate"
VAT = "vat"
MEMO = "memo"
CHARGE_HEADERS = {
    COST_TYPE: "Статья",
    ACCOUNT: "Счёт",
    SC1: "Субконто",
    SC2: "",
    SC3: "",
    CURRENCY_AMOUNT: "В валюте",
    RATE: "Курс",
    AMOUNT: "Сумма",
    VAT: "НДС",
    MEMO: "Комментарий",
}

DOCUMENT = "document"
ITEM = "item"
WAREHOUSE = "warehouse"
QUANTITY = "quantity"
COST = "cost"
SHARE = "share"
UNIT_COST = "unit_cost"
TARGET_HEADERS = {
    DOCUMENT: "Поступление",
    ITEM: "Товар",
    WAREHOUSE: "Склад",
    QUANTITY: "Количество",
    COST: "Стоимость",
    SHARE: "Расходы",
    UNIT_COST: "Цена с расходами",
}
NUMBER_KEYS = {AMOUNT, CURRENCY_AMOUNT, RATE, VAT, QUANTITY, COST, SHARE, UNIT_COST}

METHODS = [
    ("value", N_("По стоимости")),
    ("quantity", N_("По количеству")),
    ("manual", N_("Вручную")),
]

HINT = ("next_field", "previous_field", "add_charge", "delete")  # the keys (desktop/shortcuts.py)…
HINT_TYPED = (N_("Сумма «30 USD» — в валюте"), N_("НДС «18%» — посчитать"))  # …and what is typed


@dataclass
class ChargeRow:
    cost_type_id: int | None = None
    account_id: int | None = None
    subconto: list[int | None] = field(default_factory=lambda: [None, None, None])
    amount: int | None = None
    vat_amount: int | None = None
    source: tuple[int, int] | None = None  # a GL posting: (document id, line number)
    source_label: str = ""
    memo: str = ""
    # an expense in a currency: the manat amount is the currency amount at the rate
    currency_id: int | None = None
    currency_code: str = ""
    currency_amount: int | None = None
    rate: Fraction | None = None
    rate_typed: bool = False  # a new date of the document no longer changes it

    def recalculate(self) -> None:
        if self.currency_id is not None:
            ok = self.currency_amount is not None and self.rate is not None
            self.amount = (
                to_base(self.currency_amount or 0, self.rate or Fraction(0)) if ok else None
            )

    def is_empty(self) -> bool:
        return (
            self.cost_type_id is None
            and self.amount is None
            and self.currency_amount is None
            and self.source is None
            and not self.memo.strip()
        )


@dataclass
class TargetRow:
    receipt: ReceiptLineChoice
    manual: int | None = None
    line_id: int | None = None
    share: int | None = None  # calculated (or the manual amount)
