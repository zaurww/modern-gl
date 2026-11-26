"""An imported e-qaimə adds up to the portal's own totals: the portal rounds the sums, the
program rounded every line — a kopeck more (the user's parallel run, SR Logistics)."""

from __future__ import annotations

from modern_gl.application.eqaime import parse_invoice


def _invoice(costs: list[object], total: object, vat: object):
    row = {
        "id": "a1",
        "serialNumber": "MT251012085245",
        "status": "approved",
        "kind": "defaultInvoice",
        "createdAt": "2025-10-27T10:00:00",
        "sender": {"tin": "1102987741", "name": "Sr Logistics And Transport MMC"},
        "amount": total,
        "vat": vat,
    }
    items = [
        {"productName": f"Xidmət {n}", "productGroup": {"code": "9967"}, "cost": c, "vat18": c}
        for n, c in enumerate(costs, 1)
    ]
    return parse_invoice(row, {**row, "items": items}, outgoing=False)


def test_the_vat_of_the_lines_is_the_portals_vat():
    """Lines 100 + 30 + 20 + 102.92 + 12.15 + 70 = 335.07. 18% by line: 18.00, 5.40, 3.60,
    18.5256 -> 18.53, 2.187 -> 2.19, 12.60 = 60.32; the portal: 335.07 x 18% = 60.3126 ->
    60.31, total 395.38. The kopeck comes off the line rounded up the most (18.5256:
    +0.0044, against +0.003 of 2.187) -> 18.52."""
    invoice = _invoice([100, 30, 20, 102.92, 12.15, 70], 395.38, 60.31)
    assert [line.vat for line in invoice.lines] == [1800, 540, 360, 1852, 219, 1260]
    assert [line.amount for line in invoice.lines] == [10000, 3000, 2000, 10292, 1215, 7000]
    assert (invoice.amount, invoice.vat) == (33507, 6031)


def test_the_amount_of_the_lines_is_the_portals_total_less_vat():
    """Lines 100 + 36.20 + 40.937 + 30 + 100 + 20 + 373.17 = 700.307, ƏDV 126.05526 ->
    126.06, total 826.36226 -> 826.36: without ƏDV 826.36 - 126.06 = 700.30, while the lines
    rounded one by one give 700.31 (40.937 -> 40.94). That line gives the kopeck back:
    40.93. ƏDV by line: 18.00 + 6.516 -> 6.52 + 7.3692 -> 7.37 + 5.40 + 18.00 + 3.60 +
    67.1706 -> 67.17 = 126.06 — as the portal, untouched."""
    invoice = _invoice([100, 36.20, "40.937", 30, 100, 20, 373.17], 826.36, 126.06)
    assert [line.amount for line in invoice.lines] == [10000, 3620, 4093, 3000, 10000, 2000, 37317]
    assert [line.vat for line in invoice.lines] == [1800, 652, 737, 540, 1800, 360, 6717]
    assert (invoice.amount, invoice.vat) == (70030, 12606)


def test_a_kopeck_short_is_added_to_the_line_rounded_down_the_most():
    """Lines 10.004 + 10.004 + 10.003 = 30.011 -> the portal: ƏDV 5.40198 -> 5.40, total
    35.41298 -> 35.41, without ƏDV 30.01; by line 10.00 x 3 = 30.00. The first of the two
    lines that lost 0.004 takes the kopeck: 10.01."""
    invoice = _invoice(["10.004", "10.004", "10.003"], 35.41, 5.40)
    assert [line.amount for line in invoice.lines] == [1001, 1000, 1000]
    assert (invoice.amount, invoice.vat) == (3001, 540)


def test_totals_that_are_not_a_rounding_are_left_alone():
    """The list says 500.00 with ƏDV 76.27, the lines 120 + 50 (ƏDV 30.60): not a rounding
    difference (more than a kopeck a line) — the lines stay as they are; the reconciliation
    shows such an e-qaimə. A row without totals: the same."""
    invoice = _invoice([120, 50], 500, 76.27)
    assert (invoice.amount, invoice.vat) == (17000, 3060)
    bare = _invoice([120, 50], None, None)
    assert (bare.amount, bare.vat) == (17000, 3060)
