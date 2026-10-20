-- A company has one set of opening balances.  The actual balances remain ordinary
-- double-entry postings; this table only marks their document and keeps the date on
-- whose morning they take effect (the GL document itself is dated one day earlier).

CREATE TABLE opening_balance_documents (
    company_id     INTEGER PRIMARY KEY REFERENCES companies(id),
    document_id    INTEGER NOT NULL UNIQUE,
    effective_date TEXT NOT NULL
        CHECK (effective_date GLOB '[0-9][0-9][0-9][0-9]-[0-1][0-9]-[0-3][0-9]'),
    FOREIGN KEY (company_id, document_id)
        REFERENCES documents(company_id, id) ON DELETE CASCADE
);
