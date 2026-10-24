"""Currency conversion (D37, D44): a document that builds its own GL postings through
transit. Reading and the calculation shared by the form and the postings — `calc`;
writing — `ConversionModule`, one object over the ledger's connection
(`ledger.conversion`), from `commands`."""

from __future__ import annotations

from modern_gl.application.conversion.calc import (
    Conversion,
    ConversionCalc,
    ConversionFee,
    ConversionInput,
    ConversionSide,
    bank_rate,
    calculate,
    fee_date,
    fee_on_credit,
    load_conversion,
    official_rate,
    same_day,
)
from modern_gl.application.conversion.commands import (
    BANK_FEE_ITEM,
    EXCHANGE_DIFFERENCE,
    ConversionCommands,
    MissingAccountRole,
)


class ConversionModule(ConversionCommands):
    """The conversion's write scenarios (D44): one object per ledger, `ledger.conversion`."""


__all__ = [
    "BANK_FEE_ITEM",
    "EXCHANGE_DIFFERENCE",
    "Conversion",
    "ConversionCalc",
    "ConversionCommands",
    "ConversionFee",
    "ConversionInput",
    "ConversionModule",
    "ConversionSide",
    "MissingAccountRole",
    "bank_rate",
    "calculate",
    "fee_date",
    "fee_on_credit",
    "load_conversion",
    "official_rate",
    "same_day",
]
