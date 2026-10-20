"""Account classes and types, and the normal side of a balance."""

from __future__ import annotations

ACCOUNT_CLASSES = ("asset", "liability", "equity", "revenue", "expense")
DEBIT_NORMAL = {"asset", "expense"}  # liability, equity, revenue: credit-normal

# Account types: what an account means, whatever its code (D34). The list is fixed by the
# program so that reports and automatic postings understand any company's chart; the
# class follows from the type. (type, class, Russian name — a translation key).
ACCOUNT_TYPES = (
    ("cash", "asset", "Касса"),
    ("bank", "asset", "Банковские счета"),
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
