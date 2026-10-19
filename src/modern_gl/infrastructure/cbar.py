"""Official rates of the Central Bank of Azerbaijan (CBAR, cbar.az).

The bank publishes one XML file per day: https://www.cbar.az/currencies/DD.MM.YYYY.xml

    <ValCurs Date="17.10.2026" ...>
      <ValType Type="Bank metalları"> ... </ValType>
      <ValType Type="Xarici valyutalar">
        <Valute Code="USD"><Nominal>1</Nominal><Name>ABŞ dolları</Name><Value>1.7</Value></Valute>
        <Valute Code="JPY"><Nominal>100</Nominal><Name>Yen</Name><Value>1.13</Value></Valute>
"""

from __future__ import annotations

import re
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date

from modern_gl.domain.currency import parse_rate
from modern_gl.domain.errors import LedgerError
from modern_gl.i18n import tr

URL = "https://www.cbar.az/currencies/{day:%d.%m.%Y}.xml"
TIMEOUT = 15  # seconds
METALS = {"XAU", "XAG", "XPT", "XPD"}  # quoted per troy ounce, not currencies of payment


class RatesUnavailable(LedgerError):
    pass


def parse(xml: bytes) -> dict[str, tuple[int, int]]:
    """{code: (rate in millionths of a manat, nominal)} of the foreign currencies;
    bank metals (gold, silver…) are skipped."""
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as e:
        raise RatesUnavailable(tr("ЦБА прислал не то, что ожидалось: {error}", error=e)) from e
    rates = {}
    for valute in root.iter("Valute"):
        code = (valute.get("Code") or "").strip().upper()
        nominal_text = (valute.findtext("Nominal") or "").strip()
        value = (valute.findtext("Value") or "").strip()
        nominal = re.match(r"\d+", nominal_text)
        if len(code) != 3 or not code.isalpha() or code in METALS or not nominal:
            continue
        try:
            rates[code] = (parse_rate(value), int(nominal.group()))
        except (TypeError, ValueError):
            continue
    if not rates:
        raise RatesUnavailable(tr("в ответе ЦБА нет курсов валют"))
    return rates


def fetch(day: date) -> dict[str, tuple[int, int]]:
    """Download and parse the rates of a day. Raises RatesUnavailable with a message
    for the user when there is no connection or no rates for that day."""
    request = urllib.request.Request(URL.format(day=day), headers={"User-Agent": "Modern GL"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            body = response.read()
    except urllib.error.HTTPError as e:
        raise RatesUnavailable(
            tr("ЦБА: нет курсов на {date} ({error})", date=f"{day:%d.%m.%Y}", error=e.code)
        ) from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise RatesUnavailable(
            tr("Не удалось связаться с сайтом ЦБА (cbar.az): {error}", error=e)
        ) from e
    return parse(body)
