"""The year demo's company: its chart, directories, stock catalogue, exchange rates and
what the simulation knows of its money and stock between the days."""

from __future__ import annotations

import random
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from modern_gl.application.chart_csv import apply_chart_template
from modern_gl.application.inventory import Inventory
from modern_gl.application.ledger import Ledger, PostingInput
from modern_gl.domain.currency import parse_rate
from modern_gl.domain.money import from_minor

YEAR = 2026
MAIN, SHOP = "main", "shop"  # the warehouses


def money(minor: int) -> Decimal:
    """Qəpik (or euro cents) as the amount the use cases take."""
    return from_minor(minor)


def vat18(minor: int) -> int:
    return (minor * 18 + 50) // 100


def workday(year: int, month: int, day: int) -> date:
    """The day itself, or the Monday after it when it falls on a weekend."""
    d = date(year, month, day)
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


def last_day(year: int, month: int) -> date:
    return (date(year + month // 12, month % 12 + 1, 1)) - timedelta(days=1)


def last_workday(year: int, month: int) -> date:
    d = last_day(year, month)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


@dataclass(frozen=True)
class Product:
    """A good of the shop; prices in qəpik without ƏDV (an import's cost is in euro cents)."""

    key: str
    name: str
    cost: int
    wholesale: int
    retail: int
    supplier: str
    reorder: int  # the main warehouse buys when it has less
    target: int
    shop_target: int  # Monday's transfer fills the shop up to this
    order: tuple[int, int]  # a wholesale order's quantity
    opening: tuple[int, int] = (0, 0)  # main, shop on 01.01


# fmt: off
PRODUCTS = (
    # key, name, cost, wholesale, retail, supplier,
    #     reorder, target, shop target, wholesale order, opening (main, shop)
    Product("paper", "Kağız A4 (500 vərəq)", 650, 900, 1050, "paper",
            750, 2200, 80, (50, 200), (1500, 60)),
    Product("pens", "Qələm dəsti (10 əd.)", 320, 480, 590, "paper",
            400, 1100, 40, (25, 100), (750, 30)),
    Product("folders", "Qovluq-reyestr", 210, 320, 390, "paper",
            500, 1500, 60, (50, 150), (1000, 40)),
    Product("toner", "Printer kartrici 85A", 3800, 5200, 5900, "tech",
            100, 300, 10, (5, 25), (200, 8)),
    Product("monitor", 'Monitor 24"', 21000, 28500, 31900, "tech",
            25, 75, 4, (2, 10), (50, 3)),
    Product("keyboard", "Klaviatura və siçan dəsti", 2400, 3400, 3900, "tech",
            60, 180, 8, (5, 20), (100, 6)),
    Product("chair", "Ofis kreslosu", 14500, 19900, 22900, "furniture",
            20, 60, 3, (2, 12), (40, 2)),
    Product("lamp", "Masa lampası", 2800, 4100, 4700, "furniture",
            40, 110, 6, (5, 15), (60, 5)),
    # imported: the cost is in euro cents (Germany) or dollar cents (China)
    Product("laminator", "Laminator A3", 8500, 23000, 26500, "import", 0, 0, 3, (1, 4)),
    Product("shredder", "Kağız doğrayan", 12000, 32000, 36900, "import", 0, 0, 2, (1, 3)),
    Product("binder", "Spiral cildləmə aparatı", 6400, 17500, 19900, "import", 0, 0, 2, (1, 3)),
    Product("projector", "Proyektor Full HD", 38000, 98000, 112000, "import", 0, 0, 1, (1, 2)),
    Product("cutter", "Kağız kəsən gilyotin A3", 5200, 14500, 16900, "import", 0, 0, 2, (1, 3)),
    Product("scanner", "Sənəd skaneri", 21000, 56000, 63900, "import", 0, 0, 1, (1, 2)),
    Product("labeler", "Etiket printeri", 7400, 19500, 22900, "import", 0, 0, 2, (1, 4)),
    Product("whiteboard", "Maqnit lövhə 120×90", 4300, 11900, 13900, "import", 0, 0, 2, (1, 4)),
    Product("confphone", "Konfrans telefonu", 26500, 69000, 78900, "import", 0, 0, 1, (1, 2)),
    Product("safe", "Ofis seyfi", 31000, 82000, 93900, "import", 0, 0, 1, (1, 2)),
    Product("counter", "Əskinas sayan aparat", 14500, 38500, 43900, "import", 0, 0, 1, (1, 2)),
    Product("pointer", "Prezentasiya pultu", 2900, 7900, 9200, "import", 0, 0, 3, (2, 6)),
    Product("calculator", "Kalkulyator 12 rəqəmli", 450, 1500, 1790, "china",
            0, 0, 20, (10, 40)),
    Product("stapler", "Stepler 24/6", 280, 950, 1150, "china", 0, 0, 20, (10, 40)),
    Product("punch", "Deşikaçan", 350, 1150, 1350, "china", 0, 0, 15, (10, 30)),
    Product("ledlamp", "LED masa lampası", 1200, 3600, 4200, "china", 0, 0, 6, (3, 12)),
    Product("usbhub", "USB hub 4 port", 650, 2000, 2400, "china", 0, 0, 10, (5, 20)),
    Product("headset", "Qulaqlıq mikrofonla", 1500, 4400, 5200, "china", 0, 0, 6, (3, 12)),
    Product("webcam", "Veb-kamera Full HD", 2200, 6400, 7500, "china", 0, 0, 5, (3, 10)),
    Product("powerstrip", "Uzadıcı 5 rozetka", 800, 2400, 2900, "china", 0, 0, 10, (5, 20)),
    Product("mousepad", "Siçan altlığı", 120, 450, 590, "china", 0, 0, 25, (20, 60)),
    Product("organizer", "Masaüstü orqanayzer", 520, 1600, 1900, "china", 0, 0, 10, (5, 20)),
)
# fmt: on
MATERIALS = (("box", "Karton qutu", 45), ("tape", "Qablaşdırma lenti", 180))


@dataclass(frozen=True)
class PartnerData:
    key: str
    name: str
    tin: str | None
    contract: str
    days: int = 0  # when it pays or is paid: days after the invoice


PARTNERS = (
    PartnerData("paper", "Kağız Dünyası MMC", "1402785361", "Tədarük müqaviləsi №12", 14),
    PartnerData("tech", "Texnoplus MMC", "1700394521", "Tədarük müqaviləsi №7-T", 21),
    PartnerData("furniture", "Mebel Evi MMC", "2001437819", "Müqavilə №M-25/3", 14),
    PartnerData("import", "Büro Handel GmbH", None, "Contract BH-2026/01", 30),
    PartnerData("china", "Shenzhen Bright Office Co., Ltd", None, "Contract SBO-2026/07", 30),
    PartnerData("cargo", "Silk Road Cargo LLC", None, "Freight contract SRC-114", 15),
    PartnerData(
        "standard", "AzStandart Sertifikat MMC", "1404771205", "Xidmət müqaviləsi №S-9", 10
    ),
    PartnerData("logistics", "Baku Logistics MMC", "1503962274", "Daşınma müqaviləsi №4", 10),
    PartnerData("customs", "Dövlət Gömrük Komitəsi", "1500173341", "Gömrük ödənişləri"),
    PartnerData("landlord", "Gəncə Plaza MMC", "1300577412", "İcarə müqaviləsi №2/2025"),
    PartnerData("power", "Şəhər Enerji MMC", "9900112233", "Abonent №558120"),
    PartnerData("net", "NetLine MMC", "1601248830", "Rabitə xidmətləri №311"),
    PartnerData("cars", "Avto Mərkəz MMC", "1801654470", "Alqı-satqı №AV-118", 7),
    PartnerData("absheron", "Abşeron Holdinq MMC", "1200456718", "Satış müqaviləsi №S-01", 20),
    PartnerData("gilan", "Gilan Servis MMC", "1302889145", "Satış müqaviləsi №S-02", 12),
    PartnerData("neft", "Neft Mühəndislik MMC", "1700223906", "Satış müqaviləsi №S-03", 30),
    PartnerData("sumqayit", "Sumqayıt Kimya MMC", "2900341177", "Satış müqaviləsi №S-04", 25),
    PartnerData("retail", "Pərakəndə alıcılar", None, "Pərakəndə satış"),
    PartnerData("bank", "Kapital Bank ASC", "9900003611", "Kredit müqaviləsi №KR-0226"),
    PartnerData("founder", "Əliyev Rəşad", None, "Təsisçi"),
)
CUSTOMERS = ("absheron", "gilan", "neft", "sumqayit")
# gross salary in qəpik, and the expense account it goes to
EMPLOYEES = (
    ("Məmmədov Rəşid", 850_000, "26"),
    ("Hüseynova Leyla", 180_000, "26"),
    ("Quliyev Elvin", 110_000, "44"),
    ("Kərimova Aynur", 90_000, "44"),
    ("Babayev Tural", 100_000, "44"),
)
COST_ITEMS = (
    "İcarə",
    "Kommunal xərclər",
    "Rabitə",
    "Əmək haqqı",
    "Sosial sığorta",
    "Amortizasiya",
    "Qablaşdırma",
    "Ezamiyyə və nəqliyyat",
)


@dataclass
class Partner:
    id: int
    contract: int
    data: PartnerData

    @property
    def sc(self) -> tuple[int, int]:
        return self.id, self.contract


@dataclass
class Open:
    """An invoice not yet paid: by a customer, or to a supplier."""

    partner: str
    due: date
    net: int
    vat: int
    invoice: str = ""
    fx: int = 0  # a supplier's invoice in a currency: the amount in cents
    fx_code: str = "EUR"


@dataclass
class State:
    """What the simulation keeps in mind: money, stock and what is owed."""

    bank: int = 0  # 51, qəpik
    deposit: int = 0  # 54, the ƏDV deposit account
    cash: int = 0  # 50
    fx: dict[str, int] = field(default_factory=lambda: defaultdict(int))  # 52, cents
    stock: dict[tuple[str, str], int] = field(default_factory=lambda: defaultdict(int))
    materials: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    receivable: list[Open] = field(default_factory=list)
    payable: list[Open] = field(default_factory=list)
    input_vat: dict[str, int] = field(default_factory=lambda: defaultdict(int))  # this month
    output_vat: int = 0  # this month
    vat_due: int = 0  # 68.2 to pay on the 20th
    social_due: int = 0  # 69
    income_tax_due: int = 0  # 68.1
    salaries_due: dict[str, int] = field(default_factory=dict)  # 70, net of withholdings
    loan: int = 0  # 90
    last_purchase: dict[str, date] = field(default_factory=dict)
    invoices: list[tuple[bool, str, str, str, int, int]] = field(default_factory=list)


class Accounts(dict[str, int]):
    """Account ids by code, looked up on first use."""

    def __init__(self, ledger: Ledger, company_id: int) -> None:
        super().__init__()
        self.ledger, self.company_id = ledger, company_id

    def __missing__(self, code: str) -> int:
        self[code] = self.ledger.account_id(self.company_id, code)
        return self[code]


class Firm:
    """The company, its directories and catalogue; `p` builds a posting by account codes."""

    def __init__(self, ledger: Ledger, name: str, years: tuple[int, ...] = (YEAR,)) -> None:
        self.ledger = ledger
        self.years = years
        self.first, self.last = years[0], years[-1]
        self.rng = random.Random(YEAR)
        self.cid = cid = ledger.create_company(name)
        apply_chart_template(ledger, cid, "classic", "az")
        ledger.set_parallel_books(cid, True)
        self.inventory = Inventory(ledger.conn, actor=ledger.actor)
        self.acc = Accounts(ledger, cid)
        self.state = State()
        self.customs_due = 0  # the import's duty and ƏDV, paid the same day
        self.certify_later: list[tuple[date, list[int]]] = []  # when, the receipt lines
        self.eur_id = ledger.currency_id(cid, "EUR")
        self.usd_id = ledger.currency_id(cid, "USD")
        self.eur_rates: dict[date, Decimal] = {}
        self._rates()
        self._directories()
        self._catalogue()

    def value(self, kind: str, name: str, owner: int | None = None) -> int:
        kind_id = self.ledger.subconto_kind_id(self.cid, kind)
        return self.ledger.add_subconto_value(self.cid, kind_id, name, owner_id=owner)

    def p(
        self, dt: str, ct: str, amount: int, dt_sc=(), ct_sc=(), memo: str = "", **more
    ) -> PostingInput:
        return PostingInput(self.acc[dt], self.acc[ct], money(amount), dt_sc, ct_sc, memo, **more)

    def rate(self, code: str, day: date) -> Decimal:
        return self.eur_rate(day) if code == "EUR" else Decimal("1.7")

    def eur_rate(self, day: date) -> Decimal:
        """The Central Bank's rate of the day (a weekend has Friday's)."""
        while day not in self.eur_rates:
            day -= timedelta(days=1)
        return self.eur_rates[day]

    def invoice_number(self, day: date) -> str:
        return f"MT{day:%y%m}{self.rng.randrange(100_000, 999_999)}"

    def _rates(self) -> None:
        """Rates of every working day: the dollar is pegged, the euro wanders."""
        rate = Decimal("1.9850")
        day = date(self.first - 1, 12, 31)
        while day.year <= self.last:
            if day.weekday() < 5:
                step = Decimal(self.rng.randint(-60, 62)) / 10_000
                rate = min(max(rate + step, Decimal("1.9000")), Decimal("2.0800"))
                self.eur_rates[day] = rate
                self.ledger.set_rate(self.cid, self.eur_id, day, parse_rate(rate), source="cbar")
                self.ledger.set_rate(self.cid, self.usd_id, day, parse_rate("1.7"), source="cbar")
            day += timedelta(days=1)

    def _directories(self) -> None:
        led, cid = self.ledger, self.cid
        self.partner: dict[str, Partner] = {}
        for data in PARTNERS:
            pid = self.value("counterparty", data.name)
            contract = self.value("contract", data.contract, pid)
            if data.tin:
                led.set_subconto_value_tax(cid, pid, data.tin)
            self.partner[data.key] = Partner(pid, contract, data)
        led.set_subconto_value_tax(
            cid, self.partner["import"].id, "DE318726405", nonresident=True, country="DE"
        )
        led.set_subconto_value_currency(cid, self.partner["import"].contract, self.eur_id)
        for key, tin, country in (("china", "91440300MA5F", "CN"), ("cargo", "SRC0114", "CN")):
            led.set_subconto_value_tax(
                cid, self.partner[key].id, tin, nonresident=True, country=country
            )
            led.set_subconto_value_currency(cid, self.partner[key].contract, self.usd_id)
        related, landlords = led.add_tag(cid, "Əlaqəli tərəf"), led.add_tag(cid, "İcarəyə verən")
        led.set_subconto_value_tags(cid, self.partner["founder"].id, [related])
        led.set_subconto_value_tags(cid, self.partner["landlord"].id, [landlords])
        self.bank_azn = self.value("bank_account", "Kapital Bank AZN")
        self.bank_eur = self.value("bank_account", "Kapital Bank EUR")
        led.set_subconto_value_currency(cid, self.bank_eur, self.eur_id)
        self.bank_usd = self.value("bank_account", "Kapital Bank USD")
        led.set_subconto_value_currency(cid, self.bank_usd, self.usd_id)
        self.fx_id = {"EUR": self.eur_id, "USD": self.usd_id}
        self.fx_bank = {"EUR": self.bank_eur, "USD": self.bank_usd}
        self.deposit = self.value("bank_account", "ƏDV depozit hesabı")
        self.cost = {name: self.value("cost_item", name) for name in COST_ITEMS}
        self.employee = {name: self.value("employee", name) for name, _, _ in EMPLOYEES}
        self.asset = {
            name: self.value("fixed_asset", name)
            for name in ("Ofis kompüterləri", "Anbar rəfləri", "Ford Transit furqon")
        }

    def _catalogue(self) -> None:
        inv, cid = self.inventory, self.cid
        pieces = inv.add_unit(cid, "əd.", "ədəd", precision=0)
        packs = inv.add_unit(cid, "paç.", "paçka", precision=0)
        self.warehouse = {
            MAIN: inv.add_warehouse(cid, "Mərkəzi anbar"),
            SHOP: inv.add_warehouse(cid, "Nizami mağazası"),
        }
        self.item = {
            p.key: inv.add_item(cid, p.name, packs if p.key == "paper" else pieces, self.acc["41"])
            for p in PRODUCTS
        }
        self.product = {p.key: p for p in PRODUCTS}
        self.material = {
            key: inv.add_item(cid, name, pieces, self.acc["10"]) for key, name, _ in MATERIALS
        }
        self.cost_type = {
            key: inv.add_landed_cost_type(cid, name, code)
            for key, name, code in (
                ("duty", "Gömrük rüsumu", "DUTY"),
                ("fee", "Gömrük yığımı", "FEE"),
                ("freight", "Daşınma", "FREIGHT"),
                ("insurance", "Sığorta", "INSUR"),
                ("certificate", "Sertifikatlaşdırma", "CERT"),
            )
        }
