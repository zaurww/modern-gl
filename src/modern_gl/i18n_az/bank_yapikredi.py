"""Yapı Kredi Bank's statement file: what its form may say when it is not read."""

AZ: dict[str, str] = {
    "{file}: {error}": "{file}: {error}",
    "не понята дата «{text}»": "tarix tanınmadı «{text}»",
    "{file}, строка {n}: сумма должна быть в одной из колонок — «Kredit» или «Debit»": (
        "{file}, sətir {n}: məbləğ sütunlardan birində olmalıdır — «Kredit» və ya «Debit»"
    ),
}
