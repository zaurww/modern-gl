-- A service sold in an earlier month than its e-qaimə (D65 for sales): the income is
-- accrued on the last day of its month to a new account type, accrued income (76G, an
-- asset with the counterparty directory), and the sale closes the accrual (Dr customer /
-- Cr 76G); the VAT and the customer's debt stay on the e-qaimə's date.
-- SQLite cannot change a CHECK in place: the table is rebuilt, ids are kept (as 0048);
-- its triggers of 0053 and 0057 go with it and are made again, the type/class ones with
-- the new type. No view or trigger of another table names `accounts`.

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
        'other_receivable', 'accrued_income', 'input_vat', 'inventory', 'investment', 'other_asset',
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

-- the triggers of 0053 and 0057 on accounts, made anew ---------------------------------

CREATE TRIGGER accounts_integers_insert BEFORE INSERT ON accounts
WHEN typeof(NEW.company_id) NOT IN ('integer', 'null')
   OR typeof(NEW.parent_id) NOT IN ('integer', 'null')
   OR typeof(NEW.is_group) NOT IN ('integer', 'null')
   OR typeof(NEW.active) NOT IN ('integer', 'null')
   OR typeof(NEW.sc1_kind_id) NOT IN ('integer', 'null')
   OR typeof(NEW.sc2_kind_id) NOT IN ('integer', 'null')
   OR typeof(NEW.sc3_kind_id) NOT IN ('integer', 'null')
   OR typeof(NEW.contra) NOT IN ('integer', 'null')
   OR typeof(NEW.two_sided) NOT IN ('integer', 'null')
   OR typeof(NEW.currency) NOT IN ('integer', 'null')
   OR typeof(NEW.sc_optional) NOT IN ('integer', 'null')
BEGIN SELECT RAISE(ABORT, 'accounts: not an integer'); END;

CREATE TRIGGER accounts_integers_update BEFORE UPDATE ON accounts
WHEN (NEW.company_id IS NOT OLD.company_id AND typeof(NEW.company_id) NOT IN ('integer', 'null'))
   OR (NEW.parent_id IS NOT OLD.parent_id AND typeof(NEW.parent_id) NOT IN ('integer', 'null'))
   OR (NEW.is_group IS NOT OLD.is_group AND typeof(NEW.is_group) NOT IN ('integer', 'null'))
   OR (NEW.active IS NOT OLD.active AND typeof(NEW.active) NOT IN ('integer', 'null'))
   OR (NEW.sc1_kind_id IS NOT OLD.sc1_kind_id AND typeof(NEW.sc1_kind_id) NOT IN ('integer', 'null'))
   OR (NEW.sc2_kind_id IS NOT OLD.sc2_kind_id AND typeof(NEW.sc2_kind_id) NOT IN ('integer', 'null'))
   OR (NEW.sc3_kind_id IS NOT OLD.sc3_kind_id AND typeof(NEW.sc3_kind_id) NOT IN ('integer', 'null'))
   OR (NEW.contra IS NOT OLD.contra AND typeof(NEW.contra) NOT IN ('integer', 'null'))
   OR (NEW.two_sided IS NOT OLD.two_sided AND typeof(NEW.two_sided) NOT IN ('integer', 'null'))
   OR (NEW.currency IS NOT OLD.currency AND typeof(NEW.currency) NOT IN ('integer', 'null'))
   OR (NEW.sc_optional IS NOT OLD.sc_optional AND typeof(NEW.sc_optional) NOT IN ('integer', 'null'))
BEGIN SELECT RAISE(ABORT, 'accounts: not an integer'); END;

CREATE TRIGGER accounts_flags_insert BEFORE INSERT ON accounts
WHEN NEW.is_group NOT IN (0, 1)
   OR NEW.active NOT IN (0, 1)
   OR NEW.contra NOT IN (0, 1)
   OR NEW.two_sided NOT IN (0, 1)
   OR NEW.currency NOT IN (0, 1, 2)
BEGIN SELECT RAISE(ABORT, 'accounts: a flag is 0 or 1'); END;
CREATE TRIGGER accounts_flags_update BEFORE UPDATE ON accounts
WHEN (NEW.is_group IS NOT OLD.is_group AND NEW.is_group NOT IN (0, 1))
   OR (NEW.active IS NOT OLD.active AND NEW.active NOT IN (0, 1))
   OR (NEW.contra IS NOT OLD.contra AND NEW.contra NOT IN (0, 1))
   OR (NEW.two_sided IS NOT OLD.two_sided AND NEW.two_sided NOT IN (0, 1))
   OR (NEW.currency IS NOT OLD.currency AND NEW.currency NOT IN (0, 1, 2))
BEGIN SELECT RAISE(ABORT, 'accounts: a flag is 0 or 1'); END;

CREATE TRIGGER accounts_type_class_insert BEFORE INSERT ON accounts
WHEN NEW.account_type IS NOT NULL AND NEW.account_class IS NOT (
    CASE NEW.account_type
        WHEN 'cash' THEN 'asset'
        WHEN 'bank' THEN 'asset'
        WHEN 'transit' THEN 'asset'
        WHEN 'vat_deposit' THEN 'asset'
        WHEN 'receivable' THEN 'asset'
        WHEN 'advance_paid' THEN 'asset'
        WHEN 'other_receivable' THEN 'asset'
        WHEN 'accrued_income' THEN 'asset'
        WHEN 'input_vat' THEN 'asset'
        WHEN 'inventory' THEN 'asset'
        WHEN 'investment' THEN 'asset'
        WHEN 'other_asset' THEN 'asset'
        WHEN 'fixed_asset' THEN 'asset'
        WHEN 'intangible' THEN 'asset'
        WHEN 'long_term_investment' THEN 'asset'
        WHEN 'other_noncurrent_asset' THEN 'asset'
        WHEN 'deferred_tax_asset' THEN 'asset'
        WHEN 'payable' THEN 'liability'
        WHEN 'advance_received' THEN 'liability'
        WHEN 'accrued_expenses' THEN 'liability'
        WHEN 'tax_payable' THEN 'liability'
        WHEN 'payroll' THEN 'liability'
        WHEN 'short_term_loan' THEN 'liability'
        WHEN 'other_liability' THEN 'liability'
        WHEN 'long_term_loan' THEN 'liability'
        WHEN 'other_long_term_liability' THEN 'liability'
        WHEN 'deferred_tax_liability' THEN 'liability'
        WHEN 'share_capital' THEN 'equity'
        WHEN 'retained_earnings' THEN 'equity'
        WHEN 'profit_loss' THEN 'equity'
        WHEN 'other_equity' THEN 'equity'
        WHEN 'sales' THEN 'revenue'
        WHEN 'other_income' THEN 'revenue'
        WHEN 'finance_income' THEN 'revenue'
        WHEN 'cost_of_sales' THEN 'expense'
        WHEN 'operating_expense' THEN 'expense'
        WHEN 'other_expense' THEN 'expense'
        WHEN 'finance_expense' THEN 'expense'
        WHEN 'income_tax' THEN 'expense'
    END)
BEGIN SELECT RAISE(ABORT, 'accounts: a type of another class'); END;
CREATE TRIGGER accounts_type_class_update BEFORE UPDATE OF account_type, account_class ON accounts
WHEN NEW.account_type IS NOT NULL AND NEW.account_class IS NOT (
    CASE NEW.account_type
        WHEN 'cash' THEN 'asset'
        WHEN 'bank' THEN 'asset'
        WHEN 'transit' THEN 'asset'
        WHEN 'vat_deposit' THEN 'asset'
        WHEN 'receivable' THEN 'asset'
        WHEN 'advance_paid' THEN 'asset'
        WHEN 'other_receivable' THEN 'asset'
        WHEN 'accrued_income' THEN 'asset'
        WHEN 'input_vat' THEN 'asset'
        WHEN 'inventory' THEN 'asset'
        WHEN 'investment' THEN 'asset'
        WHEN 'other_asset' THEN 'asset'
        WHEN 'fixed_asset' THEN 'asset'
        WHEN 'intangible' THEN 'asset'
        WHEN 'long_term_investment' THEN 'asset'
        WHEN 'other_noncurrent_asset' THEN 'asset'
        WHEN 'deferred_tax_asset' THEN 'asset'
        WHEN 'payable' THEN 'liability'
        WHEN 'advance_received' THEN 'liability'
        WHEN 'accrued_expenses' THEN 'liability'
        WHEN 'tax_payable' THEN 'liability'
        WHEN 'payroll' THEN 'liability'
        WHEN 'short_term_loan' THEN 'liability'
        WHEN 'other_liability' THEN 'liability'
        WHEN 'long_term_loan' THEN 'liability'
        WHEN 'other_long_term_liability' THEN 'liability'
        WHEN 'deferred_tax_liability' THEN 'liability'
        WHEN 'share_capital' THEN 'equity'
        WHEN 'retained_earnings' THEN 'equity'
        WHEN 'profit_loss' THEN 'equity'
        WHEN 'other_equity' THEN 'equity'
        WHEN 'sales' THEN 'revenue'
        WHEN 'other_income' THEN 'revenue'
        WHEN 'finance_income' THEN 'revenue'
        WHEN 'cost_of_sales' THEN 'expense'
        WHEN 'operating_expense' THEN 'expense'
        WHEN 'other_expense' THEN 'expense'
        WHEN 'finance_expense' THEN 'expense'
        WHEN 'income_tax' THEN 'expense'
    END)
BEGIN SELECT RAISE(ABORT, 'accounts: a type of another class'); END;
