"""The exchange file of documents (D130, docs/EXCHANGE.md) over the golden example
(conftest): two March documents of another program, by names.

  S-1  2026-03-02  Dt 201        Ct 531 [A]   150.00  materials from supplier A
  S-2  2026-03-03  Dt 531 [A]    Ct 221       150.00  paid supplier A

Expected ОСВ for March 2026 (hand-calculated; February closing is the opening):
  account  opening Dt/Ct   turnover Dt/Ct   closing Dt/Ct
  201      1 400 / -          150 / -         1 550 / -
  221      7 000 / -            - / 150       6 850 / -
  531          - / 700        150 / 150           - / 700
"""

from __future__ import annotations

import copy

import pytest

from modern_gl.application.exchange import FormatError, import_batch, parse_batch
from modern_gl.application.queries import load_document
from modern_gl.reporting.reports import trial_balance

FILE = {
    "format": "modern-gl/documents",
    "version": 1,
    "source": "test-shop",
    "documents": [
        {
            "id": "S-1",
            "date": "2026-03-02",
            "memo": "materials from supplier A",
            "postings": [
                {
                    "debit": "201",
                    "credit": "531",
                    "amount": "150.00",
                    "credit_subconto": ["Поставщик A"],
                }
            ],
        },
        {
            "id": "S-2",
            "date": "2026-03-03",
            "postings": [
                {
                    "debit": "531",
                    "debit_subconto": ["Поставщик A"],
                    "credit": "221",
                    "amount": "150.00",
                }
            ],
        },
    ],
}


def file(**changes) -> dict:
    data = copy.deepcopy(FILE)
    data.update(changes)
    return data


def march(demo) -> dict[str, tuple[int, int, int, int, int, int]]:
    osv = trial_balance(demo.ledger.conn, demo.company_id, "2026-03-01", "2026-03-31")
    return {
        r.code: (
            r.opening_dt,
            r.opening_ct,
            r.turnover_dt,
            r.turnover_ct,
            r.closing_dt,
            r.closing_ct,
        )
        for r in osv.rows
        if r.code in ("201", "221", "531") and not r.subconto
    }


EXPECTED = {
    "201": (140_000, 0, 15_000, 0, 155_000, 0),
    "221": (700_000, 0, 0, 15_000, 685_000, 0),
    "531": (0, 70_000, 15_000, 15_000, 0, 70_000),
}


def test_posted_documents_make_the_hand_counted_balance(demo):
    outcome = import_batch(demo.ledger, demo.company_id, parse_batch(FILE), post=True)
    assert outcome.ok and outcome.new == ["S-1", "S-2"] and not outcome.existing
    assert march(demo) == EXPECTED
    doc = load_document(demo.ledger.conn, demo.company_id, outcome.created[0][1])
    assert doc.status == "posted" and doc.memo == "materials from supplier A"


def test_the_same_file_twice_makes_no_duplicates(demo):
    first = import_batch(demo.ledger, demo.company_id, parse_batch(FILE), post=True)
    again = import_batch(demo.ledger, demo.company_id, parse_batch(FILE), post=True)
    assert again.ok and again.new == [] and again.created == []
    assert again.existing == first.created
    assert march(demo) == EXPECTED


def test_another_source_is_another_document(demo):
    import_batch(demo.ledger, demo.company_id, parse_batch(FILE), post=True)
    other = import_batch(demo.ledger, demo.company_id, parse_batch(file(source="other")), post=True)
    assert other.new == ["S-1", "S-2"]
    assert march(demo)["201"][2] == 30_000  # 150 + 150


def test_drafts_by_default_and_a_check_writes_nothing(demo):
    check = import_batch(demo.ledger, demo.company_id, parse_batch(FILE), check_only=True)
    assert check.ok and check.new == ["S-1", "S-2"] and check.created == []
    assert march(demo)["201"][2] == 0
    drafts = import_batch(demo.ledger, demo.company_id, parse_batch(FILE))
    doc = load_document(demo.ledger.conn, demo.company_id, drafts.created[1][1])
    assert doc.status == "draft"
    assert march(demo)["201"][2] == 0  # a draft is not in the books


def test_a_deleted_document_is_imported_anew(demo):
    first = import_batch(demo.ledger, demo.company_id, parse_batch(FILE))
    demo.ledger.delete_document(demo.company_id, first.created[0][1])
    again = import_batch(demo.ledger, demo.company_id, parse_batch(FILE))
    assert again.new == ["S-1"] and [e for e, _ in again.existing] == ["S-2"]


def test_names_are_exact_and_one_problem_stops_the_file(demo):
    data = file()
    data["documents"][1]["postings"][0]["debit_subconto"] = ["Поставщик"]  # A or B?
    data["documents"][0]["postings"][0]["debit"] = "20"  # no such account
    outcome = import_batch(demo.ledger, demo.company_id, parse_batch(data), post=True)
    assert [e for e, _ in outcome.errors] == ["S-1", "S-2"]
    assert "«20» не найден" in outcome.errors[0][1]
    assert "«Поставщик» нет в справочнике" in outcome.errors[1][1]
    assert march(demo)["201"][2] == 0


def test_a_ledger_rule_names_its_document(demo):
    data = file()
    data["documents"][1]["postings"][0]["amount"] = "-5.00"
    outcome = import_batch(demo.ledger, demo.company_id, parse_batch(data), post=True)
    assert [e for e, _ in outcome.errors] == ["S-2"] and outcome.created == []
    assert march(demo)["201"][2] == 0  # all or nothing


def test_an_id_twice_in_the_file_is_an_error(demo):
    data = file()
    data["documents"][1]["id"] = "S-1"
    outcome = import_batch(demo.ledger, demo.company_id, parse_batch(data))
    assert outcome.errors == [("S-1", "документ «S-1» в файле дважды")]


@pytest.mark.parametrize(
    ("data", "says"),
    [
        ({"documents": []}, "не файл документов"),
        (file(version=2), "версии 2"),
        (file(version="1"), "целое число"),
        (file(source=""), "источник"),
        (file(extra=1), "лишние поля ['extra']"),
        (file(documents=[{"date": "2026-03-02", "postings": []}]), 'нет "id"'),
        (file(documents=[{"id": "x", "date": "02.03.2026"}]), "ГГГГ-ММ-ДД"),
        (file(documents=[{"id": "x", "date": "2026-03-02", "layer": "ifrs"}]), "слой"),
    ],
)
def test_the_shape_of_the_file_is_checked(data, says):
    with pytest.raises(FormatError, match=None) as e:
        parse_batch(data)
    assert says in str(e.value)


def test_an_amount_is_text_not_a_float(demo):
    data = file()
    data["documents"][0]["postings"][0]["amount"] = 150.0
    outcome = import_batch(demo.ledger, demo.company_id, parse_batch(data))
    assert "сумма — строкой" in outcome.errors[0][1]
