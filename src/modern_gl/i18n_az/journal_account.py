"""«Сменить счёт у отмеченных» in the journal (D225); the basis «YGB»."""

AZ: dict[str, str] = {
    (
        "Отмечено документов: {n}. Каждый сохранит номер и статус, проведённый будет "
        "проведён заново; прежний вид — в журнале действий. В покупке меняется счёт "
        "строк без товара; счёт товара и ƏDV остаются."
    ): (
        "Seçilmiş sənədlər: {n}. Hər biri nömrəsini və statusunu saxlayacaq, keçirilmiş sənəd "
        "yenidən keçiriləcək; əvvəlki görünüşü əməliyyatlar jurnalındadır. Alışda malsız "
        "sətirlərin hesabı dəyişir; malın hesabı və ƏDV olduğu kimi qalır."
    ),
    "Счёт сменён в документах: {n}": "Hesab dəyişdirildi, sənəd sayı: {n}",
    "; без изменений: {n}": "; dəyişməyən: {n}",
    "ГТД": "YGB",
    "Отмечено: {n} на {sum}": "Seçilib: {n}, məbləğ {sum}",
}
