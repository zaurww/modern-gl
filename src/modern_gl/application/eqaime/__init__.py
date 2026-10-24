"""E-qaimə of the tax portal (D45, D53): the import into purchase and sale drafts
(`parsing`, `planning`, `counterparties`, `drafts`), the portal's lists read for the
reconciliation (`portal`), and what the portal showed with the months reconciled —
`EqaimeModule`, one object over the ledger's connection (`ledger.eqaime`, `commands`).

The import (D45).

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

from modern_gl.application.eqaime.commands import EqaimeCommands
from modern_gl.application.eqaime.counterparties import (
    NewCounterparty,
    RenamedCounterparty,
    add_counterparties,
    apply_renames,
    new_counterparties,
    remember_legal_names,
    renamed_counterparties,
    short_name,
)
from modern_gl.application.eqaime.drafts import (
    import_drafts,
)
from modern_gl.application.eqaime.parsing import (
    PURCHASE,
    RETURN_KINDS,
    SALE,
    EInvoice,
    EInvoiceLine,
    parse_invoice,
)
from modern_gl.application.eqaime.planning import (
    AwaitingPurchase,
    InvoicePlan,
    LinePlan,
    plan_import,
)


class EqaimeModule(EqaimeCommands):
    """E-qaimə of the portal: what it showed, and what was reconciled (D52)."""


__all__ = [
    "PURCHASE",
    "RETURN_KINDS",
    "SALE",
    "AwaitingPurchase",
    "EInvoice",
    "EInvoiceLine",
    "EqaimeModule",
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
