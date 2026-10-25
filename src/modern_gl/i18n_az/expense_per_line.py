"""«Расход за» on the line of a purchase and splitting a line (D65 practice, D-new1)."""

AZ: dict[str, str] = {
    "несколько месяцев…": "bir neçə ay…",
    "месяц не распознан: {text}": "ay tanınmadı: {text}",
    "выберите хотя бы два месяца": "ən azı iki ay seçin",
    "количество во вторую строку — больше нуля и меньше всего": (
        "ikinci sətrə miqdar — sıfırdan çox və cəmdən az"
    ),
    "сумма во вторую строку — больше нуля и меньше всей": (
        "ikinci sətrə məbləğ — sıfırdan çox və cəmdən az"
    ),
    "в строке нет суммы — нечего делить": "sətirdə məbləğ yoxdur — bölməyə nə var",
    "Разделить строку": "Sətri böl",
    "Всего {quantity}": "Cəmi {quantity}",
    "Всего {amount}": "Cəmi {amount}",
    "во вторую строку": "ikinci sətrə",
    "введите число": "ədəd daxil edin",
    "Расход за несколько месяцев": "Bir neçə ayın xərci",
    "Сумма строки делится поровну между месяцами": "Sətrin məbləği aylar arasında bərabər bölünür",
    "Первый месяц": "Birinci ay",
    "Последний месяц": "Sonuncu ay",
    "строка {line}: месяц расхода указывается для услуг и расходов в покупке, не для товара": (
        "sətir {line}: xərc ayı alışda xidmət və xərclər üçün göstərilir, mal üçün yox"
    ),
    "строка {line}: расход за {month} должен быть раньше месяца документа": (
        "sətir {line}: {month} xərci sənədin ayından əvvəl olmalıdır"
    ),
    "Enter, Tab — дальше   ·   Shift+Tab — назад   ·   Ins — строка   ·   F9 — копия строки   ·   "
    "F8 — разделить строку   ·   Del — удалить строку   ·   Ctrl+V — вставить из Excel   ·   "
    "Ctrl+S — сохранить   ·   Ctrl+Enter — провести": (
        "Enter, Tab — irəli   ·   Shift+Tab — geri   ·   Ins — sətir   ·   F9 — sətrin surəti   ·   "
        "F8 — sətri böl   ·   Del — sətri sil   ·   Ctrl+V — Excel-dən yapışdır   ·   "
        "Ctrl+S — saxla   ·   Ctrl+Enter — keçir"
    ),
}
