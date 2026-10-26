"""The warehouse's reports: the statement, an item's card, the gross profit."""

AZ: dict[str, str] = {
    "Ведомость по складу": "Anbar üzrə cədvəl",
    "Остаток на начало, приход, расход и остаток на конец — количество и сумма": (
        "Əvvələ qalıq, mədaxil, məxaric və sona qalıq — miqdar və məbləğ"
    ),
    "Валовая прибыль по товарам": "Mallar üzrə ümumi mənfəət",
    "Продано, выручка, себестоимость и прибыль — по товарам или покупателям": (
        "Satılıb, gəlir, maya dəyəri və mənfəət — mallar və ya alıcılar üzrə"
    ),
    "Начало": "Əvvələ",
    "Конец": "Sona",
    "Кол-во": "Miqdar",
    "По товарам": "Mallar üzrə",
    "По складам": "Anbarlar üzrə",
    "По покупателям": "Alıcılar üzrə",
    "Нет движений": "Hərəkət yoxdur",
    "За период на складе ничего не было: выберите другой период.": (
        "Bu dövrdə anbarda heç nə olmayıb: başqa dövr seçin."
    ),
    "Склад сходится со счетами товаров в книге: {sum}  ✓": (
        "Anbar kitabdakı mal hesabları ilə üst-üstə düşür: {sum}  ✓"
    ),
    "Склад {stock}, на счетах товаров в книге {books}: разница {diff} — "
    "проводки на этих счетах не из склада": (
        "Anbar {stock}, kitabdakı mal hesablarında {books}: fərq {diff} — "
        "bu hesablarda anbardan olmayan yazılışlar var"
    ),
    "Двойной щелчок — карточка товара": "İki dəfə klik — malın kartı",
    "Карточка товара": "Malın kartı",
    "Остаток на начало": "Əvvələ qalıq",
    "Остаток на конец": "Sona qalıq",
    "Движений: {n}. Двойной щелчок — документ": "Hərəkətlər: {n}. İki dəfə klik — sənəd",
    "Нет продаж": "Satış yoxdur",
    "За период проведённых продаж не было.": "Bu dövrdə keçirilmiş satış olmayıb.",
    "Услуги": "Xidmətlər",
    "Себестоимость — по средней на день продажи и доп. расходы, пришедшие позже. "
    "Двойной щелчок по товару — его карточка": (
        "Maya dəyəri — satış günündəki orta qiymətlə və sonra gələn əlavə xərclərlə. "
        "Mala iki dəfə klik — onun kartı"
    ),
    "Без покупателя": "Alıcısız",
    "Покупатель / товар": "Alıcı / mal",
    "Продано": "Satılıb",
    "Выручка без ƏDV": "ƏDV-siz gəlir",
    "Себестоимость": "Maya dəyəri",
    "Прибыль": "Mənfəət",
    "Маржа, %": "Marja, %",
}
