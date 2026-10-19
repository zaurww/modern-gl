-- Entry templates (типовые операции): a named set of lines Dt / Kt / amount formula.
-- Applying one fills a new document; the template itself is not accounting data,
-- so it may be changed or deleted freely (both are written to the audit trail).
-- Accounts and subconto values are optional: whatever is empty is filled in by hand.

CREATE TABLE entry_templates (
    id          INTEGER PRIMARY KEY,
    company_id  INTEGER NOT NULL REFERENCES companies(id),
    name        TEXT NOT NULL CHECK (name <> ''),
    memo        TEXT NOT NULL DEFAULT '',
    UNIQUE (company_id, id)
);

CREATE TABLE entry_template_lines (
    id                INTEGER PRIMARY KEY,
    company_id        INTEGER NOT NULL,
    template_id       INTEGER NOT NULL,
    line_no           INTEGER NOT NULL,
    debit_account_id  INTEGER,
    credit_account_id INTEGER,
    dt_sc1 INTEGER, dt_sc2 INTEGER, dt_sc3 INTEGER,
    ct_sc1 INTEGER, ct_sc2 INTEGER, ct_sc3 INTEGER,
    formula           TEXT NOT NULL DEFAULT '',
    memo              TEXT NOT NULL DEFAULT '',
    FOREIGN KEY (company_id, template_id)
        REFERENCES entry_templates(company_id, id) ON DELETE CASCADE,
    FOREIGN KEY (company_id, debit_account_id)  REFERENCES accounts(company_id, id),
    FOREIGN KEY (company_id, credit_account_id) REFERENCES accounts(company_id, id),
    FOREIGN KEY (company_id, dt_sc1) REFERENCES subconto_values(company_id, id),
    FOREIGN KEY (company_id, dt_sc2) REFERENCES subconto_values(company_id, id),
    FOREIGN KEY (company_id, dt_sc3) REFERENCES subconto_values(company_id, id),
    FOREIGN KEY (company_id, ct_sc1) REFERENCES subconto_values(company_id, id),
    FOREIGN KEY (company_id, ct_sc2) REFERENCES subconto_values(company_id, id),
    FOREIGN KEY (company_id, ct_sc3) REFERENCES subconto_values(company_id, id),
    UNIQUE (template_id, line_no)
);
