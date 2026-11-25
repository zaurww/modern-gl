"""How a purchase is named where one is picked: its number, day, basis and supplier."""

from __future__ import annotations

from modern_gl.domain.dates import ru_date
from modern_gl.i18n import tr
from modern_gl.reporting.inventory import ReceiptDocumentChoice


def basis(invoice: str | None, invoice_kind: str | None) -> str:
    """«İdxal · YGB 0126…», «e-qaimə MT26…», as the warehouse says it."""
    if not invoice:
        return ""
    if invoice_kind == "customs":
        return tr("Импорт · ГТД {n}", n=invoice)
    return f"e-qaimə {invoice}"


def purchase_label(doc: ReceiptDocumentChoice) -> str:
    """In a list: what tells it from the others first — the declaration, the day, who."""
    parts = (
        basis(doc.invoice, doc.invoice_kind),
        ru_date(doc.doc_date),
        doc.party or "",
        f"№{doc.number}",
    )
    return " · ".join(part for part in parts if part)


def purchase_short(doc: ReceiptDocumentChoice) -> str:
    """In a narrow cell: the number of its declaration or e-qaimə, else its own and the day."""
    return doc.invoice or f"№{doc.number} · {ru_date(doc.doc_date)}"
