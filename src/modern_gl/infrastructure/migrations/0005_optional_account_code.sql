-- The account code becomes optional: an account may be known by its name only.
-- Codes stay unique where given (NULLs do not collide in a UNIQUE constraint).
-- SQLite cannot drop NOT NULL in place, so the table is rebuilt; ids are kept,
-- so postings and subaccounts keep pointing at the same accounts.

CREATE TABLE accounts_new (
    id            INTEGER PRIMARY KEY,
    company_id    INTEGER NOT NULL REFERENCES companies(id),
    code          TEXT CHECK (code <> ''),
    name          TEXT NOT NULL,
    parent_id     INTEGER,
    is_group      INTEGER NOT NULL DEFAULT 0,
    active        INTEGER NOT NULL DEFAULT 1,
    sc1_kind_id   INTEGER,
    sc2_kind_id   INTEGER,
    sc3_kind_id   INTEGER,
    account_class TEXT
        CHECK (account_class IN ('asset', 'liability', 'equity', 'revenue', 'expense')),
    contra        INTEGER NOT NULL DEFAULT 0,
    two_sided     INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (company_id, parent_id)   REFERENCES accounts(company_id, id),
    FOREIGN KEY (company_id, sc1_kind_id) REFERENCES subconto_kinds(company_id, id),
    FOREIGN KEY (company_id, sc2_kind_id) REFERENCES subconto_kinds(company_id, id),
    FOREIGN KEY (company_id, sc3_kind_id) REFERENCES subconto_kinds(company_id, id),
    UNIQUE (company_id, code),
    UNIQUE (company_id, id)
);

INSERT INTO accounts_new (id, company_id, code, name, parent_id, is_group, active,
                          sc1_kind_id, sc2_kind_id, sc3_kind_id, account_class, contra, two_sided)
SELECT id, company_id, NULLIF(TRIM(code), ''), name, parent_id, is_group, active,
       sc1_kind_id, sc2_kind_id, sc3_kind_id, account_class, contra, two_sided
FROM accounts;

DROP TABLE accounts;
ALTER TABLE accounts_new RENAME TO accounts;
