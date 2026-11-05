"""The stock account of an item: seen and changed on a purchase line, changed with
documents too (D202)."""

AZ = {
    "По товару есть документы: единица не меняется; со сменой счёта они проведутся заново": (
        "Mal üzrə sənədlər var: ölçü vahidi dəyişmir; hesab dəyişdikdə onlar yenidən keçirilir"
    ),
    "счёт товара менять нельзя: его документы есть в закрытом периоде (по {date})": (
        "malın hesabını dəyişmək olmaz: onun sənədləri bağlı dövrdə var ({date} tarixinədək)"
    ),
    "«{account}» — не счёт запасов: у него нет субконто товара и склада": (
        "«{account}» ehtiyat hesabı deyil: onun mal və anbar subkontosu yoxdur"
    ),
    "«{name}»: счёт запасов — {account}": "«{name}»: ehtiyat hesabı — {account}",
    "Куда приходит строка: товар — на свой счёт запасов (сменить его можно "
    "здесь — документы товара проведутся заново), услуга — на счёт затрат": (
        "Sətir hara gəlir: mal — öz ehtiyat hesabına (onu burada dəyişmək olar — malın "
        "sənədləri yenidən keçirilir), xidmət — xərc hesabına"
    ),
}
