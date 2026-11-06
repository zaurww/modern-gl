"""The reports in a browser (D-new-web-reports): only reading, on this computer only.

Figures — the golden example of conftest (hand-calculated there): February 2026,
531 opening Ct 200, turnover Ct 500, closing Ct 700; total closing 10 700 / 10 700.
"""

import hashlib
import http.client
import threading
from concurrent.futures import ThreadPoolExecutor
from http.server import ThreadingHTTPServer

import pytest

from modern_gl.application.ledger import Ledger
from modern_gl.application.workspace import Workspace
from modern_gl.assistant.companies import Companies
from modern_gl.desktop.theme.palette import Palette
from modern_gl.i18n import set_language
from modern_gl.infrastructure.db import connect
from modern_gl.web.layout import COLORS, amount, esc
from modern_gl.web.server import Site, make_handler
from tests.conftest import build_demo

FEBRUARY = "from=2026-02-01&to=2026-02-28"


@pytest.fixture(autouse=True)
def russian():
    set_language("ru")
    yield
    set_language("az")


@pytest.fixture
def folder(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    conn = connect(data / "Alfa.gl")
    build_demo(Ledger(conn), "Alfa MMC")
    conn.close()
    return data


@pytest.fixture
def site(folder):
    companies = Companies(Workspace(folder))
    yield Site(companies)
    companies.close()


def test_amount_is_shown_as_in_the_reports():
    assert amount("1234567.50") == "1 234 567.50"
    assert amount("-200.00") == "(200.00)"
    assert amount("0.00") == ""
    assert amount("999.99") == "999.99"


def test_one_company_opens_at_once(site):
    reply = site.answer("/")
    assert reply.status == 302
    assert reply.location == "/c/Alfa%20MMC/osv"


def test_trial_balance_shows_the_hand_calculated_figures(site):
    reply = site.answer(f"/c/Alfa/osv?{FEBRUARY}")
    assert reply.status == 200
    row = next(r for r in reply.body.split("<tr") if ">531 " in r or "account=531" in r)
    cells = [c.split("</td>")[0] for c in row.split('<td class="num">')[1:]]
    assert cells == ["", "200.00", "", "500.00", "", "700.00"]
    total = reply.body.split('class="total"')[1]
    assert total.count("10 700.00") == 2
    assert "Дебет и кредит сходятся" in reply.body


def test_card_and_document_are_reached_from_the_report(site):
    card = site.answer(f"/c/Alfa/card?account=531&{FEBRUARY}")
    assert card.status == 200
    assert "(700.00)" in card.body  # closing: Ct 700, balance = debit − credit
    number = card.body.split("/doc/")[1].split('"')[0]
    assert site.answer(f"/c/Alfa/doc/{number}").status == 200


def test_journal_finds_nothing_for_an_unknown_word(site):
    assert "/doc/" in site.answer(f"/c/Alfa/journal?{FEBRUARY}").body
    assert "/doc/" not in site.answer(f"/c/Alfa/journal?{FEBRUARY}&q=zzzz").body


@pytest.mark.parametrize(
    ("target", "status"),
    [
        ("/nothing", 404),
        ("/c/Alfa/nothing", 404),
        ("/c/Nobody/osv", 404),
        ("/c/Alfa/card?account=000", 404),
        ("/c/Alfa/doc/99999", 404),
    ],
)
def test_a_wrong_address_is_explained(site, target, status):
    reply = site.answer(target)
    assert reply.status == status
    assert "Не удалось показать страницу" in reply.body


def test_a_wrong_period_falls_back_to_the_year(site):
    assert site.answer("/c/Alfa/osv?from=abc&to=<x>").status == 200


def test_what_the_address_says_cannot_become_markup(site):
    body = site.answer("/c/Alfa/journal?q=<script>alert(1)</script>").body
    assert "<script>alert" not in body
    assert esc("<script>") in body


def test_the_file_is_not_changed_by_reading(folder, site):
    file = folder / "Alfa.gl"
    before = hashlib.sha256(file.read_bytes()).hexdigest()
    for target in ("/", "/c/Alfa/osv", "/c/Alfa/journal", "/c/Alfa/card?account=531"):
        site.answer(target)
    assert hashlib.sha256(file.read_bytes()).hexdigest() == before


def test_colors_follow_the_palette():
    palette = Palette()
    assert {name: getattr(palette, name) for name in COLORS} == COLORS


@pytest.fixture
def port(site):
    reader = ThreadPoolExecutor(max_workers=1)
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(site, reader))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server.server_address[1]
    server.shutdown()
    server.server_close()
    reader.submit(site.companies.close).result()
    reader.shutdown()


def request(port, method="GET", host=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    conn.putrequest(method, "/c/Alfa/osv", skip_host=True)
    conn.putheader("Host", host or f"127.0.0.1:{port}")
    conn.endheaders()
    response = conn.getresponse()
    response.read()
    conn.close()
    return response


def test_pages_are_served_with_a_content_policy(port):
    response = request(port)
    assert response.status == 200
    assert "default-src 'none'" in (response.getheader("Content-Security-Policy") or "")


def test_another_host_name_is_refused(port):
    assert request(port, host=f"evil.example:{port}").status == 403


@pytest.mark.parametrize("method", ["POST", "PUT", "DELETE"])
def test_nothing_but_reading_is_answered(port, method):
    assert request(port, method).status == 501
