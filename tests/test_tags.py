"""Tags of directory elements (D64): any number per element, a filter of ОСВ по субконто.

Golden example (conftest): on 531 «Поставщики» supplier A got 1 200.00 (Jan 10) and was
paid 1 000.00 (Jan 15); supplier B got 500.00 (Feb 3). For February 2026, by hand:
  A  opening Ct 200.00   no turnover        closing Ct 200.00
  B  opening —           turnover Ct 500.00  closing Ct 500.00
A is tagged «Связанная сторона»; B «Арендодатель» and «Связанная сторона».
"""

from __future__ import annotations

import json

import pytest
from PySide6.QtCore import Qt

from modern_gl.application.catalog import Catalog
from modern_gl.domain.errors import ValidationError
from modern_gl.reporting.reports import subconto_balance


@pytest.fixture
def tagged(demo):
    ledger, cid = demo.ledger, demo.company_id
    related = ledger.add_tag(cid, "Связанная сторона")
    landlord = ledger.add_tag(cid, "  Арендодатель ")
    ledger.set_subconto_value_tags(cid, demo.supplier_a, [related])
    ledger.set_subconto_value_tags(cid, demo.supplier_b, [landlord, related])
    return demo, related, landlord


def _feb(demo, tag_id=None):
    rows = subconto_balance(
        demo.ledger.conn,
        demo.company_id,
        demo.acc["531"],
        "2026-02-01",
        "2026-02-28",
        tag_id=tag_id,
    )
    return [
        (r.name, r.opening_dt, r.opening_ct, r.turnover_dt, r.turnover_ct, r.closing_ct)
        for r in rows
    ]


def test_osv_by_subconto_shows_only_elements_with_the_tag(tagged):
    demo, related, landlord = tagged
    a = ("Поставщик A", 0, 200_00, 0, 0, 200_00)
    b = ("Поставщик B", 0, 0, 0, 500_00, 500_00)
    assert _feb(demo) == [a, b]
    assert _feb(demo, related) == [a, b]
    assert _feb(demo, landlord) == [b]
    unused = demo.ledger.add_tag(demo.company_id, "Нерезидент")
    assert _feb(demo, unused) == []


def test_catalog_knows_the_tags_of_each_element(tagged):
    demo, related, landlord = tagged
    cat = Catalog(demo.ledger.conn, demo.company_id)
    assert cat.tags == {related: "Связанная сторона", landlord: "Арендодатель"}
    assert cat.value(demo.supplier_b).tags == {related, landlord}
    assert cat.tag_text(cat.value(demo.supplier_b)) == "Арендодатель  ·  Связанная сторона"
    kind = cat.value(demo.supplier_a).kind_id
    assert cat.kind_tags(kind) == [(landlord, "Арендодатель"), (related, "Связанная сторона")]


def test_tags_are_set_all_at_once_and_audited(tagged):
    demo, related, landlord = tagged
    ledger, cid = demo.ledger, demo.company_id
    ledger.set_subconto_value_tags(cid, demo.supplier_b, [landlord])
    assert Catalog(ledger.conn, cid).value(demo.supplier_b).tags == {landlord}
    event = ledger.conn.execute(
        "SELECT details FROM audit_events WHERE action = 'set_tags' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert sorted([related, landlord]) == json.loads(event["details"])["from"]


def test_tag_names_are_unique_whatever_the_case(tagged):
    demo, *_ = tagged
    ledger, cid = demo.ledger, demo.company_id
    with pytest.raises(ValidationError, match="уже есть"):
        ledger.add_tag(cid, "связанная СТОРОНА")
    with pytest.raises(ValidationError, match="пустым"):
        ledger.add_tag(cid, "   ")
    other = ledger.add_tag(cid, "Холдинг")
    with pytest.raises(ValidationError, match="уже есть"):
        ledger.rename_tag(cid, other, "арендодатель")
    ledger.rename_tag(cid, other, "Холдинг Х")
    assert Catalog(ledger.conn, cid).tags[other] == "Холдинг Х"


def test_deleting_a_tag_takes_it_off_every_element(tagged):
    demo, related, landlord = tagged
    ledger, cid = demo.ledger, demo.company_id
    ledger.delete_tag(cid, related)
    cat = Catalog(ledger.conn, cid)
    assert related not in cat.tags
    assert cat.value(demo.supplier_a).tags == frozenset()
    assert cat.value(demo.supplier_b).tags == {landlord}


def test_a_tag_does_not_keep_an_element_from_being_deleted(tagged):
    demo, related, _ = tagged
    ledger, cid = demo.ledger, demo.company_id
    kind = Catalog(ledger.conn, cid).value(demo.supplier_a).kind_id
    spare = ledger.add_subconto_value(cid, kind, "Ошибочный")
    ledger.set_subconto_value_tags(cid, spare, [related])
    ledger.delete_subconto_value(cid, spare)
    left = ledger.conn.execute(
        "SELECT COUNT(*) FROM subconto_value_tags WHERE value_id = ?", (spare,)
    ).fetchone()[0]
    assert left == 0


def test_a_group_has_no_tags(tagged):
    demo, related, _ = tagged
    ledger, cid = demo.ledger, demo.company_id
    kind = Catalog(ledger.conn, cid).value(demo.supplier_a).kind_id
    group = ledger.add_subconto_group(cid, kind, "Иностранные")
    with pytest.raises(ValidationError, match="группы"):
        ledger.set_subconto_value_tags(cid, group, [related])


def test_tags_of_another_company_are_refused(tagged):
    demo, related, _ = tagged
    ledger = demo.ledger
    other = ledger.create_company("Другая")
    with pytest.raises(Exception, match="не найден"):
        ledger.rename_tag(other, related, "Чужая")
    with pytest.raises(Exception, match="не найден"):
        ledger.set_subconto_value_tags(demo.company_id, demo.supplier_a, [999])


# ---- interface ---------------------------------------------------------------------


@pytest.fixture
def session(qtbot, monkeypatch):
    from PySide6.QtWidgets import QApplication, QMessageBox

    from modern_gl.application.chart_csv import apply_chart_template
    from modern_gl.application.ledger import Ledger
    from modern_gl.desktop import theme
    from modern_gl.desktop.session import Session
    from modern_gl.infrastructure.db import connect

    monkeypatch.setattr(
        QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
    )
    theme.apply(QApplication.instance())
    conn = connect(":memory:")
    ledger = Ledger(conn, actor="test")
    cid = ledger.create_company("Firma")
    apply_chart_template(ledger, cid, "classic", "ru")
    yield Session(conn, ledger, cid, "Firma", Catalog(conn, cid), notify=lambda _: None)
    conn.close()


def test_tag_is_made_in_the_counterparty_window_and_filters_the_report(session, qtbot, monkeypatch):
    """March 2026 on 60, by hand: Альфа (related) Ct 400.00 for rent, Бета Ct 1 000.00.
    With the tag the report has Альфа only and the total is Ct 400.00."""
    from datetime import date

    from PySide6.QtWidgets import QDialog, QInputDialog

    from modern_gl.application.ledger import PostingInput
    from modern_gl.desktop.directories_page import DirectoriesPage, ValueDialog
    from modern_gl.desktop.reports_page import ReportParams, SubcontoPage

    s, cid = session, session.company_id
    cp = s.ledger.subconto_kind_id(cid, "counterparty")
    contract = s.ledger.subconto_kind_id(cid, "contract")
    rent = s.ledger.add_subconto_value(cid, s.ledger.subconto_kind_id(cid, "cost_item"), "Аренда")
    alfa = s.ledger.add_subconto_value(cid, cp, "Альфа")
    beta = s.ledger.add_subconto_value(cid, cp, "Бета")
    d1 = s.ledger.add_subconto_value(cid, contract, "Д1", owner_id=alfa)
    d2 = s.ledger.add_subconto_value(cid, contract, "Д2", owner_id=beta)
    s.catalog.reload()
    acc = s.catalog.by_code
    for party, deal, amount in ((alfa, d1, "400"), (beta, d2, "1000")):
        s.ledger.post_new(
            cid,
            "2026-03-05",
            [PostingInput(acc["26"].id, acc["60"].id, amount, (rent,), (party, deal))],
        )
    s.catalog.reload()

    page = DirectoriesPage(s)
    qtbot.addWidget(page)
    page.refresh(select_kind=cp)
    monkeypatch.setattr(
        QInputDialog, "getText", staticmethod(lambda *a, **k: ("Связанная сторона", True))
    )

    def tag_it(dialog: ValueDialog) -> int:
        dialog.tags.new_tag()  # «+ Тег»: made and put on at once
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(ValueDialog, "exec", tag_it)
    page.rename_value(s.catalog.value(alfa))
    (related,) = s.catalog.tags
    assert s.catalog.value(alfa).tags == {related}
    headers = [
        page.model.headerData(c, Qt.Orientation.Horizontal) for c in range(page.model.columnCount())
    ]
    assert "Теги" in headers
    row = next(r for r in range(page.model.rowCount()) if page.model.index(r, 0).data() == "Альфа")
    assert page.model.index(row, headers.index("Теги")).data() == "Связанная сторона"

    report = SubcontoPage(s, acc["60"].id, ReportParams(date(2026, 3, 1), date(2026, 3, 31)))
    qtbot.addWidget(report)
    report.levels.setCurrentIndex(0)  # counterparties only, without their contracts
    report.refresh()
    assert not report.tag.isHidden()
    names = [report.model.index(r, 0).data() for r in range(report.model.rowCount())]
    assert names == ["Альфа", "Бета", "Итого"]
    report.tag.setCurrentIndex(report.tag.findData(related))
    report.refresh()
    names = [report.model.index(r, 0).data() for r in range(report.model.rowCount())]
    assert names == ["Альфа", "Итого"]
    total = report.model.rows[-1]
    assert (total.turnover_ct, total.closing_ct) == (400_00, 400_00)
    assert report.footer.text() == "Только с тегом «Связанная сторона»"


def test_report_has_no_tag_filter_while_nobody_has_a_tag(session, qtbot):
    from datetime import date

    from modern_gl.desktop.reports_page import ReportParams, SubcontoPage

    acc = session.catalog.by_code
    report = SubcontoPage(session, acc["60"].id, ReportParams(date(2026, 3, 1), date(2026, 3, 31)))
    qtbot.addWidget(report)
    assert report.tag.isHidden() and report.tag_label.isHidden()
