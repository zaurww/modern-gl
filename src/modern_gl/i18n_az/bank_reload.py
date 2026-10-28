"""Bank files loaded again in any order (a conversion out of earlier drafts) and the
rates a statement in a currency needs."""

from __future__ import annotations

AZ = {
    "конвертация: сторона уже проведена операцией №{n} — отмените её проведение и "
    "загрузите файлы ещё раз": (
        "konvertasiya: bir tərəfi artıq №{n} əməliyyatı ilə keçirilib — onun keçirilməsini "
        "ləğv edin və faylları yenidən yükləyin"
    ),
    "Загрузить курсы ЦБА": "AMB məzənnələrini yüklə",
    "{code} — дней: {n}": "{code} — gün: {n}",
    "Нет курса ЦБА: {what}. Без курса строки этих дней не проводятся.": (
        "AMB məzənnəsi yoxdur: {what}. Məzənnəsiz bu günlərin sətirləri keçirilmir."
    ),
    "Курсы ЦБА: {n} из {total}": "AMB məzənnələri: {n} / {total}",
}
