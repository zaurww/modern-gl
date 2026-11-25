"""Backups kept by time and made every hour; trial versions (D222,
D223)."""

AZ: dict[str, str] = {
    (
        "Копия делается при закрытии компании и каждый час работы, если что-то изменилось. "
        "Хранятся последние {n}, затем последняя копия каждого дня — {days} дней, и каждого "
        "месяца — {months} месяцев. Папка: {folder}"
    ): (
        "Nüsxə şirkət bağlananda və işin hər saatında, nəsə dəyişibsə, çıxarılır. Sonuncu {n} "
        "nüsxə, sonra hər günün son nüsxəsi — {days} gün, hər ayın son nüsxəsi — {months} ay "
        "saxlanılır. Qovluq: {folder}"
    ),
    "Вышла пробная версия {version} — обновить": "Sınaq versiyası {version} — yeniləyin",
    "Пробные версии программы": "Proqramın sınaq versiyaları",
}
