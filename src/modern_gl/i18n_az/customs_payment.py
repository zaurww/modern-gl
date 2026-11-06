"""The customs payment and the account of a batch's expenses (D212)."""

from __future__ import annotations

AZ = {
    "Таможенный платёж": "Gömrük ödənişi",
    "Таможенный платёж {n}": "Gömrük ödənişi {n}",
    "Таможенный платёж…": "Gömrük ödənişi…",
    "Заполните только то, что есть в платеже. По короткой декларации обычно есть "
    "только терминал: его сумма — вместе с ƏDV, как в его e-qaimə.": (
        "Yalnız ödənişdə olanı doldurun. Qısa bəyannamədə adətən yalnız terminal olur: "
        "onun məbləği ƏDV ilə birlikdə, e-qaiməsində olduğu kimi."
    ),
    "Пошлины и сборы": "Rüsum və yığımlar",
    "Терминал": "Terminal",
    "Сумма терминалу": "Terminala məbləğ",
    "Таможня": "Gömrük",
    "ƏDV декларации": "Bəyannamənin ƏDV-si",
    "В плане счетов нет счёта поставщиков": "Hesablar planında malsatan hesabı yoxdur",
    "укажите сумму платежа": "ödənişin məbləğini göstərin",
    "укажите счёт дополнительных расходов в настройках склада": (
        "anbar parametrlərində əlavə xərclər hesabını göstərin"
    ),
    "укажите номер декларации: ƏDV идёт в зачёт по нему": (
        "bəyannamənin nömrəsini göstərin: ƏDV onunla əvəzləşdirilir"
    ),
    "укажите контрагента": "kontragenti göstərin",
    "таможенный платёж — расход в манатах": "gömrük ödənişi manatla məxaricdir",
    "по выписке {amount}, в строках {total}: разница {left}": (
        "çıxarışda {amount}, sətirlərdə {total}: fərq {left}"
    ),
    "{total} из {amount}": "{amount} məbləğdən {total}",
    "осталось {n}": "qalıb {n}",
    "укажите счёт НДС к возмещению в настройках склада": (
        "anbar parametrlərində əvəzləşdirilən ƏDV hesabını göstərin"
    ),
    "Счёт дополнительных расходов": "Əlavə xərclər hesabı",
    "Расходы партии ждут здесь и уходят в стоимость товара: Дт счёт товара / Кт этот счёт.": (
        "Partiya xərcləri burada gözləyir və malın dəyərinə keçir: Dt mal hesabı / Kt bu hesab."
    ),
}
