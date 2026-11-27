"""Loading a bank's file: no line goes unsaid — what was left out and why, what a
difference with the bank is made of, the other side of a transfer loaded before."""

from __future__ import annotations

AZ = {
    "галочка снята": "işarə götürülüb",
    "программа не узнала строку": "proqram sətri tanımadı",
    "не загружена: {why}": "yüklənməyib: {why}",
    "другая сторона перевода — операция №{n}: проверьте счёт и проведите": (
        "köçürmənin digər tərəfi — №{n} əməliyyatı: hesabı yoxlayın və keçirin"
    ),
    ", не загружено {n} (строки сверху, причина — в строке)": (
        ", yüklənməyib {n} (sətirlər yuxarıda, səbəb sətirdə)"
    ),
    "Строк в файлах: {n}. ": "Fayllarda sətir: {n}. ",
    "на начало выписки в банке {bank}, в программе {books} — "
    "загрузите прежние выписки или введите начальный остаток": (
        "çıxarışın əvvəlinə bankda {bank}, proqramda {books} — "
        "əvvəlki çıxarışları yükləyin və ya ilkin qalığı daxil edin"
    ),
    "не загружено строк: {n} на {amount}": "yüklənməyən sətir: {n}, məbləğ {amount}",
}
