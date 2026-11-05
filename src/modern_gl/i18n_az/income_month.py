"""«Доход за» on the line of a sale: a service of an earlier month (D65 for sales)."""

AZ: dict[str, str] = {
    "Доход за": "Gəlir dövrü",
    "Начисленные доходы": "Hesablanmış gəlirlər",
    "Начисление дохода по продаже №{n}": "Satış №{n} üzrə gəlirin hesablanması",
    "не определён счёт начисленных доходов: оставьте один активный счёт типа «Начисленные "
    "доходы» (например, {code})": "hesablanmış gəlirlər hesabı müəyyən deyil: «Hesablanmış "
    "gəlirlər» tipli bir aktiv hesab saxlayın (məsələn, {code})",
    "строка {line}: доход за {month} должен быть раньше месяца документа": (
        "sətir {line}: {month} gəliri sənədin ayından əvvəl olmalıdır"
    ),
    "доход за {month} не отнести: период закрыт по {closed}. Выберите в «Доход за» месяц "
    "документа": "{month} gəliri aid edilə bilməz: dövr {closed} tarixinədək bağlıdır. "
    "«Gəlir dövrü» sahəsində sənədin ayını seçin",
    "строка {line}: месяц дохода указывается для услуг в продаже, не для товара": (
        "sətir {line}: gəlir ayı satışda xidmətlər üçün göstərilir, mal üçün yox"
    ),
    "Проводки начисления дохода в месяце услуги": "Xidmət ayında gəlirin hesablanma yazılışları",
    "Доход за несколько месяцев": "Bir neçə ayın gəliri",
}
