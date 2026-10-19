class LedgerError(Exception):
    """Base class for accounting rule violations shown to the user."""


class ValidationError(LedgerError):
    pass


class PeriodClosedError(LedgerError):
    pass


class NotFoundError(LedgerError):
    pass
