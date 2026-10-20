-- A new account type: money in transit (57 "Переводы в пути"), so a currency conversion
-- finds its transit account in any chart by type, whatever its code (D37, D35).
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
        'cash', 'bank', 'transit', 'receivable', 'advance_paid', 'other_receivable',
        'input_vat', 'inventory', 'fixed_asset', 'intangible', 'investment', 'other_asset',
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

-- The transit account chosen for conversions (57 of the 1C 7.7 chart) gets the new type.
UPDATE accounts SET account_type = 'transit'
WHERE (account_type IS NULL OR account_type = 'other_asset')
  AND id IN (SELECT account_id FROM account_roles WHERE role = 'fx_transit');
