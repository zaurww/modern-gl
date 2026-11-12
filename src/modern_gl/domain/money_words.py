"""An amount in words, as a cash order writes it: «Min iki yüz otuz dörd manat 50 qəpik»,
«Одна тысяча двести тридцать четыре маната 50 копеек». The manats in words, the
qəpiks in figures; the first letter capital. Azerbaijani and Russian — the languages of
documents (D152)."""

from __future__ import annotations

AZ_ONES = ("", "bir", "iki", "üç", "dörd", "beş", "altı", "yeddi", "səkkiz", "doqquz")
AZ_TENS = ("", "on", "iyirmi", "otuz", "qırx", "əlli", "altmış", "yetmiş", "səksən", "doxsan")
AZ_SCALES = ("", "min", "milyon", "milyard")

RU_ONES = ("", "один", "два", "три", "четыре", "пять", "шесть", "семь", "восемь", "девять")
RU_ONES_FEMININE = ("", "одна", "две", *RU_ONES[3:])
RU_TEENS = (
    "десять",
    "одиннадцать",
    "двенадцать",
    "тринадцать",
    "четырнадцать",
    "пятнадцать",
    "шестнадцать",
    "семнадцать",
    "восемнадцать",
    "девятнадцать",
)
RU_TENS = (
    "",
    "",
    "двадцать",
    "тридцать",
    "сорок",
    "пятьдесят",
    "шестьдесят",
    "семьдесят",
    "восемьдесят",
    "девяносто",
)
RU_HUNDREDS = (
    "",
    "сто",
    "двести",
    "триста",
    "четыреста",
    "пятьсот",
    "шестьсот",
    "семьсот",
    "восемьсот",
    "девятьсот",
)
# a scale's forms for 1, 2–4 and 5+ (тысяча, тысячи, тысяч), and whether it is feminine
RU_SCALES = (
    (("", "", ""), False),
    (("тысяча", "тысячи", "тысяч"), True),
    (("миллион", "миллиона", "миллионов"), False),
    (("миллиард", "миллиарда", "миллиардов"), False),
)
RU_MANAT = ("манат", "маната", "манатов")
RU_KOPEK = ("копейка", "копейки", "копеек")


def amount_in_words(minor: int, language: str) -> str:
    """Minor units in words: the manats spelled, the qəpiks as two figures."""
    if minor < 0:
        raise ValueError("amount in words: negative")
    manats, qepiks = divmod(minor, 100)
    if language == "ru":
        words = _ru(manats) or "ноль"
        text = f"{words} {_ru_form(manats, RU_MANAT)} {qepiks:02d} {_ru_form(qepiks, RU_KOPEK)}"
    else:
        text = f"{_az(manats) or 'sıfır'} manat {qepiks:02d} qəpik"
    first = {"i": "İ", "ı": "I"}.get(text[0], text[0].upper())  # Azerbaijani İ
    return first + text[1:]


def _groups(n: int) -> list[int]:
    """Three-digit groups, the lowest first: 1 234 567 → [567, 234, 1]."""
    groups: list[int] = []
    while n:
        n, group = divmod(n, 1000)
        groups.append(group)
    return groups


def _az(n: int) -> str:
    """Azerbaijani: «yüz», «min» without «bir» before them (min, not bir min)."""
    words: list[str] = []
    for scale, group in reversed(list(enumerate(_groups(n)))):
        if not group:
            continue
        if scale == 1 and group == 1:  # min
            words.append(AZ_SCALES[1])
            continue
        words.append(_az_group(group))
        if scale:
            words.append(AZ_SCALES[scale])
    return " ".join(w for w in words if w)


def _az_group(n: int) -> str:
    hundreds, rest = divmod(n, 100)
    tens, ones = divmod(rest, 10)
    words: list[str] = []
    if hundreds:
        words += [AZ_ONES[hundreds], "yüz"] if hundreds > 1 else ["yüz"]
    words += [AZ_TENS[tens], AZ_ONES[ones]]
    return " ".join(w for w in words if w)


def _ru(n: int) -> str:
    words: list[str] = []
    for scale, group in reversed(list(enumerate(_groups(n)))):
        if not group:
            continue
        forms, feminine = RU_SCALES[scale]
        words.append(_ru_group(group, feminine))
        if scale:
            words.append(_ru_form(group, forms))
    return " ".join(w for w in words if w)


def _ru_group(n: int, feminine: bool) -> str:
    hundreds, rest = divmod(n, 100)
    tens, ones = divmod(rest, 10)
    words = [RU_HUNDREDS[hundreds]]
    if tens == 1:
        words.append(RU_TEENS[ones])
    else:
        words += [RU_TENS[tens], (RU_ONES_FEMININE if feminine else RU_ONES)[ones]]
    return " ".join(w for w in words if w)


def _ru_form(n: int, forms: tuple[str, str, str]) -> str:
    """тысяча / тысячи / тысяч by the number's end: 1, 21 — one; 2–4, 22 — two; else five."""
    if 11 <= n % 100 <= 14:
        return forms[2]
    last = n % 10
    if last == 1:
        return forms[0]
    return forms[1] if 2 <= last <= 4 else forms[2]
