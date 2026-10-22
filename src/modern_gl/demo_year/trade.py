"""The year demo's goods: purchases when stock runs low, an import with customs and
freight, Monday's transfer to the shop, wholesale on credit and the shop's daily sales."""

from __future__ import annotations

from datetime import date, timedelta

from modern_gl.application.inventory import (
    STANDARD_VAT_RATE,
    IssueLine,
    ReceiptLine,
    SaleLine,
    TransferLine,
)
from modern_gl.demo_year.firm import (
    CUSTOMERS,
    MAIN,
    MATERIALS,
    PRODUCTS,
    SHOP,
    YEAR,
    Firm,
    Open,
    money,
    vat18,
)

LOCAL_SUPPLIERS = ("paper", "tech", "furniture")
IMPORT_DAYS = {date(YEAR, 3, 10), date(YEAR, 6, 9), date(YEAR, 9, 8), date(YEAR, 11, 24)}
IMPORT_ORDER = {"laminator": 24, "shredder": 18}


class Trade(Firm):
    def opening_stock(self) -> None:
        """Goods on 01.01 as one opening document; their value is retained earnings."""
        lines = [
            ReceiptLine(self.item[p.key], self.warehouse[wh], qty, money(qty * p.cost))
            for p in PRODUCTS
            for wh, qty in ((MAIN, p.opening[0]), (SHOP, p.opening[1]))
            if qty
        ]
        self.inventory.post_receipt(
            self.cid,
            date(YEAR - 1, 12, 31),
            lines,
            self.acc["88"],
            (),
            "Malların ilkin qalığı",
            opening=True,
        )
        for p in PRODUCTS:
            self.state.stock[p.key, MAIN] += p.opening[0]
            self.state.stock[p.key, SHOP] += p.opening[1]

    # ---- buying -----------------------------------------------------------------------

    def restock(self, day: date) -> None:
        """A supplier is called when its goods run low, not more often than twice a week."""
        stock = self.state.stock
        for supplier in LOCAL_SUPPLIERS:
            last = self.state.last_purchase.get(supplier)
            if last is not None and (day - last).days < 4:
                continue
            low = [p for p in PRODUCTS if p.supplier == supplier and stock[p.key, MAIN] < p.reorder]
            if low:
                self.buy(day, supplier, [(p.key, p.target - stock[p.key, MAIN]) for p in low])

    def buy(self, day: date, supplier: str, wanted: list[tuple[str, int]]) -> None:
        lines, net, vat = [], 0, 0
        for key, qty in wanted:
            amount = qty * self.product[key].cost
            lines.append(
                ReceiptLine(
                    self.item[key],
                    self.warehouse[MAIN],
                    qty,
                    money(amount),
                    vat_amount=money(vat18(amount)),
                )
            )
            net, vat = net + amount, vat + vat18(amount)
            self.state.stock[key, MAIN] += qty
        self._receipt(day, supplier, lines, net, vat, "Malların alışı")

    def buy_materials(self, day: date) -> None:
        wanted = {"box": 300, "tape": 60}
        lines, net, vat = [], 0, 0
        for key, _name, price in MATERIALS:
            amount = wanted[key] * price
            lines.append(
                ReceiptLine(
                    self.material[key],
                    self.warehouse[MAIN],
                    wanted[key],
                    money(amount),
                    vat_amount=money(vat18(amount)),
                )
            )
            net, vat = net + amount, vat + vat18(amount)
            self.state.materials[key] += wanted[key]
        self._receipt(day, "paper", lines, net, vat, "Qablaşdırma materiallarının alışı")

    def _receipt(
        self, day: date, supplier: str, lines: list[ReceiptLine], net: int, vat: int, memo: str
    ) -> None:
        partner = self.partner[supplier]
        invoice = self.invoice_number(day)
        self.inventory.post_receipt(
            self.cid,
            day,
            lines,
            self.acc["60"],
            partner.sc,
            memo,
            vat_rate=STANDARD_VAT_RATE,
            invoice=invoice,
        )
        self.owe(day, supplier, net, vat, invoice)
        self.state.last_purchase[supplier] = day

    def owe(self, day: date, supplier: str, net: int, vat: int, invoice: str) -> None:
        due = day + timedelta(days=self.partner[supplier].data.days)
        self.state.payable.append(Open(supplier, due, net, vat, invoice))
        self.state.input_vat[supplier] += vat
        if invoice:
            self.state.invoices.append((False, invoice, day.isoformat(), supplier, net + vat, vat))

    def use_materials(self, day: date) -> None:
        used = {key: self.state.materials[key] * 4 // 5 for key, _, _ in MATERIALS}
        self.inventory.post_issue(
            self.cid,
            day,
            [
                IssueLine(
                    self.material[key],
                    self.warehouse[MAIN],
                    qty,
                    self.acc["44"],
                    [self.cost["Qablaşdırma"]],
                )
                for key, qty in used.items()
                if qty
            ],
            "Qablaşdırma materiallarının silinməsi",
        )
        for key, qty in used.items():
            self.state.materials[key] -= qty

    # ---- import -----------------------------------------------------------------------

    def import_goods(self, day: date) -> None:
        """Goods from Germany in euro: the receipt at the day's rate, then customs duty
        (15%) and freight on the batch, and the customs ƏDV on the declaration."""
        rate = self.eur_rate(day)
        partner = self.partner["import"]
        lines, eur = [], 0
        for key, qty in IMPORT_ORDER.items():
            cents = qty * self.product[key].cost
            lines.append(
                ReceiptLine(
                    self.item[key], self.warehouse[MAIN], qty, None, currency_amount=money(cents)
                )
            )
            eur += cents
            self.state.stock[key, MAIN] += qty
        declaration = f"AZ{day:%y%m%d}{self.rng.randrange(1000, 9999)}"
        receipt = self.inventory.post_receipt(
            self.cid,
            day,
            lines,
            self.acc["60"],
            partner.sc,
            "İdxal: ofis texnikası",
            currency_id=self.eur_id,
            currency_rate=rate,
            invoice=declaration,
            invoice_kind="customs",
        )
        value = int((eur * rate).to_integral_value())
        due = day + timedelta(days=partner.data.days)
        self.state.payable.append(Open("import", due, value, 0, declaration, eur))
        targets = [line.id for line in self.inventory.load_document(self.cid, receipt).lines]
        duty = value * 15 // 100
        customs = self.partner["customs"]
        self.inventory.post_landed_cost(
            self.cid,
            day,
            targets,
            money(duty),
            self.acc["76"],
            customs.sc,
            "Gömrük rüsumu",
            cost_type_id=self.duty_type,
        )
        freight = 95_000 + self.rng.randrange(0, 30_000)
        self.inventory.post_landed_cost(
            self.cid,
            day + timedelta(days=1),
            targets,
            money(freight),
            self.acc["60"],
            self.partner["logistics"].sc,
            "Daşınma xərcləri",
            method="quantity",
            cost_type_id=self.freight_type,
        )
        self.owe(day + timedelta(days=1), "logistics", freight, 0, "")
        customs_vat = vat18(value + duty)
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
        self.customs_due = duty + customs_vat

    # ---- selling ----------------------------------------------------------------------

    def to_shop(self, day: date) -> None:
        stock, lines = self.state.stock, []
        for p in PRODUCTS:
            qty = min(p.shop_target - stock[p.key, SHOP], stock[p.key, MAIN])
            if qty > 0:
                lines.append(
                    TransferLine(self.item[p.key], self.warehouse[MAIN], self.warehouse[SHOP], qty)
                )
                stock[p.key, MAIN] -= qty
                stock[p.key, SHOP] += qty
        if lines:
            self.inventory.post_transfer(self.cid, day, lines, "Mağazaya yerdəyişmə")

    def wholesale(self, day: date) -> None:
        """A customer's order of a few goods from the main warehouse, on credit."""
        rng, stock = self.rng, self.state.stock
        customer = rng.choice(CUSTOMERS)
        lines, net, vat = [], 0, 0
        for p in rng.sample(PRODUCTS, rng.randint(2, 4)):
            qty = min(rng.randint(*p.order), stock[p.key, MAIN])
            if qty <= 0:
                continue
            amount = qty * p.wholesale
            tax = vat18(amount)
            lines.append(
                SaleLine(self.item[p.key], self.warehouse[MAIN], qty, money(amount), money(tax))
            )
            stock[p.key, MAIN] -= qty
            net, vat = net + amount, vat + tax
        if not lines:
            return
        invoice = self.invoice_number(day)
        self.inventory.post_sale(
            self.cid,
            day,
            lines,
            self.acc["62"],
            self.partner[customer].sc,
            "Malların topdan satışı",
            vat_rate=STANDARD_VAT_RATE,
            invoice=invoice,
        )
        due = day + timedelta(days=self.partner[customer].data.days + rng.randint(-3, 5))
        self.state.receivable.append(Open(customer, due, net, vat, invoice))
        self.state.output_vat += vat
        self.state.invoices.append((True, invoice, day.isoformat(), customer, net + vat, vat))

    def retail(self, day: date) -> None:
        """The shop's day: what the till sold, and its cash."""
        rng, stock = self.rng, self.state.stock
        quiet = day.weekday() == 6 or (day.month, day.day) in ((1, 1), (1, 2), (3, 20))
        lines, total, vat = [], 0, 0
        on_shelf = [p for p in PRODUCTS if stock[p.key, SHOP] > 0]
        for p in rng.sample(on_shelf, min(len(on_shelf), 3 if quiet else rng.randint(4, 7))):
            qty = min(rng.randint(1, 6 if p.retail < 1000 else 2), stock[p.key, SHOP])
            if qty <= 0:
                continue
            amount = qty * p.retail
            tax = vat18(amount)
            lines.append(
                SaleLine(self.item[p.key], self.warehouse[SHOP], qty, money(amount), money(tax))
            )
            stock[p.key, SHOP] -= qty
            total, vat = total + amount + tax, vat + tax
        if not lines:
            return
        retail = self.partner["retail"]
        self.inventory.post_sale(
            self.cid,
            day,
            lines,
            self.acc["62"],
            retail.sc,
            "Pərakəndə satış (kassa)",
            vat_rate=STANDARD_VAT_RATE,
        )
        self.ledger.post_new(
            self.cid,
            day,
            [self.p("50", "62", total, (), retail.sc, "Kassa çekləri üzrə")],
            "Kassaya mədaxil: pərakəndə satış",
        )
        self.state.cash += total
        self.state.output_vat += vat
