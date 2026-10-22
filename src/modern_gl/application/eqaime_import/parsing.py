"""An e-qaimə of the portal as the program reads it: its lines, kind and amounts."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from modern_gl.application.inventory import (
    STANDARD_VAT_RATE,
    vat_of,
)
from modern_gl.domain.eqaime import ON_APPROVAL, PortalInvoice, portal_invoice
from modern_gl.domain.invoice import normalize_invoice
from modern_gl.domain.money import to_minor

PURCHASE, SALE = "receipt", "sale"


# kinds that are not an ordinary sale: a return needs a return document (not made yet)
RETURN_KINDS = {"returnInvoice", "returnByAgent", "returnRecycled"}


@dataclass(frozen=True)
class EInvoiceLine:
    name: str
    code: str
    unit: str
    quantity: Decimal | None
    amount: int  # without VAT (cost + excise), minor units
    vat: int  # 18% of the line's VAT base, minor units

    @property
    def service(self) -> bool:
        """Works and services have codes «99…»; an empty or odd code: unknown, goods."""
        return self.code.isdigit() and self.code.startswith("99")


@dataclass(frozen=True)
class EInvoice:
    portal_id: str
    source_system: str
    number: str
    doc_date: str  # ISO
    outgoing: bool  # sent by the company: a sale
    status: str
    kind: str
    party_tin: str
    party_name: str
    lines: tuple[EInvoiceLine, ...]
    listed: PortalInvoice | None = None  # as the portal's list shows it: kept, reconciled

    @property
    def pending(self) -> bool:
        """Təsdiq gözləyir: not yet approved by the buyer (the list's status first: the
        list was asked for it)."""
        return (self.listed.status if self.listed else self.status) == ON_APPROVAL

    @property
    def doc_type(self) -> str:
        return SALE if self.outgoing else PURCHASE

    @property
    def amount(self) -> int:
        return sum(line.amount for line in self.lines)

    @property
    def vat(self) -> int:
        return sum(line.vat for line in self.lines)


def _decimal(value: Any) -> Decimal:
    try:
        return Decimal(str(value if value is not None else 0))
    except InvalidOperation:
        return Decimal(0)


def _minor(value: Any) -> int:
    return to_minor(_decimal(value).quantize(Decimal("0.01")))


def parse_invoice(row: Mapping[str, Any], detail: Mapping[str, Any], outgoing: bool) -> EInvoice:
    """An e-qaimə from its list row and its details, as etaxes-ext reads them
    (`buildDetailRows`): the party is the receiver of a sent one, the sender of a received
    one; the VAT is 18% of `vat18` (the API does not give it per line)."""

    def first(*keys: str) -> Any:
        for source in (detail, row):
            for key in keys:
                if source.get(key) not in (None, ""):
                    return source[key]
        return ""

    party_key = "receiver" if outgoing else "sender"
    party = detail.get(party_key) or row.get(party_key) or {}
    created = str(first("createdAt", "creationDate"))
    lines = []
    for item in detail.get("items") or []:
        base = _minor(item.get("vat18"))
        quantity = item.get("quantity")
        lines.append(
            EInvoiceLine(
                str(item.get("productName") or "").strip(),
                str((item.get("productGroup") or {}).get("code") or "").strip(),
                str(item.get("unit") or "").strip(),
                None if quantity in (None, "") else _decimal(quantity),
                _minor(item.get("cost"))
                + _minor(item.get("serviceCost"))
                + _minor(item.get("excise")),
                vat_of(base, STANDARD_VAT_RATE),
            )
        )
    if not lines:  # an e-qaimə without lines: its totals as one line
        lines.append(
            EInvoiceLine("", "", "", None, _minor(first("costWithoutVat")), _minor(first("vat")))
        )
    return EInvoice(
        str(first("id")),
        str(first("sourceSystem") or "avis"),
        normalize_invoice(str(first("serialNumber", "invoiceNumber"))) or "",
        created[:10],
        outgoing,
        str(first("status")),
        str(first("kind")),
        str(party.get("tin") or row.get(f"{party_key}Tin") or "").strip(),
        str(party.get("name") or row.get(f"{party_key}Name") or "").strip(),
        tuple(lines),
        portal_invoice(row, outgoing),
    )
