"""Counterparties named by the tax portal (e-qaimə, the ƏDV deposit account): the one the
company has with that VÖEN, and a shorter name for a new one."""

from __future__ import annotations

from modern_gl.i18n import fold
from modern_gl.infrastructure.db import Connection, Row


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


def plain_name(name: str) -> str:
    """A counterparty's name as it is compared: the legal form short, quotes, case, extra
    spaces and İ/ı apart — «"AUTOUNİVERSAL" MƏHDUD MƏSULİYYƏTLİ CƏMİYYƏTİ», «Autouniversal
    MMC» and «AUTOUNIVERSAL MMC» are one name."""
    return fold(short_name(name))


def _named(conn: Connection, company_id: int, name: str) -> list[Row]:
    wanted = plain_name(name)
    if not wanted:
        return []
    rows = conn.execute(
        "SELECT v.id, v.name, v.legal_name, v.tax_id, v.active FROM subconto_values v "
        "JOIN subconto_kinds k ON k.id = v.kind_id "
        "WHERE v.company_id = ? AND k.code = 'counterparty' AND v.is_group = 0 "
        "ORDER BY v.active DESC, v.id",
        (company_id,),
    )
    return [
        row
        for row in rows
        if wanted in (plain_name(row["name"]), plain_name(row["legal_name"] or ""))
    ]


def same_named(conn: Connection, company_id: int, name: str) -> list[int]:
    """The counterparties called so here or officially (`plain_name`), whatever their
    VÖEN: the shown ones first."""
    return [row["id"] for row in _named(conn, company_id, name)]


def entered_already(conn: Connection, company_id: int, name: str, tax_id: str = "") -> int | None:
    """The counterparty a person is about to enter a second time: a shown one of that
    name whose VÖEN is the same, or not known on either side. Two names with different
    VÖEN are two counterparties (a branch, a namesake)."""
    fits = [
        row
        for row in _named(conn, company_id, name)
        if row["active"] == 1 and (not tax_id or not row["tax_id"] or row["tax_id"] == tax_id)
    ]
    fits.sort(key=lambda row: row["tax_id"] != tax_id if tax_id else not row["tax_id"])
    return fits[0]["id"] if fits else None


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
