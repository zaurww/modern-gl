"""Bank statement files (D146): the forms of the banks read, the lines loaded into the
bank, the window of the load."""

AZ: dict[str, str] = {
    # the window
    "Выписка из файла": "Fayldan çıxarış",
    "Выписки банка (*.xlsx)": "Bank çıxarışları (*.xlsx)",
    "Загрузить выписку из файла…": "Fayldan çıxarış yüklə…",
    "— выберите счёт —": "— hesabı seçin —",
    "Выберите счёт для: {files}.": "Hesabı seçin: {files}.",
    "Будет проведено {posted}, на проверку черновиками {drafts} (причина — в строке)": (
        "Keçiriləcək: {posted}, yoxlamaya qaralama kimi: {drafts} (səbəbi — sətirdə)"
    ),
    "Из выписки: проведено {posted}, на проверку {drafts}": (
        "Çıxarışdan: keçirildi {posted}, yoxlamaya {drafts}"
    ),
    "Новых строк нет — запишутся только остатки дней по выписке.": (
        "Yeni sətir yoxdur — yalnız çıxarışa görə günlərin qalıqları yazılacaq."
    ),
    " — новых строк нет": " — yeni sətir yoxdur",
    "{account}: по выписке {bank} {currency}, в программе {books}": (
        "{account}: çıxarışa görə {bank} {currency}, proqramda {books}"
    ),
    " — разница {diff}": " — fərq {diff}",
    " — сойдётся, когда будут проведены черновики ({drafts})": (
        " — qaralamalar keçiriləndə üst-üstə düşəcək ({drafts})"
    ),
    # why a line waits for the user
    "что это — выберите счёт": "bu nədir — hesabı seçin",
    "налог: проверьте счёт (код бюджета {code})": "vergi: hesabı yoxlayın (büdcə kodu {code})",
    "налог без кода бюджета — проверьте счёт": "büdcə kodu olmayan vergi — hesabı yoxlayın",
    "не найден счёт расчётов": "hesablaşma hesabı tapılmadı",
    "не задан счёт комиссий банка": "bank komissiyası hesabı təyin edilməyib",
    "свой счёт {iban} не найден среди банковских": (
        "öz hesabı {iban} bank hesabları arasında tapılmadı"
    ),
    "не найден счёт зарплаты": "əmək haqqı hesabı tapılmadı",
    "вторая сторона — в выписке другого счёта": "ikinci tərəf — digər hesabın çıxarışındadır",
    "конвертация: {name}": "konvertasiya: {name}",
    "комиссия конвертации": "konvertasiya komissiyası",
    "новый контрагент — проверьте": "yeni kontragent — yoxlayın",
    "в назначении нет e-qaimə и долга нет — аванс?": (
        "təyinatda e-qaimə yoxdur və borc yoxdur — avans?"
    ),
    "в назначении нет e-qaimə — разложено по старым": (
        "təyinatda e-qaimə yoxdur — köhnələr üzrə bölündü"
    ),
    "e-qaimə {n} нет среди неоплаченных у контрагента": (
        "e-qaimə {n} kontragentin ödənilməmişləri arasında yoxdur"
    ),
    "сумма больше долга по e-qaimə на {diff}": "məbləğ e-qaimə üzrə borcdan {diff} çoxdur",
    "{file}: выписка счёта другой фирмы (VÖEN {theirs}, у компании {mine})": (
        "{file}: başqa firmanın hesabının çıxarışı (VÖEN {theirs}, şirkətin VÖEN-i {mine})"
    ),
    # reading a file
    "{file}: не найдена строка заголовков таблицы": "{file}: cədvəlin başlıq sətri tapılmadı",
    "{file}: в шапке нет «{label}»": "{file}: başlıqda «{label}» yoxdur",
    "{file}: не понят период «{text}»": "{file}: dövr tanınmadı «{text}»",
    "{file}, строка {n}: не понята дата «{text}»": "{file}, sətir {n}: tarix tanınmadı «{text}»",
    "{file}, строка {n}: {error}": "{file}, sətir {n}: {error}",
    "{file}: форма выписки не распознана. Понятны выписки: {banks}": (
        "{file}: çıxarışın forması tanınmadı. Tanınan çıxarışlar: {banks}"
    ),
    "{file}: остаток на конец {shown} в файле, а по строкам {counted} — файл прочитан неверно": (
        "{file}: faylda son qalıq {shown}, sətirlərə görə isə {counted} — fayl səhv oxundu"
    ),
    "{file}, строка {n}: остаток {shown} в файле, а по строкам {counted} — файл прочитан неверно": (
        "{file}, sətir {n}: faylda qalıq {shown}, sətirlərə görə isə {counted} — fayl səhv oxundu"
    ),
}
