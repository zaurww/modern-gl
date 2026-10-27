"""Returns: goods back to the supplier and from a customer."""

AZ: dict[str, str] = {
    "+ Возврат поставщику": "+ Malsatana qaytarma",
    "+ Возврат от покупателя": "+ Alıcıdan qaytarma",
    "Возврат": "Qaytarma",
    "Возврат поставщику": "Malsatana qaytarma",
    "Возврат от покупателя": "Alıcıdan qaytarma",
    "неизвестный вид возврата": "naməlum qaytarma növü",
    "строка {line}: возвращаемая строка документа не найдена": (
        "sətir {line}: sənədin qaytarılan sətri tapılmadı"
    ),
    "строка {line}: укажите товар и склад": "sətir {line}: malı və anbarı göstərin",
    "строка {line}: не указан контрагент": "sətir {line}: kontragent göstərilməyib",
    "строка {line}: по документу №{n} можно вернуть не больше {q}": (
        "sətir {line}: №{n} sənədi üzrə {q}-dən çox qaytarmaq olmaz"
    ),
    "цена возврата не равна себестоимости, а счёта прочих доходов/расходов нет": (
        "qaytarma qiyməti maya dəyərinə bərabər deyil, digər gəlir/xərc hesabı isə yoxdur"
    ),
    "строка {line}: «{item}» нет на складе, себестоимость не из чего взять — укажите "
    "продажу, по которой возврат": (
        "sətir {line}: «{item}» anbarda yoxdur, maya dəyərini götürməyə yer yoxdur — "
        "qaytarmanın aid olduğu satışı göstərin"
    ),
    "строка {line}: укажите товар": "sətir {line}: malı göstərin",
    "Разница цены возврата": "Qaytarma qiymətinin fərqi",
    "строка {line}: по ней оформлен возврат №{n} — сначала удалите его": (
        "sətir {line}: onun üzrə №{n} qaytarma rəsmiləşdirilib — əvvəlcə onu silin"
    ),
    "Оформить возврат": "Qaytarma rəsmiləşdir",
    "Товар вернули: возврат по этому документу — его цены и ƏDV, без лишнего ввода": (
        "Mal qaytarılıb: bu sənəd üzrə qaytarma — onun qiymətləri və ƏDV, artıq daxiletmə olmadan"
    ),
    "Возврат по документу №{n}": "№{n} sənədi üzrə qaytarma",
    "По документу №{n} возвращать нечего": "№{n} sənədi üzrə qaytarılacaq bir şey yoxdur",
    "Возврат по e-qaimə {n}": "{n} e-qaiməsi üzrə qaytarma",
    "возврат услуг — вводится вручную": "xidmətlərin qaytarılması — əl ilə daxil edilir",
    "e-qaimə {invoice} — номер документа №{n}; у возврата своя e-qaimə возврата, её "
    "ƏDV — в месяце возврата": (
        "e-qaimə {invoice} — №{n} sənədinin nömrəsidir; qaytarmanın öz qaytarma e-qaiməsi "
        "var, onun ƏDV-si qaytarma ayındadır"
    ),
    "строка {line}: возврат не может быть раньше документа №{n} от {date}": (
        "sətir {line}: qaytarma №{n} sənədindən ({date}) əvvəl ola bilməz"
    ),
}
