import pytest

from modern_gl.application.catalog import Catalog
from modern_gl.infrastructure.chart_csv import apply_chart_template


@pytest.fixture
def catalog(ledger, conn):
    cid = ledger.create_company("Каталог")
    apply_chart_template(ledger, cid, "1c77")
    cp = ledger.subconto_kind_id(cid, "counterparty")
    ledger.add_subconto_value(cid, cp, "Альфа Трейд")
    ledger.add_subconto_value(cid, cp, "Альфа Строй")
    ledger.add_subconto_value(cid, cp, "Бета")
    return Catalog(conn, cid)


@pytest.mark.parametrize(
    ("text", "code"),
    [
        ("60.1", "60.1"),
        ("60.1  Расчёты с поставщиками", "60.1"),
        ("касса", "50"),
        ("  51 ", "51"),
        ("Уставный", "80"),
    ],
)
def test_resolve_account(catalog, text, code):
    assert catalog.resolve_account(text).code == code


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("60", "группа, выберите субсчёт: 60.1, 60.2"),
        ("расчёты", "нескольким"),
        ("xyz", "не найден"),
        ("", "не указан"),
    ],
)
def test_resolve_account_errors(catalog, text, message):
    with pytest.raises(LookupError, match=message):
        catalog.resolve_account(text)


def test_resolve_value(catalog):
    cp = next(k for k, name in catalog.kinds.items() if name == "Контрагенты")
    assert catalog.value(catalog.resolve_value(cp, "бета")).name == "Бета"
    assert catalog.value(catalog.resolve_value(cp, "Альфа Трейд")).name == "Альфа Трейд"
    assert catalog.value(catalog.resolve_value(cp, "строй")).name == "Альфа Строй"
    assert catalog.resolve_value(cp, "Гамма") is None
    with pytest.raises(LookupError, match="нескольким"):
        catalog.resolve_value(cp, "альфа")


def test_used_positions(catalog):
    assert catalog.used_positions() == {1, 2}
