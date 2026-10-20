-- Currency conversion (D37): a document of its own whose GL postings it builds itself.
-- The GL document carries the number, the date of the debit side, the memo and the status;
-- this row keeps what was entered. A credit that comes on a later day gets a second GL
-- document of that day. A draft may lack one side (only one bank statement has come).

CREATE TABLE currency_conversions (
    id                 INTEGER PRIMARY KEY,
    company_id         INTEGER NOT NULL REFERENCES companies(id),
    document_id        INTEGER NOT NULL UNIQUE,
    credit_document_id INTEGER UNIQUE,
    -- "Списано с": account, its subconto, currency (NULL = manat), amount in that currency
    from_account_id    INTEGER,
    from_sc1           INTEGER,
    from_sc2           INTEGER,
    from_sc3           INTEGER,
    from_currency_id   INTEGER,
    from_amount        INTEGER CHECK (from_amount IS NULL OR from_amount > 0),
    from_reference     TEXT NOT NULL DEFAULT '',  -- reference of the bank statement line
    -- "Зачислено на"; to_date NULL: the same day as the debit
    to_account_id      INTEGER,
    to_sc1             INTEGER,
    to_sc2             INTEGER,
    to_sc3             INTEGER,
    to_currency_id     INTEGER,
    to_amount          INTEGER CHECK (to_amount IS NULL OR to_amount > 0),
    to_date            TEXT
        CHECK (to_date IS NULL OR to_date GLOB '[0-9][0-9][0-9][0-9]-[0-1][0-9]-[0-3][0-9]'),
    to_reference       TEXT NOT NULL DEFAULT '',
    -- bank fee, in the currency of the side it is taken from
    fee_amount         INTEGER NOT NULL DEFAULT 0 CHECK (fee_amount >= 0),
    fee_side           TEXT NOT NULL DEFAULT 'from' CHECK (fee_side IN ('from', 'to')),
    fee_account_id     INTEGER,
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
    FOREIGN KEY (company_id, fee_account_id) REFERENCES accounts(company_id, id),
    UNIQUE (company_id, id)
);

-- a bank statement import finds the conversion already entered by its references
CREATE INDEX currency_conversions_from_reference
    ON currency_conversions (company_id, from_reference) WHERE from_reference <> '';
CREATE INDEX currency_conversions_to_reference
    ON currency_conversions (company_id, to_reference) WHERE to_reference <> '';

-- Accounts of conversions (D34 roles): transit 57, exchange gain 91.1 / loss 91.2, bank fee
-- 91.2 — for existing companies on the 1C 7.7 chart; others choose them in the settings.
INSERT INTO account_roles (company_id, role, account_id)
SELECT a.company_id, r.role, a.id
FROM accounts a
JOIN (
    SELECT '57' AS code, 'fx_transit' AS role
    UNION ALL SELECT '91.1', 'fx_gain'
    UNION ALL SELECT '91.2', 'fx_loss'
    UNION ALL SELECT '91.2', 'bank_fee'
) r ON r.code = a.code
WHERE a.is_group = 0 AND a.active = 1
  AND NOT EXISTS (
      SELECT 1 FROM account_roles x WHERE x.company_id = a.company_id AND x.role = r.role
  );
