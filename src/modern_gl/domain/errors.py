"""Accounting errors shown to the user: every rule violation is a LedgerError subclass."""


class LedgerError(Exception):
    """Base class for accounting rule violations shown to the user."""


class ValidationError(LedgerError):
    pass


class PeriodClosedError(LedgerError):
    pass


class NotFoundError(LedgerError):
    pass


class ReadOnlyError(LedgerError):
    """The company is open for viewing only: nothing is written."""
