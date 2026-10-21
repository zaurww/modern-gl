"""What the tax portal showed of the e-qaimə, and the months reconciled with it (D53).
Not accounting: nothing here moves a posting; the reconciliation reads it."""

from __future__ import annotations

from collections.abc import Iterable

from modern_gl.application.common import now
from modern_gl.application.ledger.base import LedgerBase
from modern_gl.domain.eqaime import PortalInvoice
from modern_gl.domain.errors import ValidationError
from modern_gl.i18n import tr
from modern_gl.infrastructure.db import transaction

# what a change is looked at by: (column of eqaime_portal, field of PortalInvoice)
_WATCHED = (
    ("status", "status"),
    ("doc_date", "doc_date"),
    ("party_tin", "party_tin"),
    ("total", "total"),
    ("vat", "vat"),
)


class EqaimeCommands(LedgerBase):
    def remember_portal(
        self, company_id: int, invoices: Iterable[PortalInvoice], seen_at: str | None = None
    ) -> int:
        """Keep what the portal shows of each e-qaimə; a change of status, date, VÖEN or
        amounts is kept as was -> became. Returns how many e-qaimə changed."""
        seen_at = seen_at or now()
        changed = 0
        with transaction(self.conn):
            self._company(company_id)
            for invoice in invoices:
                old = self.conn.execute(
                    "SELECT * FROM eqaime_portal "
                    "WHERE company_id = ? AND outgoing = ? AND number = ?",
                    (company_id, int(invoice.outgoing), invoice.number),
                ).fetchone()
                values = (
                    invoice.portal_id,
                    invoice.source_system,
                    invoice.doc_date,
                    invoice.party_tin,
                    invoice.party_name,
                    invoice.status,
                    invoice.kind,
                    invoice.type,
                    invoice.total,
                    invoice.vat,
                    seen_at,
                )
                if old is None:
                    self.conn.execute(
                        "INSERT INTO eqaime_portal (company_id, outgoing, number, portal_id, "
                        "source_system, doc_date, party_tin, party_name, status, kind, type, "
                        "total, vat, last_seen, first_seen) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (company_id, int(invoice.outgoing), invoice.number, *values, seen_at),
                    )
                    continue
                if any(old[column] != getattr(invoice, name) for column, name in _WATCHED):
                    changed += 1
                    self.conn.execute(
                        "INSERT INTO eqaime_portal_changes (company_id, portal_id, seen_at, "
                        "old_status, new_status, old_date, new_date, old_tin, new_tin, "
                        "old_total, new_total, old_vat, new_vat) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            company_id,
                            old["id"],
                            seen_at,
                            old["status"],
                            invoice.status,
                            old["doc_date"],
                            invoice.doc_date,
                            old["party_tin"],
                            invoice.party_tin,
                            old["total"],
                            invoice.total,
                            old["vat"],
                            invoice.vat,
                        ),
                    )
                self.conn.execute(
                    "UPDATE eqaime_portal SET portal_id = ?, source_system = ?, doc_date = ?, "
                    "party_tin = ?, party_name = ?, status = ?, kind = ?, type = ?, total = ?, "
                    "vat = ?, last_seen = ? WHERE id = ?",
                    (*values, old["id"]),
                )
        return changed

    def mark_reconciled(
        self, company_id: int, outgoing: bool, month: str, at: str | None = None
    ) -> None:
        """The month (YYYY-MM) of purchases or sales agrees with the portal: changes seen
        after this moment are warned about."""
        if len(month) != 7 or month[4] != "-":
            raise ValidationError(tr("месяц должен быть в виде ГГГГ-ММ: {month}", month=month))
        with transaction(self.conn):
            self._company(company_id)
            self.conn.execute(
                "INSERT INTO eqaime_reconciled (company_id, outgoing, month, reconciled_at) "
                "VALUES (?, ?, ?, ?) ON CONFLICT (company_id, outgoing, month) "
                "DO UPDATE SET reconciled_at = excluded.reconciled_at",
                (company_id, int(outgoing), month, at or now()),
            )

    def unmark_reconciled(self, company_id: int, outgoing: bool, month: str) -> None:
        with transaction(self.conn):
            self.conn.execute(
                "DELETE FROM eqaime_reconciled WHERE company_id = ? AND outgoing = ? AND month = ?",
                (company_id, int(outgoing), month),
            )
