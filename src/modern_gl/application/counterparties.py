"""Counterparties named by the tax portal (e-qaimə, the ƏDV deposit account): the one the
company has with that VÖEN, and a shorter name for a new one."""

from __future__ import annotations

from modern_gl.i18n import fold
from modern_gl.infrastructure.db import Connection


def known_counterparty(
    conn: Connection, company_id: int, tax_id: str, name: str = ""
) -> int | None:
    """The company's counterparty with this VÖEN; one without a VÖEN (a non-resident,
    a person) by exactly the same name."""
    if tax_id:
        row = conn.execute(
            "SELECT v.id FROM subconto_values v JOIN subconto_kinds k ON k.id = v.kind_id "
            "WHERE v.company_id = ? AND k.code = 'counterparty' AND v.tax_id = ? "
            "ORDER BY v.active DESC, v.id LIMIT 1",
            (company_id, tax_id),
        ).fetchone()
        return row["id"] if row else None
    if not name.strip():
        return None
    wanted = fold(" ".join(name.split()))
    for row in conn.execute(
        "SELECT v.id, v.name FROM subconto_values v JOIN subconto_kinds k ON k.id = v.kind_id "
        "WHERE v.company_id = ? AND k.code = 'counterparty' AND v.tax_id IS NULL "
        "AND v.is_group = 0 ORDER BY v.active DESC, v.id",
        (company_id,),
    ):
        if fold(" ".join(row["name"].split())) == wanted:
            return row["id"]
    return None


# legal forms written out in full on the portal and their usual short forms
_LEGAL_FORMS = (
    ("MƏHDUD MƏSULİYYƏTLİ CƏMİYYƏTİ", "MMC"),
    ("AÇIQ SƏHMDAR CƏMİYYƏTİ", "ASC"),
    ("QAPALI SƏHMDAR CƏMİYYƏTİ", "QSC"),
    ("SƏHMDAR CƏMİYYƏTİ", "SC"),
    ("PUBLİK HÜQUQİ ŞƏXS", "PHŞ"),
    ("FƏRDİ SAHİBKAR", "FS"),
)


def short_name(name: str) -> str:
    """A suggestion for the program's name: the legal form shortened and put last, quotes
    and extra spaces dropped ('"ALFA TREYD" MƏHDUD MƏSULİYYƏTLİ CƏMİYYƏTİ' -> 'ALFA TREYD
    MMC'). The user corrects it as they like."""
    text = " ".join(name.split())
    form = ""
    for full, short in _LEGAL_FORMS:
        position = fold(text).find(fold(full))
        if position >= 0:
            text = (text[:position] + text[position + len(full) :]).strip(" ,")
            form = short
            break
    for quote in "\"“”„«»'":
        text = text.replace(quote, "")
    text = " ".join(text.split())
    return f"{text} {form}".strip() if text else name.strip()
