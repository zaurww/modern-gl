"""Accounting errors shown to the user: every rule violation is a LedgerError subclass."""


class LedgerError(Exception):
    """Base class for accounting rule violations shown to the user."""


class ValidationError(LedgerError):
    """Input or a document that breaks a rule of accounting; the message is for the user."""


class PeriodClosedError(LedgerError):
    """A change dated in the closed period: only a red storno is possible there (D5)."""


class NotFoundError(LedgerError):
    """The record asked for is not in this company."""


class ReadOnlyError(LedgerError):
    """The company is open for viewing only: nothing is written."""
