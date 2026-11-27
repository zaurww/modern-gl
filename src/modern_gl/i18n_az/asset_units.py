"""A line of several objects split into a line and an object per unit (D232)."""

AZ: dict[str, str] = {
    "По одной штуке — {n} строк": "Hər ədəd ayrıca — {n} sətir",
    "Каждая штука — своя строка и свой объект: «название №1», «№2»… Сумма — поровну": (
        "Hər ədəd — öz sətri və öz obyekti: «ad №1», «№2»… Məbləğ bərabər bölünür"
    ),
    "по одной штуке делится строка объектов с целым количеством": (
        "hər ədədə yalnız tam miqdarlı obyekt sətri bölünür"
    ),
    "больше {n} объектов разом не делится — сначала разделите строку": (
        "{n}-dən çox obyekt birdəfəyə bölünmür — əvvəlcə sətri bölün"
    ),
}
