"""ƏDV (VAT) of Azerbaijan — a module of the tax rules (docs/REPORTING.md, «Модуль ƏDV»):
the core keeps the facts (e-qaimə, customs declarations, payments by number), the module
says when and how much ƏDV is credited (purchases) and owed (sales), by the version of the
rule in force on the day."""

from modern_gl.application.vat.credit import CreditEvent, credit_events
from modern_gl.application.vat.facts import InvoiceFacts, Payment, purchase_facts
from modern_gl.application.vat.liability import LiabilityEvent, liability_events
from modern_gl.application.vat.rules import (
    LIABILITY_RULES,
    RULES,
    CreditRule,
    LiabilityRule,
    liability_rule_for,
    rule_for,
)
from modern_gl.application.vat.sales import SaleFacts, sale_facts

__all__ = [
    "LIABILITY_RULES",
    "RULES",
    "CreditEvent",
    "CreditRule",
    "InvoiceFacts",
    "LiabilityEvent",
    "LiabilityRule",
    "Payment",
    "SaleFacts",
    "credit_events",
    "liability_events",
    "liability_rule_for",
    "purchase_facts",
    "rule_for",
    "sale_facts",
]
