-- The periods loaded from the tax portal into a bank account (D115): the ƏDV deposit
-- account's, so a period loaded already is not loaded again unasked. An operation itself
-- is never doubled anyway: it is known by its reference (D112).

CREATE TABLE bank_portal_loads (
    id         INTEGER PRIMARY KEY,
    company_id INTEGER NOT NULL REFERENCES companies(id),
    account_id INTEGER NOT NULL,
    value_id   INTEGER,
    date_from  TEXT NOT NULL,
    date_to    TEXT NOT NULL,
    loaded_at  TEXT NOT NULL,
    operations INTEGER NOT NULL DEFAULT 0 CHECK (operations >= 0),  -- the portal's, done
    CHECK (date_to >= date_from),
    FOREIGN KEY (company_id, account_id) REFERENCES accounts(company_id, id),
    FOREIGN KEY (company_id, value_id) REFERENCES subconto_values(company_id, id),
    UNIQUE (company_id, id)
);

CREATE INDEX bank_portal_loads_place
    ON bank_portal_loads (company_id, account_id, value_id, date_from);
CREATE INDEX bank_portal_loads_value ON bank_portal_loads (company_id, value_id);
