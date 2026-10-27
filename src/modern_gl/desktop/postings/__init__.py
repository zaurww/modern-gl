"""Postings grid: model, inline editors with completion, keyboard flow.

Keyboard flow (1C-like): type into a cell to edit, Enter and Tab alike move to the next
cell that applies (Shift+Tab back), and the cell they reach is open for typing at once —
subconto cells the chosen account doesn't have are skipped, and so are the currency
cells of a line without a currency account. On a currency line the amount in manat
follows the amount in currency at the rate (the rate of the document date is offered;
both the rate and the manat amount can be typed over).
Enter on the last cell of the last row starts a new row. A name a directory does not
have yet is offered last in the list ("+ Добавить «…»"): Enter adds it, no dialog.

Paste (Ctrl+V) takes lines copied from Excel, one posting per line. With a header line
(Дебет, Кредит, Сумма… in Russian or Azerbaijani, any order) cells go by the headers;
without one they go in the order of keyboard entry: Dt, its subconto, Kt, its subconto,
(currency, amount in currency, rate,) amount, memo — an empty cell skips a field.
Copy (Ctrl+C) gives the document in the header form, so it can go to Excel and back.

Speed-ups: a subconto list starts with the elements recently used on that account; the
memo cell offers the memo of the last posting with the same Dt/Kt pair (selected, so
typing replaces it); "#" in the Dt cell picks an entry template; an amount may be typed
as arithmetic (1180*18/118).

The e-qaimə column (the number of the portal's electronic invoice) appears once a line
is on a settlement or ƏDV account; it stays after the memo, so pasting in the order of
keyboard entry is not shifted.
"""

from __future__ import annotations

from modern_gl.application.table_text import header_names, plain_number
from modern_gl.desktop.postings.columns import (
    AMOUNT,
    CT,
    CURRENCY,
    CURRENCY_AMOUNT,
    DT,
    HEADER_FIELDS,
    HEADERS,
    INVOICE,
    MEMO,
    RATE,
    EntryHints,
    PostingRow,
    header_columns,
)
from modern_gl.desktop.postings.model import PostingsModel
from modern_gl.desktop.postings.table import PostingsDelegate, PostingsTable

__all__ = [
    "AMOUNT",
    "CT",
    "CURRENCY",
    "CURRENCY_AMOUNT",
    "DT",
    "HEADERS",
    "HEADER_FIELDS",
    "INVOICE",
    "MEMO",
    "RATE",
    "EntryHints",
    "PostingRow",
    "PostingsDelegate",
    "PostingsModel",
    "PostingsTable",
    "header_columns",
    "header_names",
    "plain_number",
]
