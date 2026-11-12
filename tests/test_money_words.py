"""An amount in words for a cash order: written out by hand."""

from __future__ import annotations

import pytest

from modern_gl.domain.money_words import amount_in_words


@pytest.mark.parametrize(
    ("minor", "words"),
    [
        (0, "Sıfır manat 00 qəpik"),
        (5, "Sıfır manat 05 qəpik"),
        (100, "Bir manat 00 qəpik"),
        (1_100, "On bir manat 00 qəpik"),
        (10_000, "Yüz manat 00 qəpik"),
        (25_000, "İki yüz əlli manat 00 qəpik"),
        (100_000, "Min manat 00 qəpik"),
        (123_450, "Min iki yüz otuz dörd manat 50 qəpik"),
        (2_000_000, "İyirmi min manat 00 qəpik"),
        (11_100_000, "Yüz on bir min manat 00 qəpik"),
        (100_000_099, "Bir milyon manat 99 qəpik"),
        (300_200_100, "Üç milyon iki min bir manat 00 qəpik"),
    ],
)
def test_azerbaijani(minor, words):
    assert amount_in_words(minor, "az") == words


@pytest.mark.parametrize(
    ("minor", "words"),
    [
        (0, "Ноль манатов 00 копеек"),
        (101, "Один манат 01 копейка"),
        (202, "Два маната 02 копейки"),
        (1_105, "Одиннадцать манатов 05 копеек"),
        (2_121, "Двадцать один манат 21 копейка"),
        (123_450, "Одна тысяча двести тридцать четыре маната 50 копеек"),
        (200_000, "Две тысячи манатов 00 копеек"),
        (514_000, "Пять тысяч сто сорок манатов 00 копеек"),
        (1_100_000, "Одиннадцать тысяч манатов 00 копеек"),
        (200_000_000, "Два миллиона манатов 00 копеек"),
    ],
)
def test_russian(minor, words):
    assert amount_in_words(minor, "ru") == words


def test_no_negative_amount_in_words():
    with pytest.raises(ValueError, match="negative"):
        amount_in_words(-1, "az")
