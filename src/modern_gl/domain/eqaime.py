"""E-qaimə as the tax portal lists them (D53): statuses and a row of `find.inbox` /
`find.outbox` without its lines — enough to reconcile the books with the portal."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from modern_gl.domain.invoice import normalize_invoice
from modern_gl.domain.money import portal_minor
from modern_gl.i18n import N_, tr

# statuses that count in turnover (etaxes-ext DOVRIYYE_STATUSES); the API takes one at a time
TURNOVER = ("approved", "approvedBySystem", "cancelationRefused", "correctionRefused")
ON_APPROVAL = "onApproval"  # Təsdiq gözləyir: the buyer has five days, then the system approves
IN_PROGRESS = ("updateApproval", "updateRequested", "cancelRequested", "onApprovalEdited")
VOID = ("canceled", "deleted", "deletedBySystem", "deactivated", "rejected")
IMPORTED = (*TURNOVER, ON_APPROVAL)  # what the import makes drafts of
# what the reconciliation asks the portal for: "draft" is only the sender's; "rejected" is
# shown in a row, but the portal's filter does not take it (400 «Sorğu məlumatları
# yanlışdır», live 2026-10-21; etaxes-ext never asks for it either)
ALL = (*IMPORTED, *IN_PROGRESS, *(s for s in VOID if s != "rejected"))

# the portal's own names (Azerbaijani); the Russian ones are for the Russian interface
_LABELS = {
    "approved": N_("Подтверждена"),
    "approvedBySystem": N_("Подтверждена системой"),
    "cancelationRefused": N_("Отказ в аннулировании"),
    "correctionRefused": N_("Отказ в исправлении"),
    ON_APPROVAL: N_("Ожидает подтверждения"),
    "updateApproval": N_("Исправлена"),
    "updateRequested": N_("Возвращена на исправление"),
    "cancelRequested": N_("Отправлена на аннулирование"),
    "onApprovalEdited": N_("Отправлена на исправление"),
    "canceled": N_("Аннулирована"),
    "deleted": N_("Удалена"),
    "deletedBySystem": N_("Удалена системой"),
    "deactivated": N_("Деактивирована"),
    "rejected": N_("Отклонена"),
}


def status_label(status: str) -> str:
    """The portal status of an e-qaimə in the interface language; an unknown one as is."""
    return tr(_LABELS[status]) if status in _LABELS else status


def status_group(status: str) -> str:
    """'turnover', 'pending' (on approval), 'progress', 'void' or '' (unknown)."""
    if status in TURNOVER:
        return "turnover"
    if status == ON_APPROVAL:
        return "pending"
    if status in IN_PROGRESS:
        return "progress"
    return "void" if status in VOID else ""


@dataclass(frozen=True)
class PortalInvoice:
    """One e-qaimə of the portal's list: its number, party and totals."""

    number: str
    outgoing: bool  # sent by the company: a sale
    doc_date: str  # ISO
    status: str
    party_tin: str = ""
    party_name: str = ""
    total: int = 0  # with ƏDV, minor units
    vat: int = 0
    portal_id: str = ""
    source_system: str = ""
    kind: str = ""
    type: str = ""

    @property
    def amount(self) -> int:
        """Without ƏDV."""
        return self.total - self.vat


def portal_invoice(row: Mapping[str, Any], outgoing: bool) -> PortalInvoice | None:
    """A list row as the portal sends it; None for a row without a number. The total is
    `amount` (with ƏDV); a row without it: `costWithoutVat` + `vat`."""
    number = normalize_invoice(str(row.get("serialNumber") or row.get("invoiceNumber") or ""))
    if not number:
        return None
    party_key = "receiver" if outgoing else "sender"
    party: Mapping[str, Any] = row.get(party_key) or {}
    vat = portal_minor(row.get("vat"))
    total = row.get("amount")
    return PortalInvoice(
        number,
        outgoing,
        str(row.get("createdAt") or row.get("creationDate") or "")[:10],
        str(row.get("status") or ""),
        str(party.get("tin") or row.get(f"{party_key}Tin") or "").strip(),
        str(party.get("name") or row.get(f"{party_key}Name") or "").strip(),
        portal_minor(total)
        if total not in (None, "")
        else portal_minor(row.get("costWithoutVat")) + vat,
        vat,
        str(row.get("id") or ""),
        str(row.get("sourceSystem") or ""),
        str(row.get("kind") or ""),
        str(row.get("type") or row.get("invoiceType") or ""),
    )
