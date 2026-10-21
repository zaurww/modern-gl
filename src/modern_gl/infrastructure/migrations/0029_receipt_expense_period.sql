-- The month a purchase's expense belongs to when the e-qaimə comes later (D63): a service
-- of September invoiced in October. `expense_date` is the last day of that month; posting
-- the receipt then also posts an accrual on that day (Dr expense / Cr accrued expenses,
-- 76H) and the receipt itself closes it (Dr 76H / Cr supplier), so the expense falls in
-- September while the supplier's debt and the ƏDV stay on the e-qaimə's date.
-- `accrual_document_id` is that accrual's GL document. Columns added by ALTER cannot carry
-- the composite FK: the application checks the document belongs to the company.

ALTER TABLE inventory_documents ADD COLUMN expense_date TEXT
    CHECK (expense_date IS NULL OR expense_date GLOB '[0-9][0-9][0-9][0-9]-[0-1][0-9]-[0-3][0-9]');
ALTER TABLE inventory_documents ADD COLUMN accrual_document_id INTEGER REFERENCES documents(id);

CREATE UNIQUE INDEX inventory_documents_by_accrual
    ON inventory_documents (accrual_document_id) WHERE accrual_document_id IS NOT NULL;

-- A new account type for 76H: accrued expenses are a liability but not a settlement with a
-- partner by e-qaimə, so the e-qaimə report does not count Dr 76H / Cr 60 as a payment.
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
        'payable', 'advance_received', 'accrued_expenses', 'tax_payable', 'payroll',
        'short_term_loan', 'long_term_loan', 'other_liability',
        'share_capital', 'retained_earnings', 'profit_loss', 'other_equity',
        'sales', 'other_income',
        'cost_of_sales', 'operating_expense', 'other_expense', 'income_tax'
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
