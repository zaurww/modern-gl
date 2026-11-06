"""The other side of a bank statement's line: the file adds no counterparty — a sender
the directory lacks waits as a draft with the bank's VÖEN and name."""

from __future__ import annotations

AZ = {
    "контрагента нет в справочнике: {name}, VÖEN {tin}": (
        "kontragent soraqçada yoxdur: {name}, VÖEN {tin}"
    ),
    "контрагента нет в справочнике: {name}": "kontragent soraqçada yoxdur: {name}",
    "контрагент в выписке не назван": "çıxarışda kontragent göstərilməyib",
    ", контрагентов нет в справочнике: {n}": ", soraqçada olmayan kontragentlər: {n}",
    "{name}, VÖEN {tin}": "{name}, VÖEN {tin}",
    "В выписке: {who} — в справочнике нет": "Çıxarışda: {who} — soraqçada yoxdur",
    "В выписке: {who} — в справочнике это «{name}»": (
        "Çıxarışda: {who} — soraqçada bu «{name}»dir"
    ),
    "Добавить в справочник…": "Soraqçaya əlavə et…",
    "Подставить": "Seç",
    "Банк: черновики получили контрагента — {n}": "Bank: qaralamalara kontragent təyin edildi — {n}",
}
