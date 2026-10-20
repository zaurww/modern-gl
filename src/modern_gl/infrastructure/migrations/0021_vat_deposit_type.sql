-- A new account type: the ƏDV deposit account ("ƏDV depozit hesabı"). Its money sits in
-- the Treasury and may only pay ƏDV (to a supplier's deposit account, the budget,
-- customs), so it is not free cash like a bank account (D35, D41).
-- SQLite cannot change a CHECK in place: the table is rebuilt, ids are kept.

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
    currency      INTEGER NOT NULL DEFAULT 0,
    account_type  TEXT CHECK (account_type IN (
        'cash', 'bank', 'transit', 'vat_deposit', 'receivable', 'advance_paid',
        'other_receivable', 'input_vat', 'inventory', 'fixed_asset', 'intangible',
        'investment', 'other_asset',
        'payable', 'advance_received', 'tax_payable', 'payroll', 'short_term_loan',
        'long_term_loan', 'other_liability',
        'share_capital', 'retained_earnings', 'profit_loss', 'other_equity',
        'sales', 'other_income',
        'cost_of_sales', 'operating_expense', 'other_expense', 'income_tax'
    )),
    FOREIGN KEY (company_id, parent_id)   REFERENCES accounts(company_id, id),
    FOREIGN KEY (company_id, sc1_kind_id) REFERENCES subconto_kinds(company_id, id),
    FOREIGN KEY (company_id, sc2_kind_id) REFERENCES subconto_kinds(company_id, id),
    FOREIGN KEY (company_id, sc3_kind_id) REFERENCES subconto_kinds(company_id, id),
    UNIQUE (company_id, code),
    UNIQUE (company_id, id)
);

INSERT INTO accounts_new (id, company_id, code, name, parent_id, is_group, active,
                          sc1_kind_id, sc2_kind_id, sc3_kind_id, account_class, contra,
                          two_sided, currency, account_type)
SELECT id, company_id, code, name, parent_id, is_group, active,
       sc1_kind_id, sc2_kind_id, sc3_kind_id, account_class, contra,
       two_sided, currency, account_type
FROM accounts;

DROP TABLE accounts;
ALTER TABLE accounts_new RENAME TO accounts;
