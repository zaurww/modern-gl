"""Headers of a pasted or imported table — one set of names and one reading of
«Субконто» for the document form, the journal import and a warehouse document
(«Долг» 14)."""

from __future__ import annotations

import pytest

from modern_gl.application.journal_import import header
from modern_gl.application.table_text import subconto_header
from modern_gl.desktop.inventory_document_page.columns import paste_columns
from modern_gl.desktop.postings import AMOUNT, CT, DT, header_columns
from modern_gl.desktop.postings.columns import INVOICE
from modern_gl.i18n import fold


@pytest.mark.parametrize(
    ("cell", "pos", "read"),
    [
        ("Субконто", 0, (None, 1)),  # of the account before it, the next one
        ("Субконто", 1, (None, 2)),
        ("Субконто Кт 2", 1, ("ct", 2)),
        ("Subkonto Dt", 3, ("dt", 1)),  # a side starts again from 1
        ("Сумма", 0, None),
    ],
)
def test_a_subconto_header(cell, pos, read):
    assert subconto_header(fold(cell), pos) == read


@pytest.mark.parametrize("invoice", ["Е-гаимя", "Номер e-qaimə", "E-qaimə"])
def test_the_form_and_the_import_know_the_same_names(invoice):
    cells = ["Дт", "Субконто", "Кт", "Субконто", "Сумма AZN", invoice]
    assert header_columns(cells) == [DT, DT + 1, CT, CT + 1, AMOUNT, INVOICE]
    assert header(cells) == {
        0: ("debit", 0),
        1: ("debit", 1),
        2: ("credit", 0),
        3: ("credit", 1),
        4: ("amount", 0),
        5: ("invoice", 0),
    }


def test_a_warehouse_document_reads_subconto_alike():
    columns = ["item", "quantity", "sc1", "sc2"]
    assert paste_columns(["Товар", "Количество", "Субконто", "Субконто"], columns) == columns
