"""Updating a company file to a newer program (D148)."""

AZ: dict[str, str] = {
    "Файл «{file}» обновлён более новой версией Modern GL (схема {found}, эта "
    "программа знает до {known}). Обновите программу — файл не изменён": (
        "«{file}» faylı Modern GL-in daha yeni versiyası ilə yenilənib (sxem {found}, bu "
        "proqram {known}-ə qədər bilir). Proqramı yeniləyin — fayl dəyişdirilmədi"
    ),
    "Файл «{file}» не удалось обновить для этой версии программы: {error}. "
    "Файл не изменён, его копия до обновления — {copy}": (
        "«{file}» faylını proqramın bu versiyası üçün yeniləmək alınmadı: {error}. "
        "Fayl dəyişdirilmədi, onun yenilənmədən əvvəlki nüsxəsi — {copy}"
    ),
    "Открыть компанию": "Şirkəti aç",
}
