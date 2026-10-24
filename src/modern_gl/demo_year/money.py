"""The year demo's money: opening balances, the bank (customers, suppliers, the ƏDV deposit
account, salaries, taxes, the loan), the euro bought for the import, cash and month-end
entries."""

from __future__ import annotations

from datetime import date

from modern_gl.application.bank import (
    CUSTOMER,
    FEE,
    IN,
    OTHER,
    OUT,
    SALARY,
    SUPPLIER,
    TAX,
    TRANSFER,
    BankLine,
    BankOperationInput,
)
from modern_gl.application.conversion import ConversionFee, ConversionInput, ConversionSide
from modern_gl.application.ledger import ImportedDocument, PostingInput
from modern_gl.demo_year.firm import EMPLOYEES, Firm, Open, money
from modern_gl.reporting.reports import subconto_balance, trial_balance

CASH_FLOAT = 50_000  # what stays in the till after the money goes to the bank
LOAN, LOAN_RATE = 5_000_000, 14  # qəpik, % a year


def social_tax(gross: int) -> tuple[int, int]:
    """(withheld from the employee, paid by the employer): DSMF 3% / 22% of the first
    200 manat and 10% / 15% of the rest, unemployment 0.5% each, medical 2% each."""
    low, high = min(gross, 20_000), max(gross - 20_000, 0)
    employee = (low * 3 + high * 10) // 100 + gross // 200 + gross * 2 // 100
    employer = (low * 22 + high * 15) // 100 + gross // 200 + gross * 2 // 100
    return employee, employer


def income_tax(gross: int) -> int:
    """14% of what is above 8 000 manat a month (the non-oil private sector)."""
    return max(gross - 800_000, 0) * 14 // 100


class Money(Firm):
    def opening_balances(self) -> None:
        control = self.ledger.opening_account(self.cid)
        p = self.partner
        debit = [
            ("51", 8_500_000, (self.bank_azn,)),
            ("54", 400_000, (self.deposit,)),
            ("50", 120_000, ()),
            ("01", 1_200_000, (self.asset["Ofis kompüterləri"],)),
            ("01", 800_000, (self.asset["Anbar rəfləri"],)),
            ("62", 944_000, p["absheron"].sc),
        ]
        credit = [
            ("02", 400_000, (self.asset["Ofis kompüterləri"],)),
            ("02", 160_000, (self.asset["Anbar rəfləri"],)),
            ("60", 620_000, p["tech"].sc),
            ("85", 5_000_000, (p["founder"].id,)),
        ]
        retained = sum(a for _, a, _ in debit) - sum(a for _, a, _ in credit)
        credit.append(("88", retained, ()))
        lines = [
            PostingInput(self.acc[code], control, money(amount), sc) for code, amount, sc in debit
        ] + [
            PostingInput(control, self.acc[code], money(amount), (), sc)
            for code, amount, sc in credit
        ]
        self.ledger.save_opening_balances(
            self.cid,
            date(self.first, 1, 1),
            lines,
            post=True,
            memo=f"İlkin qalıqlar 01.01.{self.first}",
        )
        s = self.state
        s.bank, s.deposit, s.cash = 8_500_000, 400_000, 120_000
        s.receivable.append(Open("absheron", date(self.first, 1, 14), 800_000, 144_000))
        s.payable.append(Open("tech", date(self.first, 1, 9), 525_424, 94_576))

    # ---- the bank ---------------------------------------------------------------------

    def bank_op(
        self,
        day: date,
        direction: str,
        kind: str,
        lines: list[BankLine],
        memo: str,
        *,
        account: str = "51",
        currency: int | None = None,
        bank: int | None = None,
    ) -> None:
        if bank is None:
            bank = {"51": self.bank_azn, "52": self.bank_eur, "54": self.deposit}[account]
        self.ledger.bank.save_bank_operation(
            self.cid,
            BankOperationInput(
                day.isoformat(),
                direction,
                self.acc[account],
                lines,
                kind,
                (bank,),
                currency,
                memo=memo,
                reference=f"{day:%y%m%d}-{self.rng.randrange(10_000, 99_999)}",
            ),
            post=True,
        )

    def payment(self, day: date, direction: str, kind: str, code: str, bill: Open, memo: str):
        """A settlement with a partner: the amount without ƏDV through the current account,
        the ƏDV through the deposit account (D69)."""
        sc = self.partner[bill.partner].sc
        self.bank_op(
            day, direction, kind, [BankLine(self.acc[code], bill.net, sc, bill.invoice)], memo
        )
        if bill.vat:
            self.bank_op(
                day,
                direction,
                kind,
                [BankLine(self.acc[code], bill.vat, sc, bill.invoice)],
                memo + " (ƏDV)",
                account="54",
            )

    def collect(self, day: date) -> None:
        s = self.state
        for bill in [b for b in s.receivable if b.due <= day]:
            name = self.partner[bill.partner].data.name
            self.payment(day, IN, CUSTOMER, "62", bill, f"{name}: mal üçün ödəniş")
            s.receivable.remove(bill)
            s.bank, s.deposit = s.bank + bill.net, s.deposit + bill.vat

    def pay_suppliers(self, day: date) -> None:
        s = self.state
        for bill in [b for b in s.payable if b.due <= day]:
            name = self.partner[bill.partner].data.name
            if bill.fx:
                code = bill.fx_code
                if s.fx[code] < bill.fx:
                    self.buy_currency(day, code, bill.fx - s.fx[code])
                self.bank_op(
                    day,
                    OUT,
                    SUPPLIER,
                    [BankLine(self.acc["60"], bill.fx, self.partner[bill.partner].sc)],
                    f"{name}: invoice {bill.invoice}".rstrip(),
                    account="52",
                    currency=self.fx_id[code],
                    bank=self.fx_bank[code],
                )
                s.fx[code] -= bill.fx
            else:
                if s.bank < bill.net + 2_000_000:
                    continue  # waits for the customers' money
                self.top_up_deposit(day, bill.vat)
                self.payment(day, OUT, SUPPLIER, "60", bill, f"{name}: ödəniş")
                s.bank, s.deposit = s.bank - bill.net, s.deposit - bill.vat
            s.payable.remove(bill)

    def top_up_deposit(self, day: date, needed: int) -> None:
        s = self.state
        if s.deposit >= needed:
            return
        amount = -(-(needed - s.deposit) // 100_000) * 100_000  # whole thousands of manat
        self.bank_op(
            day,
            OUT,
            TRANSFER,
            [BankLine(self.acc["54"], amount, (self.deposit,))],
            "ƏDV depozit hesabının artırılması",
        )
        s.bank, s.deposit = s.bank - amount, s.deposit + amount

    def buy_currency(self, day: date, code: str, cents: int) -> None:
        """Euro or dollars for a supplier abroad: the bank sells them 1.2% above the
        Central Bank."""
        cents = -(-cents // 10_000) * 10_000  # whole hundreds
        manat = int((cents * self.rate(code, day) * 1012 / 1000).to_integral_value())
        self.ledger.conversion.save_conversion(
            self.cid,
            ConversionInput(
                day.isoformat(),
                ConversionSide(self.acc["51"], manat, (self.bank_azn,)),
                ConversionSide(self.acc["52"], cents, (self.fx_bank[code],), self.fx_id[code]),
                fees=(ConversionFee(self.acc["51"], 1_500, (self.bank_azn,)),),
                memo="Avronun alınması" if code == "EUR" else "Dolların alınması",
            ),
            post=True,
        )
        s = self.state
        s.bank = s.bank - manat - 1_500
        s.fx[code] += cents

    def bank_fee(self, day: date) -> None:
        amount = 2_500 + self.rng.randrange(0, 1_500)
        self.bank_op(day, OUT, FEE, [BankLine(self.acc["80"], amount)], "Bank xidmətləri haqqı")
        self.state.bank -= amount

    def take_loan(self, day: date) -> None:
        bank = self.partner["bank"]
        self.bank_op(
            day, IN, OTHER, [BankLine(self.acc["90"], LOAN, bank.sc)], "Bank kreditinin alınması"
        )
        self.state.bank += LOAN
        self.state.loan = LOAN

    def repay_loan(self, day: date) -> None:
        s = self.state
        if not s.loan:
            return
        interest = s.loan * LOAN_RATE // 1200
        principal = min(250_000, s.loan)
        bank = self.partner["bank"].sc
        # the interest is a debt to the bank first: financing in the profit and loss (D128)
        self.ledger.post_new(
            self.cid, day, [self.p("80", "90", interest, (), bank)], "Kredit faizinin hesablanması"
        )
        self.bank_op(
            day,
            OUT,
            OTHER,
            [BankLine(self.acc["90"], principal + interest, bank)],
            "Kredit və faiz ödənişi",
        )
        s.loan -= principal
        s.bank -= principal + interest

    def deposit_cash(self, day: date) -> None:
        s = self.state
        amount = (s.cash - CASH_FLOAT) // 10_000 * 10_000
        if amount > 0:
            self.bank_op(
                day,
                IN,
                OTHER,
                [BankLine(self.acc["50"], amount)],
                "Nağd pulun banka mədaxili (inkassasiya)",
            )
            s.cash, s.bank = s.cash - amount, s.bank + amount

    # ---- people -----------------------------------------------------------------------

    def advance(self, day: date) -> None:
        driver = self.employee["Babayev Tural"]
        self.ledger.post_new(
            self.cid, day, [self.p("71", "50", 30_000, (driver,))], "Təhtəlhesab məbləğ verildi"
        )
        self.state.cash -= 30_000

    def advance_report(self, day: date) -> None:
        driver = self.employee["Babayev Tural"]
        spent = 20_000 + self.rng.randrange(0, 9_000)
        self.ledger.post_new(
            self.cid,
            day,
            [
                self.p(
                    "26",
                    "71",
                    spent,
                    [self.cost["Ezamiyyə və nəqliyyat"]],
                    (driver,),
                    "Yanacaq və dayanacaq",
                ),
                self.p("50", "71", 30_000 - spent, (), (driver,), "Artıq qalığın qaytarılması"),
            ],
            "Avans hesabatı",
        )
        self.state.cash += 30_000 - spent

    def payroll(self, day: date) -> None:
        """The month's salaries as the payroll program exports them (an import)."""
        s, lines = self.state, []
        for name, gross, account in EMPLOYEES:
            emp = (self.employee[name],)
            withheld, employer = social_tax(gross)
            tax = income_tax(gross)
            lines.append(self.p(account, "70", gross, [self.cost["Əmək haqqı"]], emp, name))
            lines.append(self.p("70", "69", withheld, emp, (), "DSMF, işsizlik, tibbi sığorta"))
            if tax:
                lines.append(self.p("70", "68.1", tax, emp, (), "Gəlir vergisi"))
            lines.append(
                self.p(
                    account,
                    "69",
                    employer,
                    [self.cost["Sosial sığorta"]],
                    (),
                    "İşəgötürənin sığorta haqları",
                )
            )
            s.salaries_due[name] = gross - withheld - tax
            s.social_due += withheld + employer
            s.income_tax_due += tax
        outcome = self.ledger.import_documents(
            self.cid,
            [ImportedDocument(day, lines, f"Əmək haqqı: {day:%m.%Y} (maaş proqramından)")],
        )
        if outcome.errors:
            raise RuntimeError(outcome.errors)

    def pay_salaries(self, day: date) -> None:
        s = self.state
        if not s.salaries_due:
            return
        lines = [
            BankLine(self.acc["70"], amount, (self.employee[name],))
            for name, amount in s.salaries_due.items()
        ]
        self.bank_op(day, OUT, SALARY, lines, "Əmək haqqının kartlara köçürülməsi")
        s.bank -= sum(s.salaries_due.values())
        s.salaries_due = {}

    def pay_taxes(self, day: date) -> None:
        """The 20th: social insurance and income tax from the current account, ƏDV from
        the deposit account."""
        s = self.state
        lines = [BankLine(self.acc["69"], s.social_due)] if s.social_due else []
        if s.income_tax_due:
            lines.append(BankLine(self.acc["68.1"], s.income_tax_due))
        if lines:
            self.bank_op(day, OUT, TAX, lines, "Vergi və sosial sığorta ödənişi")
            s.bank -= s.social_due + s.income_tax_due
            s.social_due = s.income_tax_due = 0
        if s.vat_due > 0:
            self.top_up_deposit(day, s.vat_due)
            self.bank_op(
                day,
                OUT,
                TAX,
                [BankLine(self.acc["68.2"], s.vat_due)],
                "ƏDV-nin büdcəyə ödənilməsi",
                account="54",
            )
            s.deposit -= s.vat_due
            s.vat_due = 0

    # ---- month end --------------------------------------------------------------------

    def offset_vat(self, day: date) -> None:
        """The month's input ƏDV against the output ƏDV, per supplier (Dt 68.2 / Kt 19)."""
        s = self.state
        lines = [
            self.p("68.2", "19", vat, (), (self.partner[key].id,), "ƏDV əvəzləşdirilməsi")
            for key, vat in s.input_vat.items()
            if vat
        ]
        if lines:
            self.ledger.post_new(self.cid, day, lines, "Ödənilmiş ƏDV-nin əvəzləşdirilməsi")
        s.vat_due += s.output_vat - sum(s.input_vat.values())
        s.output_vat = 0
        s.input_vat.clear()

    def balance(self, code: str, date_from: date, day: date) -> int:
        """Credit balance (negative: debit) of an account at the end of `day`."""
        rows = trial_balance(self.ledger.conn, self.cid, date_from, day).rows
        row = next(r for r in rows if r.code == code)
        return row.closing_ct - row.closing_dt

    def close_expenses(self, day: date) -> None:
        """The month's expenses go to sales (Dt 46 / Kt 26, 44), per cost item."""
        lines = [
            self.p("46", code, r.closing_dt - r.closing_ct, (), (r.value_id,))
            for code in ("26", "44")
            for r in subconto_balance(self.ledger.conn, self.cid, code, date(day.year, 1, 1), day)
            if r.closing_dt != r.closing_ct
        ]
        if lines:
            self.ledger.post_new(self.cid, day, lines, "Xərclərin satışa silinməsi")

    def sales_result(self, day: date) -> None:
        """What is left on 46 after the month's sales goes to profit and loss."""
        result = self.balance("46", day.replace(day=1), day)
        if result > 0:
            self.ledger.post_new(
                self.cid, day, [self.p("46", "80", result)], "Satışdan maliyyə nəticəsi"
            )
        elif result < 0:
            self.ledger.post_new(
                self.cid, day, [self.p("80", "46", -result)], "Satışdan maliyyə nəticəsi"
            )

    def pay_profit_tax(self, day: date) -> None:
        self.bank_op(
            day, OUT, TAX, [BankLine(self.acc["68.3"], 150_000)], "Mənfəət vergisi üzrə cari ödəniş"
        )
        self.state.bank -= 150_000

    def close_year(self, day: date) -> None:
        """Profit tax of the year (20%) and the profit into retained earnings."""
        profit = self.balance("80", date(day.year, 1, 1), day)
        if profit > 0:
            tax = profit * 20 // 100
            self.ledger.post_new(
                self.cid, day, [self.p("80", "68.3", tax)], "İllik mənfəət vergisinin hesablanması"
            )
            profit -= tax
        if profit:
            dt, ct = ("80", "88") if profit > 0 else ("88", "80")
            self.ledger.post_new(
                self.cid,
                day,
                [self.p(dt, ct, abs(profit))],
                "İlin xalis mənfəətinin bölüşdürülməmiş mənfəətə köçürülməsi",
            )
