"""An operation loaded into a bank account from outside — the tax portal's ƏDV deposit
(D112), a bank's statement file — and what the import does with it: posts it, leaves it
a draft (and why), links an operation entered by hand, or finds it in the books already."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

POSTED, DRAFT, LINKED, KNOWN = "posted", "draft", "linked", "known"


class ImportedOperation(Protocol):
    """What the window shows of an operation from outside, in minor units."""

    @property
    def day(self) -> str: ...  # ISO date

    @property
    def direction(self) -> str: ...  # IN or OUT

    @property
    def amount(self) -> int: ...  # > 0

    @property
    def tin(self) -> str: ...  # the other side's VÖEN

    @property
    def name(self) -> str: ...  # its name

    @property
    def kind(self) -> str: ...  # SUPPLIER, CUSTOMER, TAX…

    @property
    def memo(self) -> str: ...

    @property
    def invoices(self) -> tuple[tuple[str, int | None], ...]: ...  # (e-qaimə, its ƏDV)

    @property
    def reference(self) -> str: ...  # what the books know it by

    @property
    def net(self) -> int: ...  # signed: money in > 0


@dataclass(frozen=True)
class ImportRow:
    """What the import does (did) with one operation: POSTED, DRAFT (and why), LINKED —
    entered by hand, gets the reference; KNOWN — in the books already."""

    op: ImportedOperation
    state: str
    lines: tuple[tuple[str, str, int], ...] = ()  # (account's code, e-qaimə, amount)
    reason: str = ""
    document_id: int | None = None  # its GL document; None in a preview
