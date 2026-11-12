"""The basis «Digər» of a purchase or a sale (D217)."""

from __future__ import annotations

AZ = {
    "Digər": "Digər",
    "акт №5": "akt №5",
    "Основание: e-qaimə или таможенная декларация (импорт). «Ждёт e-qaimə» — "
    "товар пришёл раньше документов: номер и ƏDV допишет загрузка с портала. "
    "«Digər» — акт, чек, договор: впишите какой; без ƏDV к зачёту": (
        "Əsas: e-qaimə və ya gömrük bəyannaməsi (idxal). «E-qaimə gözləyir» — mal "
        "sənədlərdən əvvəl gəlib: nömrəni və ƏDV-ni portaldan yükləmə əlavə edəcək. "
        "«Digər» — akt, qəbz, müqavilə: hansı olduğunu yazın; ƏDV əvəzləşdirilmir"
    ),
    "Основание: e-qaimə или «Digər» — акт, чек, договор: впишите какой": (
        "Əsas: e-qaimə və ya «Digər» — akt, qəbz, müqavilə: hansı olduğunu yazın"
    ),
    "основание длиннее {n} знаков: {text}": "əsas {n} simvoldan uzundur: {text}",
    "у документа одно основание: e-qaimə или «Digər»": (
        "sənədin bir əsası olur: e-qaimə və ya «Digər»"
    ),
    "покупка по «Digər» — без ƏDV: зачесть его можно только по e-qaimə": (
        "«Digər» üzrə alış ƏDV-siz olur: ƏDV yalnız e-qaimə ilə əvəzləşdirilir"
    ),
}
