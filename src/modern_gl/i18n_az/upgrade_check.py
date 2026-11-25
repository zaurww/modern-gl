"""The books compared before and after an update; the warning about the second folder
(D-new-upgrade-check, D97)."""

AZ: dict[str, str] = {
    "обороты счёта {account} за {month}": "{account} hesabının {month} üzrə dövriyyəsi",
    "остаток товара на складе (товар № {item})": "malın anbar qalığı (mal № {item})",
    (
        "обновление изменило бы цифры учёта: {first}; всего расхождений — {n}. "
        "Сообщите разработчику"
    ): (
        "yeniləmə uçot rəqəmlərini dəyişərdi: {first}; cəmi uyğunsuzluq — {n}. "
        "Proqramçıya məlumat verin"
    ),
    "Вторая папка для копий не выбрана": "Nüsxələr üçün ikinci qovluq seçilməyib",
    "копии лежат только на этом диске": "nüsxələr yalnız bu diskdədir",
    "Во второй папке нет последней копии": "İkinci qovluqda son nüsxə yoxdur",
    "папка недоступна?": "qovluq əlçatan deyil?",
}
