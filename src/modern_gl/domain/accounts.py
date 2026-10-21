"""Account classes and types, and the normal side of a balance."""

from __future__ import annotations

ACCOUNT_CLASSES = ("asset", "liability", "equity", "revenue", "expense")
DEBIT_NORMAL = {"asset", "expense"}  # liability, equity, revenue: credit-normal
# Accounts that automatic postings use, chosen per company (table account_roles)
INPUT_VAT = "input_vat"  # ƏDV к возмещению: a warehouse receipt debits it
OPENING_BALANCE = "opening_balance"  # technical counter-account for opening balances
# Currency conversion (D37): money in transit (57), the exchange difference, the bank fee
FX_TRANSIT = "fx_transit"
FX_GAIN = "fx_gain"
FX_LOSS = "fx_loss"
BANK_FEE = "bank_fee"
# A sale: the revenue, the cost of the goods sold, the VAT to pay, and the account the VAT
# is charged from (none: straight from the customer's account)
SALES_REVENUE = "sales_revenue"
COST_OF_SALES = "cost_of_sales"
OUTPUT_VAT = "output_vat"
SALES_VAT = "sales_vat"
# A purchase whose expense belongs to an earlier month (D65): the accrual is credited here
ACCRUED_EXPENSES = "accrued_expenses"
ACCOUNT_ROLES = (
    INPUT_VAT,
    OPENING_BALANCE,
    FX_TRANSIT,
    FX_GAIN,
    FX_LOSS,
    BANK_FEE,
    SALES_REVENUE,
    COST_OF_SALES,
    OUTPUT_VAT,
    SALES_VAT,
    ACCRUED_EXPENSES,
)
# Without an account chosen for a role, the only account of this type plays it (D35).
ROLE_TYPES = {
    INPUT_VAT: "input_vat",
    FX_TRANSIT: "transit",
    FX_GAIN: "other_income",
    FX_LOSS: "other_expense",
    BANK_FEE: "other_expense",
    SALES_REVENUE: "sales",
    COST_OF_SALES: "cost_of_sales",
    ACCRUED_EXPENSES: "accrued_expenses",
}

# Account types: what an account means, whatever its code (D35). The list is fixed by the
# program so that reports and automatic postings understand any company's chart; the
# class follows from the type. (type, class, Russian name — a translation key).
ACCOUNT_TYPES = (
    ("cash", "asset", "Касса"),
    ("bank", "asset", "Банковские счета"),
    ("transit", "asset", "Переводы в пути"),
    # ƏDV depozit hesabı: money that may only pay ƏDV, so not free cash like "bank" (D41)
    ("vat_deposit", "asset", "Депозитный счёт НДС"),
    ("receivable", "asset", "Покупатели и заказчики"),
    ("advance_paid", "asset", "Авансы выданные"),
    ("other_receivable", "asset", "Прочая дебиторская задолженность"),
    ("input_vat", "asset", "НДС к возмещению"),
    ("inventory", "asset", "Запасы"),
    ("fixed_asset", "asset", "Основные средства"),
    ("intangible", "asset", "Нематериальные активы"),
    ("investment", "asset", "Финансовые вложения"),
    ("other_asset", "asset", "Прочие активы"),
    ("payable", "liability", "Поставщики и подрядчики"),
    ("advance_received", "liability", "Авансы полученные"),
    # not a settlement by e-qaimə: Dt 76H / Kt 60 is no payment of the invoice (D65)
    ("accrued_expenses", "liability", "Начисленные расходы"),
    ("tax_payable", "liability", "Налоги и обязательные платежи"),
    ("payroll", "liability", "Оплата труда"),
    ("short_term_loan", "liability", "Краткосрочные кредиты"),
    ("long_term_loan", "liability", "Долгосрочные кредиты"),
    ("other_liability", "liability", "Прочие обязательства"),
    ("share_capital", "equity", "Уставный капитал"),
    ("retained_earnings", "equity", "Нераспределённая прибыль"),
    ("profit_loss", "equity", "Финансовый результат"),
    ("other_equity", "equity", "Прочий капитал"),
    ("sales", "revenue", "Выручка"),
    ("other_income", "revenue", "Прочие доходы"),
    ("cost_of_sales", "expense", "Себестоимость продаж"),
    ("operating_expense", "expense", "Операционные расходы"),
    ("other_expense", "expense", "Прочие расходы"),
    ("income_tax", "expense", "Налог на прибыль"),
)
# Lines on these accounts may name the e-qaimə they belong to: settlements with partners
# (an account without a type counts if it has the counterparty directory) and ƏDV (a
# sale's ƏDV line 46 / 68.2 has no partner account; 19 has one, but it is ƏDV).
SETTLEMENT_TYPES = frozenset(
    {
        "receivable",
        "payable",
        "advance_paid",
        "advance_received",
        "other_receivable",
        "other_liability",
    }
)
VAT_TYPES = frozenset({"input_vat", "tax_payable"})
TYPE_CLASS = {t: cls for t, cls, _ in ACCOUNT_TYPES}
TYPE_NAMES = {t: name for t, _, name in ACCOUNT_TYPES}


def normal_side(account_class: str | None, contra: bool = False) -> str | None:
    """'debit' or 'credit'; a contra account sits on the opposite side. None if unknown."""
    if account_class is None:
        return None
    debit = account_class in DEBIT_NORMAL
    return "debit" if debit != contra else "credit"


def wrong_side(account_class: str | None, contra: bool, two_sided: bool, net: int) -> bool:
    """True if a net balance (Dt - Ct) sits on the side the account should not have.

    Two-sided accounts (settlements with counterparties, taxes…) are never flagged.
    """
    if two_sided or net == 0:
        return False
    side = normal_side(account_class, contra)
    if side is None:
        return False
    return (net > 0) != (side == "debit")
