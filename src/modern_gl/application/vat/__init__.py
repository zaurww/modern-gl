"""ƏDV (VAT) of Azerbaijan — a module of the tax rules (docs/REPORTING.md, «Модуль ƏDV»):
the core keeps the facts (e-qaimə, customs declarations, payments by number), the module
says when and how much ƏDV is credited, by the version of the rule in force on the day."""

from modern_gl.application.vat.credit import CreditEvent, credit_events
from modern_gl.application.vat.facts import InvoiceFacts, Payment, purchase_facts
from modern_gl.application.vat.rules import RULES, CreditRule, rule_for

__all__ = [
    "RULES",
    "CreditEvent",
    "CreditRule",
    "InvoiceFacts",
    "Payment",
    "credit_events",
    "purchase_facts",
    "rule_for",
]
