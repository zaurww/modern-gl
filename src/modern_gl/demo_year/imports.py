"""The year demo's imports: goods from Germany in euro and from China in dollars, each
on a customs declaration, with the expenses that make their cost — duty and the customs
fee in one document, freight by quantity (in manat or in dollars), insurance in euro and,
weeks later when part is sold, the certification of the electrical goods by hand."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from modern_gl.application.inventory import LandedCostCharge, LandedCostTarget, ReceiptLine
from modern_gl.demo_year.firm import MAIN, Open, money, vat18
from modern_gl.demo_year.trade import Trade


@dataclass(frozen=True)
class Shipment:
    supplier: str  # the partner's key
    currency: str
    duty: int  # % of the customs value
    order: dict[str, int]  # product key -> quantity
    memo: str
    certified: tuple[str, ...] = ()  # electrical goods, certified later by hand


GERMANY = Shipment(
    "import",
    "EUR",
    15,
    {
        "laminator": 24,
        "shredder": 18,
        "binder": 20,
        "projector": 6,
        "cutter": 15,
        "scanner": 8,
        "labeler": 16,
        "whiteboard": 20,
        "confphone": 5,
        "safe": 4,
        "counter": 6,
        "pointer": 30,
    },
    "İdxal: ofis texnikası (Almaniya)",
    ("projector", "scanner", "confphone", "counter"),
)
CHINA = Shipment(
    "china",
    "USD",
    10,
    {
        "calculator": 400,
        "stapler": 500,
        "punch": 300,
        "ledlamp": 120,
        "usbhub": 200,
        "headset": 150,
        "webcam": 100,
        "powerstrip": 200,
        "mousepad": 600,
        "organizer": 180,
    },
    "İdxal: ofis ləvazimatı (Çin)",
    ("ledlamp", "usbhub", "headset", "webcam", "powerstrip"),
)
SHIPMENTS = {  # (month, day) of every year
    (3, 10): GERMANY,
    (4, 21): CHINA,
    (6, 9): GERMANY,
    (8, 18): CHINA,
    (9, 8): GERMANY,
    (11, 10): CHINA,
    (11, 24): GERMANY,
}
CUSTOMS_FEE = 27_500  # gömrük yığımı for a declaration, qəpik
CERTIFICATE_DAYS = 25  # the certification comes after part of the goods is sold


class Imports(Trade):
    def import_goods(self, day: date) -> None:
        """The receipt at the day's rate on the customs declaration, then its expenses."""
        shipment = SHIPMENTS[day.month, day.day]
        code = shipment.currency
        rate = self.rate(code, day)
        partner = self.partner[shipment.supplier]
        lines, cents = [], 0
        for key, qty in shipment.order.items():
            amount = qty * self.product[key].cost
            lines.append(
                ReceiptLine(
                    self.item[key], self.warehouse[MAIN], qty, None, currency_amount=money(amount)
                )
            )
            cents += amount
            self.state.stock[key, MAIN] += qty
        declaration = f"AZ{day:%y%m%d}{self.rng.randrange(1000, 9999)}"
        receipt = self.inventory.post_receipt(
            self.cid,
            day,
            lines,
            self.acc["60"],
            partner.sc,
            shipment.memo,
            currency_id=self.fx_id[code],
            currency_rate=rate,
            invoice=declaration,
            invoice_kind="customs",
        )
        loaded = self.inventory.load_document(self.cid, receipt).lines
        targets = {self._key_of(line.item_id): line.id for line in loaded}
        value = sum(line.amount for line in loaded)
        due = day + timedelta(days=partner.data.days)
        self.state.payable.append(Open(shipment.supplier, due, value, 0, declaration, cents, code))
        duty = value * shipment.duty // 100
        self._customs(day, list(targets.values()), duty, declaration, value)
        self._freight(day + timedelta(days=1), shipment, list(targets.values()))
        if code == "EUR":
            self._insurance(day + timedelta(days=1), shipment, list(targets.values()), cents)
        self.certify_later.append(
            (day + timedelta(days=CERTIFICATE_DAYS), [targets[k] for k in shipment.certified])
        )

    def _key_of(self, item_id: int | None) -> str:
        return next(key for key, item in self.item.items() if item == item_id)

    def _customs(
        self, day: date, targets: list[int], duty: int, declaration: str, value: int
    ) -> None:
        """Duty and the customs fee in one document, by value; the customs ƏDV is on the
        value with both, through account 19."""
        customs = self.partner["customs"]
        charge = {"account_id": self.acc["76"], "subconto": customs.sc}
        document = self.inventory.create_landed_cost_draft(
            self.cid,
            day,
            [LandedCostTarget(t) for t in targets],
            [
                LandedCostCharge(money(duty), cost_type_id=self.cost_type["duty"], **charge),
                LandedCostCharge(money(CUSTOMS_FEE), cost_type_id=self.cost_type["fee"], **charge),
            ],
            "value",
            f"Gömrük bəyannaməsi {declaration}",
        )
        self.inventory.post_document(self.cid, document)
        customs_vat = vat18(value + duty + CUSTOMS_FEE)
        self.ledger.post_new(
            self.cid,
            day,
            [
                self.p(
                    "19",
                    "76",
                    customs_vat,
                    [customs.id],
                    customs.sc,
                    "Gömrük ƏDV-si",
                    invoice=declaration,
                    invoice_kind="customs",
                ),
            ],
            "Gömrük bəyannaməsi üzrə ƏDV",
        )
        self.state.input_vat["customs"] += customs_vat
        self.customs_due = duty + CUSTOMS_FEE + customs_vat

    def _freight(self, day: date, shipment: Shipment, targets: list[int]) -> None:
        """Freight by quantity: a local carrier in manat for Germany, a Chinese one in
        dollars."""
        if shipment.currency == "EUR":
            amount = 95_000 + self.rng.randrange(0, 30_000)
            charge = LandedCostCharge(
                money(amount),
                self.acc["60"],
                self.partner["logistics"].sc,
                cost_type_id=self.cost_type["freight"],
            )
            self.owe(day, "logistics", amount, 0, "")
        else:
            cents = 180_000 + self.rng.randrange(0, 40_000)
            rate = self.rate("USD", day)
            charge = LandedCostCharge(
                None,
                self.acc["60"],
                self.partner["cargo"].sc,
                cost_type_id=self.cost_type["freight"],
                currency_id=self.usd_id,
                currency_rate=rate,
                currency_amount=money(cents),
            )
            manat = int((cents * rate).to_integral_value())
            due = day + timedelta(days=self.partner["cargo"].data.days)
            self.state.payable.append(Open("cargo", due, manat, 0, "", cents, "USD"))
        self._charge(day, targets, charge, "quantity", "Daşınma xərcləri")

    def _insurance(self, day: date, shipment: Shipment, targets: list[int], cents: int) -> None:
        """The supplier insures the cargo for 0.6% of the invoice, billed in euro."""
        premium = cents * 6 // 1000
        charge = LandedCostCharge(
            None,
            self.acc["60"],
            self.partner[shipment.supplier].sc,
            cost_type_id=self.cost_type["insurance"],
            currency_id=self.eur_id,
            currency_rate=self.eur_rate(day),
            currency_amount=money(premium),
        )
        manat = int((premium * self.eur_rate(day)).to_integral_value())
        due = day + timedelta(days=self.partner[shipment.supplier].data.days)
        self.state.payable.append(Open(shipment.supplier, due, manat, 0, "", premium, "EUR"))
        self._charge(day, targets, charge, "value", "Yükün sığortası")

    def certify(self, day: date) -> None:
        """The certification of the electrical goods: 45 manat a model, by hand, with
        ƏDV; part of them is sold by now, so its share goes to the cost of sales."""
        due = [targets for when, targets in self.certify_later if when == day]
        self.certify_later = [x for x in self.certify_later if x[0] != day]
        for targets in due:
            amounts = {t: 4_500 + 1_500 * n for n, t in enumerate(targets)}
            net = sum(amounts.values())
            document = self.inventory.create_landed_cost_draft(
                self.cid,
                day,
                [LandedCostTarget(t, money(a)) for t, a in amounts.items()],
                [
                    LandedCostCharge(
                        money(net),
                        self.acc["60"],
                        self.partner["standard"].sc,
                        money(vat18(net)),
                        cost_type_id=self.cost_type["certificate"],
                    )
                ],
                "manual",
                "Elektrik mallarının sertifikatlaşdırılması",
            )
            self.inventory.post_document(self.cid, document)
            self.owe(day, "standard", net, vat18(net), self.invoice_number(day))

    def _charge(
        self, day: date, targets: list[int], charge: LandedCostCharge, method: str, memo: str
    ) -> None:
        document = self.inventory.create_landed_cost_draft(
            self.cid, day, [LandedCostTarget(t) for t in targets], [charge], method, memo
        )
        self.inventory.post_document(self.cid, document)
