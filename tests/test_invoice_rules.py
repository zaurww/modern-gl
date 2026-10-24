"""One rule for which postings of an invoice number count (D120): the e-qaimə report takes
every settlement turnover and every ƏDV line (what is left to pay); the reconciliation
with the portal only the accrual of the e-qaimə and its ƏDV."""

from modern_gl.application.invoice_rules import (
    InvoiceAccount,
    is_accrual,
    is_vat_accrual,
    turnover_sides,
)

GOODS = InvoiceAccount("inventory", None, None)  # 41
SUPPLIER = InvoiceAccount("payable", 1, 2)  # 60 [counterparty, contract]
CUSTOMER = InvoiceAccount("receivable", 1, 2)  # 62
ADVANCE = InvoiceAccount("advance_paid", 1, None)  # 60.2
VAT = InvoiceAccount("input_vat", 1, None)  # 19
BANK = InvoiceAccount("bank", None, None)  # 51
DEPOSIT = InvoiceAccount("vat_deposit", None, None)  # ƏDV deposit
OLD_PARTNER = InvoiceAccount(None, 1, None)  # no type, but the counterparty directory


def test_settlement_is_a_type_or_the_counterparty_directory():
    assert SUPPLIER.settlement and OLD_PARTNER.settlement
    assert not GOODS.settlement and not VAT.settlement


def test_turnover_is_every_settlement_side_but_an_advance_set_against_it():
    assert turnover_sides(GOODS, SUPPLIER) == (False, True)  # Dt 41 / Kt 60: accrual
    assert turnover_sides(SUPPLIER, BANK) == (True, False)  # Dt 60 / Kt 51: payment
    assert turnover_sides(SUPPLIER, CUSTOMER) == (True, True)  # offset of two partners
    assert turnover_sides(SUPPLIER, ADVANCE) == (True, False)  # the advance pays it (D78)


def test_accrual_is_the_e_qaime_itself():
    assert is_accrual(SUPPLIER, GOODS)  # Dt 41 / Kt 60
    assert is_accrual(SUPPLIER, VAT)  # Dt 19 / Kt 60
    assert is_accrual(OLD_PARTNER, GOODS)
    assert not is_accrual(SUPPLIER, BANK)  # a payment
    assert not is_accrual(SUPPLIER, CUSTOMER)  # an offset
    assert not is_accrual(GOODS, SUPPLIER)  # the goods side is no settlement


def test_vat_of_the_e_qaime_is_not_its_payment():
    assert is_vat_accrual(VAT, SUPPLIER)  # Dt 19 / Kt 60
    assert not is_vat_accrual(VAT, BANK)  # paid to the budget
    assert not is_vat_accrual(VAT, DEPOSIT)  # paid from the ƏDV deposit (D41)
    assert not is_vat_accrual(VAT, InvoiceAccount("tax_payable", None, None))
