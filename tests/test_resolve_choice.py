"""One search in a cell's list (resolve_choice): the stock documents and the landed cost
use the same one."""

import pytest

from modern_gl.desktop.cell_editing import resolve_choice

CHOICES = [
    (1, "601  Kağız A4"),
    (2, "602  Kağız A3"),
    (3, "Daşınma"),
    (4, "Daşınma xərci"),
    (5, "Sığorta"),
]


@pytest.mark.parametrize(
    ("text", "found"),
    [
        ("601  Kağız A4", 1),  # the whole label
        ("kağız a3", 2),  # the name, any case
        ("602", 2),  # the code
        ("KAGIZ A4", 1),  # ğ = g (fold)
        ("Daşınma", 3),  # exact wins over «Daşınma xərci» that also has it
        ("xərci", 4),  # a fragment in one label only
        ("sıg", 5),  # the start of one label
        ("Nəqliyyat", None),  # nothing matches
    ],
)
def test_finds_by_label_name_code_or_fragment(text, found):
    assert resolve_choice(CHOICES, text) == found


def test_one_label_starting_with_the_text_wins_over_others_containing_it():
    choices = [(1, "Arenda"), (2, "Ofis arendası"), (3, "Anbar arendası")]
    assert resolve_choice(choices, "arend") == 1


def test_several_matches_name_them():
    with pytest.raises(LookupError, match="Kağız A4, 602  Kağız A3"):
        resolve_choice(CHOICES, "kağız")
