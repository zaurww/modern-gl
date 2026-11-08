"""Expenses that wait for a batch (D211)."""

from __future__ import annotations

AZ = {
    "+ Ждущие расходы…": "+ Gözləyən xərclər…",
    "Расходы, ждущие партии": "Partiya gözləyən xərclər",
    "Расходов, ждущих партии, нет": "Partiya gözləyən xərc yoxdur",
    "Все расходы": "Bütün xərclər",
    "Взять отмеченные": "Seçilənləri götür",
    "Отмеченные войдут в стоимость партии: новый долг не появится. Вводите вручную "
    "только то, чего здесь нет, например таможенные платежи.": (
        "Seçilənlər partiyanın dəyərinə düşəcək, yeni borc yaranmayacaq. Əl ilə yalnız burada "
        "olmayanı daxil edin, məsələn, gömrük ödənişlərini."
    ),
    "Расход уже есть в книгах": "Xərc artıq kitablarda var",
    "{amount} уже ждёт партии: {label}.\n\n"
    "Если ввести его ещё раз, долг поставщику задвоится. Взять этот расход вместо "
    "введённого?": (
        "{amount} artıq partiya gözləyir: {label}.\n\n"
        "Onu yenidən daxil etsəniz, malsatana borc ikiqat olacaq. Daxil edilənin yerinə bu "
        "xərc götürülsün?"
    ),
    "как расход можно взять только услугу из покупки": (
        "xərc kimi yalnız alışdakı xidmət götürülə bilər"
    ),
    "расход {n}: документ №{m} не проведён": "xərc {n}: №{m} sənəd keçirilməyib",
    "расход {n}: в документе №{m} изменился счёт услуги": (
        "xərc {n}: №{m} sənəddə xidmətin hesabı dəyişib"
    ),
    "расход {n}: услуга документа №{number} — {amount}, уже распределено {used}, осталось {left}": (
        "xərc {n}: №{number} sənədin xidməti — {amount}, artıq bölüşdürülüb {used}, qalıb {left}"
    ),
    "строка {line}: она взята расходом партии (документ №{n}) — сначала уберите её оттуда": (
        "sətir {line}: partiya xərcinə götürülüb (№{n} sənəd) — əvvəlcə oradan çıxarın"
    ),
}
