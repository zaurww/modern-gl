"""Exchange of documents with other programs, the API and its command line (D130)."""

AZ: dict[str, str] = {
    "документ «{id}» в файле дважды": "«{id}» sənədi faylda iki dəfədir",
    "строка {line}: ожидается объект с полями проводки": "sətir {line}: yazılış sahələri olan obyekt gözlənilir",
    'субконто — списком, например ["Bakı Elektrik"]': 'subkonto — siyahı ilə, məsələn ["Bakı Elektrik"]',
    "документ {n}": "sənəd {n}",
    "файл": "fayl",
    'это не файл документов Modern GL: нет "format": "{f}"': 'bu Modern GL sənəd faylı deyil: "format": "{f}" yoxdur',
    "версия формата — целое число, например 1": "format versiyası — tam ədəd, məsələn 1",
    "файл версии {v}, программа читает до {max} — обновите программу": "fayl {v} versiyasındadır, proqram {max} versiyasına qədər oxuyur — proqramı yeniləyin",
    'не указан источник файла ("source")': 'faylın mənbəyi göstərilməyib ("source")',
    'нет списка документов ("documents")': 'sənədlər siyahısı yoxdur ("documents")',
    "{where}: ожидается объект": "{where}: obyekt gözlənilir",
    '{where}: нет "id" — его номер в вашей программе': '{where}: "id" yoxdur — sizin proqramınızdakı nömrəsi',
    "{where}: слой — один из {layers}": "{where}: qat — bunlardan biri: {layers}",
    '{where}: "memo" — строка': '{where}: "memo" — sətir olmalıdır',
    "{where}: лишние поля {keys}": "{where}: artıq sahələr {keys}",
    '{where}: дата — "ГГГГ-ММ-ДД", например "2026-03-05"': '{where}: tarix — "İİİİ-AA-GG", məsələn "2026-03-05"',
    "строка {line}: e-qaimə или декларация — одно из двух": "sətir {line}: e-qaimə və ya bəyannamə — ikisindən biri",
    "сторно: документа «{id}» нет среди загруженных": "storno: «{id}» sənədi yüklənənlər arasında yoxdur",
    '{where}: "reverses" — id документа, без своих проводок': '{where}: "reverses" — sənədin id-si, öz yazılışları olmadan',
}
