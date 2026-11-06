"""The other side of a bank statement's line: the file adds no counterparty — a sender
the directory lacks waits as a draft with the bank's VÖEN and name."""

from __future__ import annotations

AZ = {
    "контрагента нет в справочнике: {name}, VÖEN {tin}": (
        "kontragent soraqçada yoxdur: {name}, VÖEN {tin}"
    ),
    "контрагента нет в справочнике: {name}": "kontragent soraqçada yoxdur: {name}",
    "За {period} e-qaimə не загружены: контрагентов и неоплаченные программа берёт "
    "из них. Лучше сначала загрузить e-qaimə с портала, потом выписку.": (
        "{period} üçün e-qaimə yüklənməyib: proqram kontragentləri və ödənilməmişləri "
        "onlardan götürür. Əvvəlcə portaldan e-qaimə, sonra çıxarışı yükləmək daha yaxşıdır."
    ),
    "Оплачено без номера": "Nömrəsiz ödənilib",
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
