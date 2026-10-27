"""Shared from test_travel_agency.py (moved here: other test modules use it too)."""

from __future__ import annotations

from modern_gl.application.chart_csv import apply_chart_template
from modern_gl.application.ledger import PostingInput

JUNE = ("2026-06-01", "2026-06-30")


def make_agency(ledger):
    """The agency on the 1C 7.7 chart with «Sifarişlər» as the third subconto of 60.1,
    60.2, 62.1, 62.2 and 90.1: (company, accounts by code, elements by name, kinds by code,
    the order kind)."""
    cid = ledger.create_company("Səyahət MMC")
    apply_chart_template(ledger, cid, "1c77", "az")
    kind = {
        c: ledger.subconto_kind_id(cid, c) for c in ("counterparty", "contract", "bank_account")
    }
    order = ledger.add_subconto_kind(cid, "order", "Sifarişlər")
    for code in ("60.1", "60.2", "62.1", "62.2"):  # the advances carry the order too
        ledger.update_account(cid, code, subconto=[kind["counterparty"], kind["contract"], order])
    ledger.update_account(cid, "90.1", subconto=[order])
    acc = {c: ledger.account_id(cid, c) for c in ("51", "60.1", "62.1", "90.1")}
    v = {
        name: ledger.add_subconto_value(cid, kind["counterparty"], name)
        for name in ("Zaur", "Firma MMC", "TurOp", "Hava Yolları")
    }
    v["S-001"] = ledger.add_subconto_value(cid, order, "S-001 Zaur, Antalya")
    v["S-002"] = ledger.add_subconto_value(cid, order, "S-002 Firma MMC, bilet")
    v["bank"] = ledger.add_subconto_value(cid, kind["bank_account"], "Kapital Bank AZN")
    return cid, acc, v, kind, order


def _post_cases(ledger, agency) -> None:
    cid, acc, v, _, _ = agency
    bank = (v["bank"],)
    zaur = (v["Zaur"], None, v["S-001"])
    turop = (v["TurOp"], None, v["S-001"])
    firma = (v["Firma MMC"], None, v["S-002"])
    hava = (v["Hava Yolları"], None, v["S-002"])
    for day, dt, ct, amount, dt_sc, ct_sc in (
        ("2026-06-01", "51", "62.1", "2000", bank, zaur),
        ("2026-06-02", "62.1", "60.1", "1800", zaur, turop),
        ("2026-06-02", "62.1", "90.1", "200", zaur, (v["S-001"],)),
        ("2026-06-03", "60.1", "51", "1800", turop, bank),
        ("2026-06-05", "51", "62.1", "500", bank, firma),
        ("2026-06-06", "62.1", "60.1", "950", firma, hava),
        ("2026-06-06", "62.1", "90.1", "50", firma, (v["S-002"],)),
    ):
        ledger.post_new(cid, day, [PostingInput(acc[dt], acc[ct], amount, dt_sc, ct_sc)])
