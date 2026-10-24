-- Types for IFRS 18 and deferred tax (D128): deferred tax assets and liabilities get lines
-- of their own in the balance sheet (long-term), finance income goes to the investing
-- category of the profit and loss, finance expense (interest on borrowings) to financing.
-- SQLite cannot change a CHECK in place: the table is rebuilt, ids are kept (as 0035).

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
        'other_receivable', 'input_vat', 'inventory', 'investment', 'other_asset',
        'fixed_asset', 'intangible', 'long_term_investment', 'other_noncurrent_asset',
        'deferred_tax_asset',
        'payable', 'advance_received', 'accrued_expenses', 'tax_payable', 'payroll',
        'short_term_loan', 'other_liability', 'long_term_loan', 'other_long_term_liability',
        'deferred_tax_liability',
        'share_capital', 'retained_earnings', 'profit_loss', 'other_equity',
        'sales', 'other_income', 'finance_income',
        'cost_of_sales', 'operating_expense', 'other_expense', 'finance_expense', 'income_tax'
    )),
    sc_optional   INTEGER NOT NULL DEFAULT 0 CHECK (sc_optional BETWEEN 0 AND 7),
    FOREIGN KEY (company_id, parent_id)   REFERENCES accounts(company_id, id),
    FOREIGN KEY (company_id, sc1_kind_id) REFERENCES subconto_kinds(company_id, id),
    FOREIGN KEY (company_id, sc2_kind_id) REFERENCES subconto_kinds(company_id, id),
    FOREIGN KEY (company_id, sc3_kind_id) REFERENCES subconto_kinds(company_id, id),
    UNIQUE (company_id, code),
    UNIQUE (company_id, id)
);

INSERT INTO accounts_new (id, company_id, code, name, parent_id, is_group, active,
                          sc1_kind_id, sc2_kind_id, sc3_kind_id, account_class, contra,
                          two_sided, currency, account_type, sc_optional)
SELECT id, company_id, code, name, parent_id, is_group, active,
       sc1_kind_id, sc2_kind_id, sc3_kind_id, account_class, contra,
       two_sided, currency, account_type, sc_optional
FROM accounts;

DROP TABLE accounts;
ALTER TABLE accounts_new RENAME TO accounts;

-- 09 and 77 of the 1C 7.7 chart (and their subaccounts of that type) are deferred taxes.
UPDATE accounts SET account_type = 'deferred_tax_asset'
WHERE account_type = 'other_noncurrent_asset' AND (code = '09' OR code LIKE '09.%');
UPDATE accounts SET account_type = 'deferred_tax_liability'
WHERE account_type = 'other_long_term_liability' AND (code = '77' OR code LIKE '77.%');
