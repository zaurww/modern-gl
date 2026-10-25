"""Stage 4 of the ƏDV declaration: a payer of ƏDV from a day; the ƏDV paid from a bank
account to the supplier's deposit."""

AZ: dict[str, str] = {
    "Плательщик ƏDV": "ƏDV ödəyicisi",
    "Плательщик ƏDV с…": "ƏDV ödəyicisi tarixdən…",
    "Плательщик ƏDV с даты (ДД.ММ.ГГГГ; пусто — с самого начала):": (
        "ƏDV ödəyicisi tarixdən (GG.AA.İİİİ; boş — lap əvvəldən):"
    ),
    "Не понял дату: {text}": "Tarix tanınmadı: {text}",
    "Плательщик ƏDV с {day}: до этого дня ƏDV не начисляется и не зачитывается": (
        "{day} tarixdən ƏDV ödəyicisi: bu günə qədər ƏDV hesablanmır və əvəzləşdirilmir"
    ),
    "ƏDV поставщику": "Təchizatçıya ƏDV",
    "банк {bank} + ƏDV {vat} = {total}": "bank {bank} + ƏDV {vat} = {total}",
    "С этого счёта — на депозит поставщика": "Bu hesabdan — təchizatçının depozitinə",
    "ƏDV — с этого счёта на депозитный счёт поставщика": (
        "ƏDV — bu hesabdan təchizatçının depozit hesabına"
    ),
    "ƏDV от покупателя приходит на депозит — выберите его": (
        "Alıcıdan ƏDV depozitə daxil olur — onu seçin"
    ),
    "строка {line}: ƏDV на депозит поставщика — только расход": (
        "sətir {line}: təchizatçının depozitinə ƏDV — yalnız məxaric"
    ),
    "строка {line}: pays_vat — true или false": "sətir {line}: pays_vat — true və ya false",
}
