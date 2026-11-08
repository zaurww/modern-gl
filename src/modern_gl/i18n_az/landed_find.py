"""Finding the landed costs: the report «Əlavə xərclər», the filter of the documents."""

AZ: dict[str, str] = {
    "Все доп. расходы": "Bütün əlavə xərclər",
    "Поступления с расходами: что и на сколько добавили": (
        "Xərcli daxilolmalar: nə və nə qədər əlavə olunub"
    ),
    "Только с расходами": "Yalnız xərcli",
    "Снимите, чтобы видеть и декларации без расходов": (
        "Xərcsiz bəyannamələri də görmək üçün işarəni götürün"
    ),
    "Нет дополнительных расходов": "Əlavə xərc yoxdur",
    "Таможня, доставка и другие расходы, вошедшие в стоимость товара": (
        "Malın dəyərinə daxil olan gömrük, çatdırılma və digər xərclər"
    ),
}
