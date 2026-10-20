-- Bank fees of a conversion become lines (D37): any number of them, each taken from any
-- money account in that account's currency — the account sold from, the one credited,
-- or a third one (a fee in manat for an exchange of USD to EUR).

CREATE TABLE conversion_fees (
    id                 INTEGER PRIMARY KEY,
    company_id         INTEGER NOT NULL REFERENCES companies(id),
    conversion_id      INTEGER NOT NULL,
    line_no            INTEGER NOT NULL,
    account_id         INTEGER NOT NULL,  -- the account the bank took the fee from
    sc1                INTEGER,
    sc2                INTEGER,
    sc3                INTEGER,
    currency_id        INTEGER,  -- NULL: manat
    amount             INTEGER NOT NULL CHECK (amount > 0),  -- in that currency
    expense_account_id INTEGER,  -- NULL: the bank fee account of the settings
    FOREIGN KEY (company_id, conversion_id) REFERENCES currency_conversions(company_id, id)
        ON DELETE CASCADE,
    FOREIGN KEY (company_id, account_id) REFERENCES accounts(company_id, id),
    FOREIGN KEY (company_id, sc1) REFERENCES subconto_values(company_id, id),
    FOREIGN KEY (company_id, sc2) REFERENCES subconto_values(company_id, id),
    FOREIGN KEY (company_id, sc3) REFERENCES subconto_values(company_id, id),
    FOREIGN KEY (company_id, currency_id) REFERENCES currencies(company_id, id),
    FOREIGN KEY (company_id, expense_account_id) REFERENCES accounts(company_id, id),
    UNIQUE (conversion_id, line_no)
);

INSERT INTO conversion_fees (company_id, conversion_id, line_no, account_id, sc1, sc2, sc3,
                             currency_id, amount, expense_account_id)
SELECT company_id, id, 1,
       CASE fee_side WHEN 'to' THEN to_account_id ELSE from_account_id END,
       CASE fee_side WHEN 'to' THEN to_sc1 ELSE from_sc1 END,
       CASE fee_side WHEN 'to' THEN to_sc2 ELSE from_sc2 END,
       CASE fee_side WHEN 'to' THEN to_sc3 ELSE from_sc3 END,
       CASE fee_side WHEN 'to' THEN to_currency_id ELSE from_currency_id END,
       fee_amount, fee_account_id
FROM currency_conversions
WHERE fee_amount > 0
  AND (CASE fee_side WHEN 'to' THEN to_account_id ELSE from_account_id END) IS NOT NULL;

-- the fee columns go: the table is rebuilt, ids are kept
CREATE TABLE currency_conversions_new (
    id                 INTEGER PRIMARY KEY,
    company_id         INTEGER NOT NULL REFERENCES companies(id),
    document_id        INTEGER NOT NULL UNIQUE,
    credit_document_id INTEGER UNIQUE,
    from_account_id    INTEGER,
    from_sc1           INTEGER,
    from_sc2           INTEGER,
    from_sc3           INTEGER,
    from_currency_id   INTEGER,
    from_amount        INTEGER CHECK (from_amount IS NULL OR from_amount > 0),
    from_reference     TEXT NOT NULL DEFAULT '',
    to_account_id      INTEGER,
    to_sc1             INTEGER,
    to_sc2             INTEGER,
    to_sc3             INTEGER,
    to_currency_id     INTEGER,
    to_amount          INTEGER CHECK (to_amount IS NULL OR to_amount > 0),
    to_date            TEXT
        CHECK (to_date IS NULL OR to_date GLOB '[0-9][0-9][0-9][0-9]-[0-1][0-9]-[0-3][0-9]'),
    to_reference       TEXT NOT NULL DEFAULT '',
    FOREIGN KEY (company_id, document_id) REFERENCES documents(company_id, id),
    FOREIGN KEY (company_id, credit_document_id) REFERENCES documents(company_id, id),
    FOREIGN KEY (company_id, from_account_id) REFERENCES accounts(company_id, id),
    FOREIGN KEY (company_id, from_sc1) REFERENCES subconto_values(company_id, id),
    FOREIGN KEY (company_id, from_sc2) REFERENCES subconto_values(company_id, id),
    FOREIGN KEY (company_id, from_sc3) REFERENCES subconto_values(company_id, id),
    FOREIGN KEY (company_id, from_currency_id) REFERENCES currencies(company_id, id),
    FOREIGN KEY (company_id, to_account_id) REFERENCES accounts(company_id, id),
    FOREIGN KEY (company_id, to_sc1) REFERENCES subconto_values(company_id, id),
    FOREIGN KEY (company_id, to_sc2) REFERENCES subconto_values(company_id, id),
    FOREIGN KEY (company_id, to_sc3) REFERENCES subconto_values(company_id, id),
    FOREIGN KEY (company_id, to_currency_id) REFERENCES currencies(company_id, id),
    UNIQUE (company_id, id)
);

INSERT INTO currency_conversions_new
SELECT id, company_id, document_id, credit_document_id,
       from_account_id, from_sc1, from_sc2, from_sc3, from_currency_id, from_amount,
       from_reference,
       to_account_id, to_sc1, to_sc2, to_sc3, to_currency_id, to_amount, to_date, to_reference
FROM currency_conversions;

DROP TABLE currency_conversions;
ALTER TABLE currency_conversions_new RENAME TO currency_conversions;

CREATE INDEX currency_conversions_from_reference
    ON currency_conversions (company_id, from_reference) WHERE from_reference <> '';
CREATE INDEX currency_conversions_to_reference
    ON currency_conversions (company_id, to_reference) WHERE to_reference <> '';
