-- A period of a bank account reconciled with the tax portal (D118): the ƏDV deposit
-- account's. Its figures by both sides as they were then: a change seen later — on the
-- portal or in the books — is warned about.

CREATE TABLE bank_portal_reconciled (
    id             INTEGER PRIMARY KEY,
    company_id     INTEGER NOT NULL REFERENCES companies(id),
    account_id     INTEGER NOT NULL,
    value_id       INTEGER,
    date_from      TEXT NOT NULL,
    date_to        TEXT NOT NULL,
    reconciled_at  TEXT NOT NULL,
    portal_opening INTEGER NOT NULL,
    portal_in      INTEGER NOT NULL CHECK (portal_in >= 0),
    portal_out     INTEGER NOT NULL CHECK (portal_out >= 0),
    books_opening  INTEGER NOT NULL,
    books_in       INTEGER NOT NULL CHECK (books_in >= 0),
    books_out      INTEGER NOT NULL CHECK (books_out >= 0),
    CHECK (date_to >= date_from),
    FOREIGN KEY (company_id, account_id) REFERENCES accounts(company_id, id),
    FOREIGN KEY (company_id, value_id) REFERENCES subconto_values(company_id, id),
    UNIQUE (company_id, id)
);

CREATE INDEX bank_portal_reconciled_place
    ON bank_portal_reconciled (company_id, account_id, value_id, date_from);
CREATE INDEX bank_portal_reconciled_value ON bank_portal_reconciled (company_id, value_id);
