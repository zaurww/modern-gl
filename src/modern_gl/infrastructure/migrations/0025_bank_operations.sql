-- Bank operations (D47): money in (mədaxil) or out (məxaric) of one bank account, a
-- document that builds its own GL postings, like a currency conversion. The GL document
-- carries the number, the date, the purpose of payment (memo) and the status; these rows
-- keep what was entered. Lines split the amount: several e-qaimə, contracts or taxes.

CREATE TABLE bank_operations (
    id              INTEGER PRIMARY KEY,
    company_id      INTEGER NOT NULL REFERENCES companies(id),
    document_id     INTEGER NOT NULL UNIQUE,
    direction       TEXT NOT NULL CHECK (direction IN ('in', 'out')),
    -- what it is: the default account of the lines, and the list of operations
    kind            TEXT NOT NULL DEFAULT 'other'
        CHECK (kind IN ('supplier', 'customer', 'tax', 'salary', 'fee', 'transfer', 'other')),
    -- the bank account: its account, subconto, currency (NULL = manat)
    account_id      INTEGER,
    sc1             INTEGER,
    sc2             INTEGER,
    sc3             INTEGER,
    currency_id     INTEGER,
    counterparty_id INTEGER,  -- fills the counterparty of every line
    reference       TEXT NOT NULL DEFAULT '',  -- reference of the bank statement line
    FOREIGN KEY (company_id, document_id) REFERENCES documents(company_id, id),
    FOREIGN KEY (company_id, account_id) REFERENCES accounts(company_id, id),
    FOREIGN KEY (company_id, sc1) REFERENCES subconto_values(company_id, id),
    FOREIGN KEY (company_id, sc2) REFERENCES subconto_values(company_id, id),
    FOREIGN KEY (company_id, sc3) REFERENCES subconto_values(company_id, id),
    FOREIGN KEY (company_id, currency_id) REFERENCES currencies(company_id, id),
    FOREIGN KEY (company_id, counterparty_id) REFERENCES subconto_values(company_id, id),
    UNIQUE (company_id, id)
);

-- a bank statement import finds the operation already entered by its reference
CREATE INDEX bank_operations_reference
    ON bank_operations (company_id, reference) WHERE reference <> '';

CREATE TABLE bank_operation_lines (
    id           INTEGER PRIMARY KEY,
    company_id   INTEGER NOT NULL REFERENCES companies(id),
    operation_id INTEGER NOT NULL,
    line_no      INTEGER NOT NULL,
    account_id   INTEGER,  -- the corresponding account (NULL only in a draft)
    sc1          INTEGER,
    sc2          INTEGER,
    sc3          INTEGER,
    amount       INTEGER NOT NULL DEFAULT 0 CHECK (amount >= 0),  -- in the operation's currency
    invoice      TEXT NOT NULL DEFAULT '',  -- e-qaimə the payment closes (D38)
    FOREIGN KEY (company_id, operation_id) REFERENCES bank_operations(company_id, id)
        ON DELETE CASCADE,
    FOREIGN KEY (company_id, account_id) REFERENCES accounts(company_id, id),
    FOREIGN KEY (company_id, sc1) REFERENCES subconto_values(company_id, id),
    FOREIGN KEY (company_id, sc2) REFERENCES subconto_values(company_id, id),
    FOREIGN KEY (company_id, sc3) REFERENCES subconto_values(company_id, id),
    UNIQUE (operation_id, line_no)
);
