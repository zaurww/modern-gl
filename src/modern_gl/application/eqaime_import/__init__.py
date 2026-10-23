"""Import of e-qaimə from the tax portal into purchase and sale drafts (D45).

A received e-qaimə becomes a purchase, a sent one a sale; only drafts are made: the user
checks every one by eye and posts it (suppliers write names and codes wrongly).

A line is goods or a service by its code, as etaxes-ext decides: codes «99…» are works
and services (CPA), others goods (ƏMTN). What a line becomes is guessed, in this order:
the same name from the same counterparty last time (its item, or its account and
subconto), an item of the same name, else nothing — a purchase line without an item and
without an account does not post until the user chooses.

A purchase posted before its e-qaimə came (D119) is offered the e-qaimə of its supplier:
the e-qaimə is written into it (with its VAT when the amounts agree), not made anew."""

from __future__ import annotations

from modern_gl.application.eqaime_import.counterparties import (
    NewCounterparty,
    RenamedCounterparty,
    add_counterparties,
    apply_renames,
    new_counterparties,
    remember_legal_names,
    renamed_counterparties,
    short_name,
)
from modern_gl.application.eqaime_import.drafts import (
    import_drafts,
)
from modern_gl.application.eqaime_import.parsing import (
    PURCHASE,
    RETURN_KINDS,
    SALE,
    EInvoice,
    EInvoiceLine,
    parse_invoice,
)
from modern_gl.application.eqaime_import.planning import (
    AwaitingPurchase,
    InvoicePlan,
    LinePlan,
    plan_import,
)

__all__ = [
    "PURCHASE",
    "RETURN_KINDS",
    "SALE",
    "AwaitingPurchase",
    "EInvoice",
    "EInvoiceLine",
    "InvoicePlan",
    "LinePlan",
    "NewCounterparty",
    "RenamedCounterparty",
    "add_counterparties",
    "apply_renames",
    "import_drafts",
    "new_counterparties",
    "parse_invoice",
    "plan_import",
    "remember_legal_names",
    "renamed_counterparties",
    "short_name",
]
