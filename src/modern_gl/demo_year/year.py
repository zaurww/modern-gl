"""The year demo's calendar: what happens on each day of the year, the monthly services
posted in bulk, the van, the parallel books, a storno, the e-qaimə portal and what is left
as drafts."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from dataclasses import replace
from datetime import date, timedelta

from modern_gl.application.bank import OTHER, OUT, SALARY, BankLine, BankOperationInput
from modern_gl.application.inventory import STANDARD_VAT_RATE, ReceiptLine, SaleLine
from modern_gl.application.trade_batch import post_drafts
from modern_gl.demo_year.firm import (
    last_day,
    last_workday,
    money,
    vat18,
    workday,
)
from modern_gl.demo_year.imports import CERTIFICATE_DAYS, SHIPMENTS, Imports
from modern_gl.demo_year.money import Money
from modern_gl.domain.eqaime import PortalInvoice

# monthly services: supplier, what (the line's memo), amount, account and cost item
SERVICES = (
    ("landlord", "Ofisin və mağazanın icarəsi", 250_000, "26", "İcarə"),
    ("net", "İnternet və telefon", 12_000, "26", "Rabitə"),
    ("power", "Elektrik enerjisi", 0, "44", "Kommunal xərclər"),
)
VAN = 4_200_000


class Year(Imports, Money):
    def run(self) -> None:
        self.opening_balances()
        self.opening_stock()
        plan = self.plan()
        day = date(self.first, 1, 1)
        while day.year <= self.last:
            for event in plan.get(day, ()):
                event(day)
            self.day(day)
            day += timedelta(days=1)
        self.after_the_year()

    def plan(self) -> dict[date, list[Callable[[date], None]]]:
        """What happens on a date of the years besides the everyday trade, in that order.
        The loan and the van are taken once; the loan is repaid until it is paid off."""
        plan: dict[date, list[Callable[[date], None]]] = defaultdict(list)
        plan[date(self.first, 2, 3)].append(self.take_loan)
        plan[date(self.first, 4, 14)].append(self.buy_van)
        plan[date(self.first, 4, 20)].append(self.van_in_use)
        for y in self.years:
            self.plan_year(plan, y)
        return plan

    def plan_year(self, plan: dict[date, list[Callable[[date], None]]], y: int) -> None:
        for d in (date(y, m, n) for m, n in SHIPMENTS):
            plan[d] += [self.import_goods, self.pay_customs]
            plan[d + timedelta(days=CERTIFICATE_DAYS)].append(self.certify)
        plan[date(y, 7, 15)].append(self.mistake)
        for m in range(1, 13):
            plan[workday(y, m, 2)].append(self.services)
            if m == 1 or m % 3 == 0:
                plan[workday(y, m, 2)].append(self.buy_materials)
            if m > 2 or y > self.first:
                plan[workday(y, m, 3)].append(self.repay_loan)
            plan[workday(y, m, 5)].append(self.pay_salaries)
            plan[workday(y, m, 10)].append(self.use_materials)
            plan[workday(y, m, 15)].append(self.advance)
            if m in (4, 7, 10):
                plan[workday(y, m, 15)].append(self.pay_profit_tax)
            plan[workday(y, m, 18)].append(self.advance_report)
            plan[workday(y, m, 20)].append(self.pay_taxes)

    def day(self, d: date) -> None:
        """Every day: the shop; on working days also the warehouse, wholesale and the bank."""
        if d.weekday() < 5:
            self.restock(d)
            if d.weekday() == 0:
                self.to_shop(d)
            for _ in range(2):
                if self.rng.random() < 0.8:
                    self.wholesale(d)
            self.collect(d)
            self.pay_suppliers(d)
        self.retail(d)
        if d.weekday() == 4:
            self.deposit_cash(d)
        if d == last_workday(d.year, d.month):
            self.bank_fee(d)
        if d == last_day(d.year, d.month):
            self.month_end(d)

    def month_end(self, d: date) -> None:
        self.payroll(d)
        self.depreciation(d)
        self.offset_vat(d)
        self.ledger.revalue(self.cid, d, self.acc["80"])
        self.close_expenses(d)
        self.sales_result(d)
        if d.month % 3 == 0:
            self.adjustments(d)
        if d.month == 12:
            self.close_year(d)

    # ---- services, bought every month and posted in bulk (D73) ------------------------

    def services(self, d: date) -> None:
        """Rent, internet and the electricity of the month before: drafts from the
        e-qaimə, posted at once; after the first January the expense account is filled like last
        time. The electricity is the previous month's expense (D65)."""
        drafts = []
        for supplier, what, amount, account, item in SERVICES:
            first = (d.year, d.month) == (self.first, 1)
            if supplier == "power":
                if first:
                    continue
                amount = 30_000 + self.rng.randrange(0, 30_000)
            known = first or (supplier == "power" and (d.year, d.month) == (self.first, 2))
            line = ReceiptLine(
                None,
                None,
                None,
                money(amount),
                what,
                vat_amount=money(vat18(amount)),
                expense_account_id=self.acc[account] if known else None,
                expense_subconto=[self.cost[item]] if known else (),
                expense_date=d - timedelta(days=d.day) if supplier == "power" else None,
            )
            invoice = self.invoice_number(d)
            drafts.append(
                self.inventory.create_receipt_draft(
                    self.cid,
                    d,
                    [line],
                    self.acc["60"],
                    self.partner[supplier].sc,
                    what,
                    vat_rate=STANDARD_VAT_RATE,
                    invoice=invoice,
                )
            )
            self.owe(d + timedelta(days=7), supplier, amount, vat18(amount), invoice)
        result = post_drafts(self.inventory, self.cid, drafts)
        if result.failed:
            raise RuntimeError(result.failed)

    # ---- the van and the depreciation -------------------------------------------------

    def buy_van(self, d: date) -> None:
        van = self.asset["Ford Transit furqon"]
        line = ReceiptLine(
            None,
            None,
            None,
            money(VAN),
            "Ford Transit furqon",
            vat_amount=money(vat18(VAN)),
            expense_account_id=self.acc["08"],
            expense_subconto=[van],
        )
        self._receipt(d, "cars", [line], VAN, vat18(VAN), "Avtomobilin alışı")

    def van_in_use(self, d: date) -> None:
        van = self.asset["Ford Transit furqon"]
        self.ledger.post_new(
            self.cid,
            d,
            [self.p("01", "08", VAN, [van], [van])],
            "Əsas vəsaitin istismara verilməsi",
        )

    def depreciation(self, d: date) -> None:
        monthly = {"Ofis kompüterləri": 33_333, "Anbar rəfləri": 13_333}
        if d.month > 4 or d.year > self.first:
            monthly["Ford Transit furqon"] = VAN // 60
        cost = [self.cost["Amortizasiya"]]
        self.ledger.post_new(
            self.cid,
            d,
            [self.p("26", "02", a, cost, [self.asset[n]], n) for n, a in monthly.items()],
            "Amortizasiyanın hesablanması",
        )

    def pay_customs(self, d: date) -> None:
        self.bank_op(
            d,
            OUT,
            OTHER,
            [BankLine(self.acc["76"], self.customs_due, self.partner["customs"].sc)],
            "Gömrük rüsumu və ƏDV",
        )
        self.state.bank -= self.customs_due

    # ---- parallel books (D63) and a correction -----------------------------------------

    def adjustments(self, d: date) -> None:
        """IFRS: the computers wear out faster than the books say; tax: the van is
        depreciated at the tax rate of 25% a year instead of 20%."""
        cost = [self.cost["Amortizasiya"]]
        computers = [self.asset["Ofis kompüterləri"]]
        self.ledger.post_new(
            self.cid,
            d,
            [self.p("26", "02", 30_000, cost, computers)],
            "MHBS: kompüterlərin faydalı istifadə müddətinin dəyişməsi",
            layer="ifrs_adj",
        )
        months = min(3, d.month - 4 + 12 * (d.year - self.first))
        if months > 0:
            self.ledger.post_new(
                self.cid,
                d,
                [
                    self.p(
                        "26", "02", months * VAN // 240, cost, [self.asset["Ford Transit furqon"]]
                    )
                ],
                "Vergi uçotu: furqonun amortizasiyası 25%",
                layer="tax_adj",
            )

    def mistake(self, d: date) -> None:
        """The internet bill entered twice by hand, and its storno the next day."""
        net = self.partner["net"].sc
        wrong = self.ledger.post_new(
            self.cid,
            d,
            [self.p("26", "60", 14_160, [self.cost["Rabitə"]], net)],
            "İnternet və telefon (təkrar daxil edilib)",
        )
        self.ledger.reverse(
            self.cid, wrong, d + timedelta(days=1), "Səhv daxil edilmiş sənədin stornosu"
        )

    # ---- after the year ---------------------------------------------------------------

    def after_the_year(self) -> None:
        self.drafts()
        self.portal()
        self.ledger.set_closed_through(self.cid, date(self.last, 6, 30))

    def drafts(self) -> None:
        """What the accountant has started but not posted on 31.12."""
        d = date(self.last, 12, 31)
        founder = self.partner["founder"]
        self.ledger.create_draft(
            self.cid,
            d,
            [self.p("88", "75", 2_000_000, (), (founder.id,))],
            "Dividendlərin hesablanması (layihə)",
        )
        chairs = self.product["chair"]
        self.inventory.create_sale_draft(
            self.cid,
            d,
            [
                SaleLine(
                    self.item["chair"],
                    self.warehouse["main"],
                    4,
                    money(4 * chairs.wholesale),
                    money(vat18(4 * chairs.wholesale)),
                )
            ],
            self.acc["62"],
            self.partner["gilan"].sc,
            "Malların topdan satışı (sifariş)",
            vat_rate=STANDARD_VAT_RATE,
        )
        self.ledger.bank.save_bank_operation(
            self.cid,
            BankOperationInput(
                d.isoformat(),
                OUT,
                self.acc["51"],
                [BankLine(self.acc["70"], 0)],
                SALARY,
                (self.bank_azn,),
                memo="Dekabr əmək haqqı (hazırlanır)",
            ),
            post=False,
        )

    def portal(self) -> None:
        """What the portal showed of the e-qaimə up to September of the last year; two
        differ: a purchase whose amount the supplier corrected, a sale cancelled on the
        portal. The months up to August of the last year are reconciled."""
        last = self.last
        invoices = [x for x in self.state.invoices if x[2] < f"{last}-10-01"]
        shown = []
        for outgoing, number, day, partner, total, vat in invoices:
            data = self.partner[partner].data
            status = "approved" if outgoing else "approvedBySystem"
            shown.append(
                PortalInvoice(number, outgoing, day, status, data.tin or "", data.name, total, vat)
            )
        august, september = f"{last}-08-", f"{last}-09-"
        purchase = next(
            i for i, x in enumerate(shown) if not x.outgoing and x.doc_date.startswith(august)
        )
        sale = next(
            i for i, x in enumerate(shown) if x.outgoing and x.doc_date.startswith(september)
        )
        x = shown[purchase]
        shown[purchase] = replace(x, total=x.total + 1_180, vat=x.vat + 180)
        shown[sale] = replace(shown[sale], status="canceled")
        self.ledger.eqaime.remember_portal(self.cid, shown, f"{last}-10-05T09:30:00")
        for y in self.years:
            for month in range(1, 9 if y == last else 13):
                reconciled = f"{last_day(y, month) + timedelta(days=16)}T11:00:00"
                for outgoing in (False, True):
                    self.ledger.eqaime.mark_reconciled(
                        self.cid,
                        outgoing,
                        date(y, month, 1),
                        last_day(y, month),
                        reconciled,
                    )
