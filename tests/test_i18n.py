"""Every user-facing string has an Azerbaijani translation with the same placeholders."""

import ast
import string
from pathlib import Path

import pytest

from modern_gl.application.catalog import search
from modern_gl.application.chart_csv import apply_chart_template
from modern_gl.i18n import fold, set_language, tr, upper
from modern_gl.i18n_az import AZ, PARTS
from tests.helpers.texts import CYRILLIC

SRC = Path(__file__).parent.parent / "src" / "modern_gl"
TR = ("tr", "trd")  # the interface's and the documents' language (D152)


def tr_keys() -> dict[str, str]:
    """All literal first arguments of tr(...) and trd(...) calls, with their location."""
    keys = {}
    for path in SRC.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            called = getattr(node, "func", None)
            if isinstance(node, ast.Call) and getattr(called, "id", None) in TR and node.args:
                arg = node.args[0]
                candidates = [arg.body, arg.orelse] if isinstance(arg, ast.IfExp) else [arg]
                for c in candidates:
                    if isinstance(c, ast.Constant) and isinstance(c.value, str):
                        keys[c.value] = f"{path.name}:{node.lineno}"
    return keys


def placeholders(s: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(s) if name}


def test_a_key_is_translated_in_one_file_only():
    """Each feature has its file of translations (D131); the same key in two of them
    would make the second one win silently."""
    seen: dict[str, str] = {}
    twice = {}
    for name, part in PARTS.items():
        for key in part:
            if key in seen:
                twice[key] = (seen[key], name)
            seen[key] = name
    assert not twice, twice


def test_every_tr_string_has_azerbaijani_translation():
    missing = {k: where for k, where in tr_keys().items() if k not in AZ and CYRILLIC & set(k)}
    assert not missing, missing


def test_translations_keep_placeholders():
    wrong = {k: v for k, v in AZ.items() if placeholders(k) != placeholders(v)}
    assert not wrong, wrong


def test_translated_message_in_azerbaijani():
    set_language("az")
    assert tr("строка {line}: нулевая сумма", line=2) == "sətir 2: məbləğ sıfırdır"
    set_language("ru")
    assert tr("строка {line}: нулевая сумма", line=2) == "строка 2: нулевая сумма"


def test_azerbaijani_chart_template(ledger, conn):
    set_language("az")
    cid = ledger.create_company("Test MMC")
    assert apply_chart_template(ledger, cid) == 42  # 09, 77 — deferred tax (D128)
    names = dict(conn.execute("SELECT code, name FROM accounts WHERE company_id = ?", (cid,)))
    assert names["50"] == "Kassa"
    assert names["46"] == "Məhsulun (işlərin, xidmətlərin) satışı"
    layers = [r[0] for r in conn.execute("SELECT name FROM layers WHERE company_id = ?", (cid,))]
    assert layers == ["Ümumi uçot", "MHBS düzəlişləri", "Vergi düzəlişləri"]


@pytest.mark.parametrize("typed", ["işçi", "ISCI", "isci", "İŞÇİ", "ışç"])
def test_search_ignores_case_and_azerbaijani_letters(typed):
    assert search(["Kassa", "İşçilər", "Bank"], typed) == ["İşçilər"]


def test_fold():
    assert fold("Əsas vəsaitlər") == "esas vesaitler"
    assert fold("Ёлка") == "елка"


def test_search_ranks_word_starts_first():
    labels = ["Ofis icarəsi", "İcarə haqqı", "Materiallar"]
    assert search(labels, "icar") == ["Ofis icarəsi", "İcarə haqqı"]
    assert search(labels, "ic")[0] == "Ofis icarəsi"
    assert search(labels, "") == labels


def test_azerbaijani_alphabetical_order():
    from modern_gl.i18n import sort_key

    words = ["Əsas vəsaitlər", "Anbarlar", "Şirkət", "Sabah", "İşçilər", "Ilıq", "Ekran", "Zavod"]
    assert sorted(words, key=sort_key) == [
        "Anbarlar",
        "Ekran",
        "Əsas vəsaitlər",
        "Ilıq",
        "İşçilər",
        "Sabah",
        "Şirkət",
        "Zavod",
    ]


def test_upper_knows_azerbaijani_dotted_i():
    set_language("az")
    try:
        assert upper("Siyahılar") == "SİYAHILAR"
    finally:
        set_language("ru")
    assert upper("Списки") == "СПИСКИ"
