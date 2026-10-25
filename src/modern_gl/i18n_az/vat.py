"""The ƏDV module: the credit of input ƏDV by the rule of its time (docs/REPORTING.md)."""

AZ: dict[str, str] = {
    "правил ƏDV за {year} год в программе нет": "{year}-ci il üçün ƏDV qaydaları proqramda yoxdur",
    "ƏDV к зачёту": "Əvəzləşdiriləcək ƏDV",
    "Зачёт ƏDV покупок по дням: e-qaimə, оплата суммы и ƏDV; декларации — по оплате ƏDV": (
        "Alışların ƏDV əvəzləşdirilməsi günlər üzrə: e-qaimə, məbləğin və ƏDV-nin ödənişi; "
        "bəyannamələr — ƏDV ödənişi ilə"
    ),
    "ГТД {n}": "GB {n}",
    "Зачёта за период нет": "Dövr üçün əvəzləşdirmə yoxdur",
    "ƏDV покупки зачитывается, когда есть e-qaimə и оплачены основная сумма с банка и ƏDV на "
    "депозитный счёт поставщика, в доле оплаченного; по таможенной декларации — по оплате "
    "ƏDV таможне.": (
        "Alışın ƏDV-si e-qaimə olduqda və əsas məbləğ bankdan, ƏDV isə təchizatçının depozit "
        "hesabına ödənildikdə, ödənilən payda əvəzləşdirilir; gömrük bəyannaməsi üzrə — ƏDV "
        "gömrüyə ödənildikdə."
    ),
    "Дата зачёта": "Əvəzləşdirmə tarixi",
    "E-qaimə / ГТД": "E-qaimə / GB",
    "ƏDV по документу": "Sənəd üzrə ƏDV",
    "К зачёту": "Əvəzləşdirilir",
    "Зачтено ранее": "Əvvəl əvəzləşdirilib",
    "Ждёт": "Gözləyir",
    "К зачёту за период: {credited}   ·   ждут e-qaimə или оплаты: {waiting} по {n} покупкам": (
        "Dövr üzrə əvəzləşdirilir: {credited}   ·   e-qaimə və ya ödəniş gözləyir: {waiting}, "
        "{n} alış"
    ),
}
