-- Bank statements and the details of bank accounts (D78). A bank account of the module
-- is a place: a GL account and an element of its bank account directory (value_id NULL:
-- the GL account has no directory). Its lines are read from postings, as before; a
-- statement keeps only its period and the balance the bank's statement shows at its end.

-- What kind of account a place is (its group in the list), the card's last digits and
-- holder, the IBAN, closed. A place without a row: kind by its GL account and currency.
CREATE TABLE bank_account_details (
    id          INTEGER PRIMARY KEY,
    company_id  INTEGER NOT NULL REFERENCES companies(id),
    account_id  INTEGER NOT NULL,
    value_id    INTEGER,
    kind        TEXT NOT NULL CHECK (kind IN ('current', 'currency', 'vat_deposit', 'card')),
    card_digits TEXT NOT NULL DEFAULT '' CHECK (length(card_digits) IN (0, 4)),
    holder_id   INTEGER,  -- the employee who holds the card
    iban        TEXT NOT NULL DEFAULT '',
    closed      INTEGER NOT NULL DEFAULT 0 CHECK (closed IN (0, 1)),
    FOREIGN KEY (company_id, account_id) REFERENCES accounts(company_id, id),
    FOREIGN KEY (company_id, value_id) REFERENCES subconto_values(company_id, id),
    FOREIGN KEY (company_id, holder_id) REFERENCES subconto_values(company_id, id),
    UNIQUE (company_id, id)
);

CREATE UNIQUE INDEX bank_account_details_place
    ON bank_account_details (company_id, account_id, COALESCE(value_id, 0));
CREATE INDEX bank_account_details_value ON bank_account_details (company_id, value_id);
CREATE INDEX bank_account_details_holder ON bank_account_details (company_id, holder_id);

-- A statement of a place: a day or a period (a weekend, a card's month), and the balance
-- at its end by the bank (NULL: not entered yet). Periods of one place do not overlap.
CREATE TABLE bank_statements (
    id           INTEGER PRIMARY KEY,
    company_id   INTEGER NOT NULL REFERENCES companies(id),
    account_id   INTEGER NOT NULL,
    value_id     INTEGER,
    date_from    TEXT NOT NULL,
    date_to      TEXT NOT NULL,
    bank_closing INTEGER,  -- minor units of the place's currency
    source       TEXT NOT NULL DEFAULT 'manual' CHECK (source IN ('manual', 'file', 'api')),
    CHECK (date_to >= date_from),
    FOREIGN KEY (company_id, account_id) REFERENCES accounts(company_id, id),
    FOREIGN KEY (company_id, value_id) REFERENCES subconto_values(company_id, id),
    UNIQUE (company_id, id)
);

CREATE INDEX bank_statements_place
    ON bank_statements (company_id, account_id, value_id, date_from);
CREATE INDEX bank_statements_value ON bank_statements (company_id, value_id);
