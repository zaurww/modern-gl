"""A bank line never vanishes without a word: the import's note next to the line, a
hand-posted side replaced by the conversion, a difference that names its drafts."""

from __future__ import annotations

AZ = {
    "вместо проведённых вручную операций №{numbers}": (
        "əl ilə keçirilmiş №{numbers} əməliyyatların əvəzinə"
    ),
    "конвертация: сторона проведена операцией №{n} в закрытом периоде — "
    "исправьте её сторно и загрузите файлы ещё раз": (
        "konvertasiya: bir tərəfi №{n} əməliyyatı ilə bağlı dövrdə keçirilib — "
        "onu storno ilə düzəldin və faylları yenidən yükləyin"
    ),
    "расхождение {amount} · черновиков {n}": "fərq {amount} · qaralama {n}",
    "Расхождение {amount}: черновиков {n} — они не двигают остаток; проведите их или удалите": (
        "Fərq {amount}: qaralama {n} — onlar qalığı dəyişmir; keçirin və ya silin"
    ),
}
