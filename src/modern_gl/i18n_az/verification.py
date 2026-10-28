"""«Проверка книги» (D175): the checks, what they find, the window."""

AZ: dict[str, str] = {
    # the checks
    "Файл компании цел": "Şirkət faylı salamatdır",
    "Проведённые документы соответствуют правилам проведения": (
        "Keçirilmiş sənədlər keçirmə qaydalarına uyğundur"
    ),
    "Сторно повторяют свои документы": "Stornolar öz sənədlərini təkrarlayır",
    "Проводки модулей совпадают с их документами": (
        "Modulların yazılışları onların sənədləri ilə üst-üstə düşür"
    ),
    "Банк сходится с выписками банка": "Bank bankın çıxarışları ilə uyğun gəlir",
    "Склад сходится со счетами запасов": "Anbar ehtiyat hesabları ilə uyğun gəlir",
    # what they find
    "№{n} от {date}: {problem}": "№{n} ({date}): {problem}",
    "документ №{n}, который оно сторнирует, не проведён": ("stornoladığı sənəd №{n} keçirilməyib"),
    "сторно не в той книге, что документ №{n}": "storno sənəd №{n} ilə eyni kitabda deyil",
    "проводки не повторяют документ №{n} с обратным знаком": (
        "yazılışlar sənəd №{n}-i əks işarə ilə təkrarlamır"
    ),
    "проводки отличаются от документа раздела «{module}»": (
        "yazılışlar «{module}» bölməsinin sənədindən fərqlənir"
    ),
    "Конвертация": "Konvertasiya",
    "перестроить не удалось: {error}": "yenidən qurmaq alınmadı: {error}",
    "счёт {account}: на складе {stock}, по книге {books}, разница {diff}": (
        "hesab {account}: anbarda {stock}, kitabda {books}, fərq {diff}"
    ),
    "{place}, выписка {period}: по банку {bank}, в программе {books}, разница {diff}": (
        "{place}, çıxarış {period}: bankda {bank}, proqramda {books}, fərq {diff}"
    ),
    # the window
    "Проверка книги…": "Kitabın yoxlanışı…",
    "Проверка книги": "Kitabın yoxlanışı",
    "Программа сверяет свои данные: файл, правила проведения, сторно, проводки модулей, банк и склад. В файле ничего не меняется.": "Proqram öz məlumatlarını üzləşdirir: fayl, keçirmə qaydaları, storno, modulların yazılışları, bank və anbar. Faylda heç nə dəyişmir.",
    "Проверяю…": "Yoxlanılır…",
    "Всё сходится": "Hər şey uyğundur",
    "Найдено расхождений: {n}": "Tapılan fərqlər: {n}",
    "Проверка не закончена": "Yoxlanış başa çatmadı",
    "Открыть документ": "Sənədi aç",
    "Перестроить проводки": "Yazılışları yenidən qur",
    "Проводки банка, конвертации и склада открытого периода будут построены заново по их документам. Прежние останутся в истории изменений.": "Açıq dövrün bank, konvertasiya və anbar yazılışları onların sənədlərinə görə yenidən qurulacaq. Əvvəlkilər dəyişikliklər tarixçəsində qalacaq.",
    "Перестроено документов: {n}": "Yenidən qurulan sənədlər: {n}",
}
