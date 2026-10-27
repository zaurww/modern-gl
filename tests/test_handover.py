"""Handing a company over (D81): the zip of plain-text files. Figures — the golden example
of conftest, ОСВ for 2026 (hand-calculated there): turnovers 15 000.00, closing 10 700.00."""

from __future__ import annotations

import re
import zipfile

import pytest

from modern_gl.reporting.handover import handover_files, write_handover
from modern_gl.reporting.plaintext import hledger_journal
from tests.helpers.currency import post_example


@pytest.fixture
def books(currency_books):
    return currency_books


@pytest.fixture
def window(desktop_window):
    return desktop_window


def test_package_of_a_company_without_parallel_books(demo):
    led, cid = demo.ledger, demo.company_id
    led.set_subconto_value_tax(cid, demo.supplier_a, "1234567890")
    files = handover_files(led.conn, cid, "2026-10-22")
    assert list(files) == ["README.txt", "common.journal", "osv-common.txt", "directories.csv"]
    assert files["common.journal"] == hledger_journal(
        led.conn, cid, "2026-10-22", ("common",), "2026-10-22"
    )
    readme = files["README.txt"]
    assert readme.startswith("ООО Тест\nПередача дел — выгружено 2026-10-22 из Modern GL\n")
    assert "Проведённых документов: 6, с 2026-01-05 по 2026-02-20" in readme
    assert "  osv-common.txt    ОСВ с 2026-01-01 по 2026-10-22 — книга «Общий учёт»" in readme
    assert "Контрагенты;;Поставщик A;;1234567890;;;да" in files["directories.csv"]


def test_osv_text_has_the_hand_calculated_figures(demo):
    osv = handover_files(demo.ledger.conn, demo.company_id, "2026-10-22")["osv-common.txt"]
    lines = osv.splitlines()
    assert lines[0] == "Оборотно-сальдовая ведомость с 2026-01-01 по 2026-10-22"
    cells = {}  # columns are at least two spaces apart; "1 000.00" keeps its single space
    for line in lines[5:]:
        if not line.startswith("-"):
            label, *figures = re.split(r"\s{2,}", line.strip())
            cells[label] = figures
    assert cells["531 Поставщики"] == ["—", "—", "1 000.00", "1 700.00", "—", "700.00"]
    assert cells["221 Банк 1"] == ["—", "—", "10 000.00", "3 000.00", "7 000.00", "—"]
    assert cells["Итого"] == ["—", "—", "15 000.00", "15 000.00", "10 700.00", "10 700.00"]


def test_later_documents_are_included_and_set_the_year(demo):
    led, cid = demo.ledger, demo.company_id
    led.post_new(cid, "2027-01-10", [demo.p("721", "221", "5.00")])
    files = handover_files(led.conn, cid, "2026-10-22")
    assert "2027-01-10 (7)" in files["common.journal"]
    assert files["osv-common.txt"].startswith(
        "Оборотно-сальдовая ведомость с 2027-01-01 по 2027-01-10"
    )


def test_parallel_books_and_rates(ledger, books):
    cid = books[0]
    post_example(ledger, books)
    ledger.set_parallel_books(cid, True)
    files = handover_files(ledger.conn, cid, "2026-10-22")
    assert {"ifrs.journal", "osv-ifrs.txt", "tax.journal", "osv-tax.txt"} <= set(files)
    assert files["rates.journal"].splitlines()[1:] == [
        "P 2026-03-01 USD 1.7000 AZN",
        "P 2026-03-20 USD 1.7100 AZN",
        "P 2026-03-31 USD 1.7200 AZN",
    ]


def test_zip_is_written_whole(tmp_path):
    path = tmp_path / "Firma — передача дел 2026-10-22.zip"
    write_handover(path, {"README.txt": "привет\n", "directories.csv": "Вид;Код\n"})
    with zipfile.ZipFile(path) as z:
        assert z.namelist() == [
            "Firma — передача дел 2026-10-22/README.txt",
            "Firma — передача дел 2026-10-22/directories.csv",
        ]
        assert z.read("Firma — передача дел 2026-10-22/README.txt").decode() == "привет\n"
        # the BOM lets Excel open the directories in UTF-8
        assert z.read("Firma — передача дел 2026-10-22/directories.csv").startswith(b"\xef\xbb\xbf")
    assert [p.name for p in tmp_path.iterdir()] == [path.name]  # no .part left behind


def test_window_hands_the_company_over(window, tmp_path, monkeypatch):
    target = tmp_path / "out.zip"
    offered = []
    monkeypatch.setattr(
        "modern_gl.desktop.main_window.company_files.QFileDialog.getSaveFileName",
        staticmethod(lambda _w, _t, path, _f: (offered.append(path) or str(target), "")),
    )
    window.hand_over()
    assert offered[0].endswith(".zip") and "передача дел" in offered[0]
    with zipfile.ZipFile(target) as z:
        names = {n.split("/", 1)[1] for n in z.namelist()}
    assert {"README.txt", "common.journal", "osv-common.txt", "directories.csv"} <= names
