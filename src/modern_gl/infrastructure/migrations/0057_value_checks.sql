-- Values the file refuses (D155), as 0053 did for integers: a mistake of the code, an
-- import or a tool is refused, not stored. On an update only a changed value is checked,
-- so a row written before stays editable.
--
-- 1. A day (*_date, date_from/to, closed_through) is a day of the calendar: the GLOB of
--    each table let '2026-02-30' and '2026-19-39' through.
-- 2. A time (created_at, posted_at, at, …) is a time SQLite reads.
-- 3. A flag is 0 or 1 (accounts.currency: 0, 1 or 2 — D28); a base currency is a code.
-- 4. An account's class is the class of its type (domain/accounts.py, D35): reports and
--    default accounts trust it. A new type adds itself here in its migration.


-- 1. days ------------------------------------------------------------------------

CREATE TRIGGER bank_portal_loads_days_insert BEFORE INSERT ON bank_portal_loads
WHEN (NEW.date_from IS NOT NULL AND date(NEW.date_from) IS NOT NEW.date_from)
   OR (NEW.date_to IS NOT NULL AND date(NEW.date_to) IS NOT NEW.date_to)
BEGIN SELECT RAISE(ABORT, 'bank_portal_loads: not a day'); END;
CREATE TRIGGER bank_portal_loads_days_update BEFORE UPDATE ON bank_portal_loads
WHEN (NEW.date_from IS NOT OLD.date_from AND NEW.date_from IS NOT NULL AND date(NEW.date_from) IS NOT NEW.date_from)
   OR (NEW.date_to IS NOT OLD.date_to AND NEW.date_to IS NOT NULL AND date(NEW.date_to) IS NOT NEW.date_to)
BEGIN SELECT RAISE(ABORT, 'bank_portal_loads: not a day'); END;

CREATE TRIGGER bank_portal_reconciled_days_insert BEFORE INSERT ON bank_portal_reconciled
WHEN (NEW.date_from IS NOT NULL AND date(NEW.date_from) IS NOT NEW.date_from)
   OR (NEW.date_to IS NOT NULL AND date(NEW.date_to) IS NOT NEW.date_to)
BEGIN SELECT RAISE(ABORT, 'bank_portal_reconciled: not a day'); END;
CREATE TRIGGER bank_portal_reconciled_days_update BEFORE UPDATE ON bank_portal_reconciled
WHEN (NEW.date_from IS NOT OLD.date_from AND NEW.date_from IS NOT NULL AND date(NEW.date_from) IS NOT NEW.date_from)
   OR (NEW.date_to IS NOT OLD.date_to AND NEW.date_to IS NOT NULL AND date(NEW.date_to) IS NOT NEW.date_to)
BEGIN SELECT RAISE(ABORT, 'bank_portal_reconciled: not a day'); END;

CREATE TRIGGER bank_statements_days_insert BEFORE INSERT ON bank_statements
WHEN (NEW.date_from IS NOT NULL AND date(NEW.date_from) IS NOT NEW.date_from)
   OR (NEW.date_to IS NOT NULL AND date(NEW.date_to) IS NOT NEW.date_to)
BEGIN SELECT RAISE(ABORT, 'bank_statements: not a day'); END;
CREATE TRIGGER bank_statements_days_update BEFORE UPDATE ON bank_statements
WHEN (NEW.date_from IS NOT OLD.date_from AND NEW.date_from IS NOT NULL AND date(NEW.date_from) IS NOT NEW.date_from)
   OR (NEW.date_to IS NOT OLD.date_to AND NEW.date_to IS NOT NULL AND date(NEW.date_to) IS NOT NEW.date_to)
BEGIN SELECT RAISE(ABORT, 'bank_statements: not a day'); END;

CREATE TRIGGER companies_days_insert BEFORE INSERT ON companies
WHEN (NEW.closed_through IS NOT NULL AND date(NEW.closed_through) IS NOT NEW.closed_through)
BEGIN SELECT RAISE(ABORT, 'companies: not a day'); END;
CREATE TRIGGER companies_days_update BEFORE UPDATE ON companies
WHEN (NEW.closed_through IS NOT OLD.closed_through AND NEW.closed_through IS NOT NULL AND date(NEW.closed_through) IS NOT NEW.closed_through)
BEGIN SELECT RAISE(ABORT, 'companies: not a day'); END;

CREATE TRIGGER currency_conversions_days_insert BEFORE INSERT ON currency_conversions
WHEN (NEW.to_date IS NOT NULL AND date(NEW.to_date) IS NOT NEW.to_date)
BEGIN SELECT RAISE(ABORT, 'currency_conversions: not a day'); END;
CREATE TRIGGER currency_conversions_days_update BEFORE UPDATE ON currency_conversions
WHEN (NEW.to_date IS NOT OLD.to_date AND NEW.to_date IS NOT NULL AND date(NEW.to_date) IS NOT NEW.to_date)
BEGIN SELECT RAISE(ABORT, 'currency_conversions: not a day'); END;

CREATE TRIGGER currency_rates_days_insert BEFORE INSERT ON currency_rates
WHEN (NEW.rate_date IS NOT NULL AND date(NEW.rate_date) IS NOT NEW.rate_date)
BEGIN SELECT RAISE(ABORT, 'currency_rates: not a day'); END;
CREATE TRIGGER currency_rates_days_update BEFORE UPDATE ON currency_rates
WHEN (NEW.rate_date IS NOT OLD.rate_date AND NEW.rate_date IS NOT NULL AND date(NEW.rate_date) IS NOT NEW.rate_date)
BEGIN SELECT RAISE(ABORT, 'currency_rates: not a day'); END;

CREATE TRIGGER documents_days_insert BEFORE INSERT ON documents
WHEN (NEW.doc_date IS NOT NULL AND date(NEW.doc_date) IS NOT NEW.doc_date)
BEGIN SELECT RAISE(ABORT, 'documents: not a day'); END;
CREATE TRIGGER documents_days_update BEFORE UPDATE ON documents
WHEN (NEW.doc_date IS NOT OLD.doc_date AND NEW.doc_date IS NOT NULL AND date(NEW.doc_date) IS NOT NEW.doc_date)
BEGIN SELECT RAISE(ABORT, 'documents: not a day'); END;

CREATE TRIGGER eqaime_portal_days_insert BEFORE INSERT ON eqaime_portal
WHEN (NEW.doc_date IS NOT NULL AND date(NEW.doc_date) IS NOT NEW.doc_date)
BEGIN SELECT RAISE(ABORT, 'eqaime_portal: not a day'); END;
CREATE TRIGGER eqaime_portal_days_update BEFORE UPDATE ON eqaime_portal
WHEN (NEW.doc_date IS NOT OLD.doc_date AND NEW.doc_date IS NOT NULL AND date(NEW.doc_date) IS NOT NEW.doc_date)
BEGIN SELECT RAISE(ABORT, 'eqaime_portal: not a day'); END;

CREATE TRIGGER eqaime_portal_changes_days_insert BEFORE INSERT ON eqaime_portal_changes
WHEN (NEW.old_date IS NOT NULL AND date(NEW.old_date) IS NOT NEW.old_date)
   OR (NEW.new_date IS NOT NULL AND date(NEW.new_date) IS NOT NEW.new_date)
BEGIN SELECT RAISE(ABORT, 'eqaime_portal_changes: not a day'); END;
CREATE TRIGGER eqaime_portal_changes_days_update BEFORE UPDATE ON eqaime_portal_changes
WHEN (NEW.old_date IS NOT OLD.old_date AND NEW.old_date IS NOT NULL AND date(NEW.old_date) IS NOT NEW.old_date)
   OR (NEW.new_date IS NOT OLD.new_date AND NEW.new_date IS NOT NULL AND date(NEW.new_date) IS NOT NEW.new_date)
BEGIN SELECT RAISE(ABORT, 'eqaime_portal_changes: not a day'); END;

CREATE TRIGGER eqaime_reconciled_days_insert BEFORE INSERT ON eqaime_reconciled
WHEN (NEW.date_from IS NOT NULL AND date(NEW.date_from) IS NOT NEW.date_from)
   OR (NEW.date_to IS NOT NULL AND date(NEW.date_to) IS NOT NEW.date_to)
BEGIN SELECT RAISE(ABORT, 'eqaime_reconciled: not a day'); END;
CREATE TRIGGER eqaime_reconciled_days_update BEFORE UPDATE ON eqaime_reconciled
WHEN (NEW.date_from IS NOT OLD.date_from AND NEW.date_from IS NOT NULL AND date(NEW.date_from) IS NOT NEW.date_from)
   OR (NEW.date_to IS NOT OLD.date_to AND NEW.date_to IS NOT NULL AND date(NEW.date_to) IS NOT NEW.date_to)
BEGIN SELECT RAISE(ABORT, 'eqaime_reconciled: not a day'); END;

CREATE TRIGGER inventory_accruals_days_insert BEFORE INSERT ON inventory_accruals
WHEN (NEW.expense_date IS NOT NULL AND date(NEW.expense_date) IS NOT NEW.expense_date)
BEGIN SELECT RAISE(ABORT, 'inventory_accruals: not a day'); END;
CREATE TRIGGER inventory_accruals_days_update BEFORE UPDATE ON inventory_accruals
WHEN (NEW.expense_date IS NOT OLD.expense_date AND NEW.expense_date IS NOT NULL AND date(NEW.expense_date) IS NOT NEW.expense_date)
BEGIN SELECT RAISE(ABORT, 'inventory_accruals: not a day'); END;

CREATE TRIGGER inventory_documents_days_insert BEFORE INSERT ON inventory_documents
WHEN (NEW.doc_date IS NOT NULL AND date(NEW.doc_date) IS NOT NEW.doc_date)
BEGIN SELECT RAISE(ABORT, 'inventory_documents: not a day'); END;
CREATE TRIGGER inventory_documents_days_update BEFORE UPDATE ON inventory_documents
WHEN (NEW.doc_date IS NOT OLD.doc_date AND NEW.doc_date IS NOT NULL AND date(NEW.doc_date) IS NOT NEW.doc_date)
BEGIN SELECT RAISE(ABORT, 'inventory_documents: not a day'); END;

CREATE TRIGGER inventory_lines_days_insert BEFORE INSERT ON inventory_lines
WHEN (NEW.expense_date IS NOT NULL AND date(NEW.expense_date) IS NOT NEW.expense_date)
BEGIN SELECT RAISE(ABORT, 'inventory_lines: not a day'); END;
CREATE TRIGGER inventory_lines_days_update BEFORE UPDATE ON inventory_lines
WHEN (NEW.expense_date IS NOT OLD.expense_date AND NEW.expense_date IS NOT NULL AND date(NEW.expense_date) IS NOT NEW.expense_date)
BEGIN SELECT RAISE(ABORT, 'inventory_lines: not a day'); END;

CREATE TRIGGER opening_balance_documents_days_insert BEFORE INSERT ON opening_balance_documents
WHEN (NEW.effective_date IS NOT NULL AND date(NEW.effective_date) IS NOT NEW.effective_date)
BEGIN SELECT RAISE(ABORT, 'opening_balance_documents: not a day'); END;
CREATE TRIGGER opening_balance_documents_days_update BEFORE UPDATE ON opening_balance_documents
WHEN (NEW.effective_date IS NOT OLD.effective_date AND NEW.effective_date IS NOT NULL AND date(NEW.effective_date) IS NOT NEW.effective_date)
BEGIN SELECT RAISE(ABORT, 'opening_balance_documents: not a day'); END;

CREATE TRIGGER stock_movements_days_insert BEFORE INSERT ON stock_movements
WHEN (NEW.doc_date IS NOT NULL AND date(NEW.doc_date) IS NOT NEW.doc_date)
BEGIN SELECT RAISE(ABORT, 'stock_movements: not a day'); END;
CREATE TRIGGER stock_movements_days_update BEFORE UPDATE ON stock_movements
WHEN (NEW.doc_date IS NOT OLD.doc_date AND NEW.doc_date IS NOT NULL AND date(NEW.doc_date) IS NOT NEW.doc_date)
BEGIN SELECT RAISE(ABORT, 'stock_movements: not a day'); END;


-- 2. times -----------------------------------------------------------------------

CREATE TRIGGER audit_events_times_insert BEFORE INSERT ON audit_events
WHEN (NEW.at IS NOT NULL AND datetime(NEW.at) IS NULL)
BEGIN SELECT RAISE(ABORT, 'audit_events: not a time'); END;

CREATE TRIGGER bank_portal_loads_times_insert BEFORE INSERT ON bank_portal_loads
WHEN (NEW.loaded_at IS NOT NULL AND datetime(NEW.loaded_at) IS NULL)
BEGIN SELECT RAISE(ABORT, 'bank_portal_loads: not a time'); END;
CREATE TRIGGER bank_portal_loads_times_update BEFORE UPDATE ON bank_portal_loads
WHEN (NEW.loaded_at IS NOT OLD.loaded_at AND NEW.loaded_at IS NOT NULL AND datetime(NEW.loaded_at) IS NULL)
BEGIN SELECT RAISE(ABORT, 'bank_portal_loads: not a time'); END;

CREATE TRIGGER bank_portal_reconciled_times_insert BEFORE INSERT ON bank_portal_reconciled
WHEN (NEW.reconciled_at IS NOT NULL AND datetime(NEW.reconciled_at) IS NULL)
BEGIN SELECT RAISE(ABORT, 'bank_portal_reconciled: not a time'); END;
CREATE TRIGGER bank_portal_reconciled_times_update BEFORE UPDATE ON bank_portal_reconciled
WHEN (NEW.reconciled_at IS NOT OLD.reconciled_at AND NEW.reconciled_at IS NOT NULL AND datetime(NEW.reconciled_at) IS NULL)
BEGIN SELECT RAISE(ABORT, 'bank_portal_reconciled: not a time'); END;

CREATE TRIGGER companies_times_insert BEFORE INSERT ON companies
WHEN (NEW.created_at IS NOT NULL AND datetime(NEW.created_at) IS NULL)
BEGIN SELECT RAISE(ABORT, 'companies: not a time'); END;
CREATE TRIGGER companies_times_update BEFORE UPDATE ON companies
WHEN (NEW.created_at IS NOT OLD.created_at AND NEW.created_at IS NOT NULL AND datetime(NEW.created_at) IS NULL)
BEGIN SELECT RAISE(ABORT, 'companies: not a time'); END;

CREATE TRIGGER documents_times_insert BEFORE INSERT ON documents
WHEN (NEW.created_at IS NOT NULL AND datetime(NEW.created_at) IS NULL)
   OR (NEW.posted_at IS NOT NULL AND datetime(NEW.posted_at) IS NULL)
BEGIN SELECT RAISE(ABORT, 'documents: not a time'); END;
CREATE TRIGGER documents_times_update BEFORE UPDATE ON documents
WHEN (NEW.created_at IS NOT OLD.created_at AND NEW.created_at IS NOT NULL AND datetime(NEW.created_at) IS NULL)
   OR (NEW.posted_at IS NOT OLD.posted_at AND NEW.posted_at IS NOT NULL AND datetime(NEW.posted_at) IS NULL)
BEGIN SELECT RAISE(ABORT, 'documents: not a time'); END;

CREATE TRIGGER eqaime_portal_times_insert BEFORE INSERT ON eqaime_portal
WHEN (NEW.first_seen IS NOT NULL AND datetime(NEW.first_seen) IS NULL)
   OR (NEW.last_seen IS NOT NULL AND datetime(NEW.last_seen) IS NULL)
BEGIN SELECT RAISE(ABORT, 'eqaime_portal: not a time'); END;
CREATE TRIGGER eqaime_portal_times_update BEFORE UPDATE ON eqaime_portal
WHEN (NEW.first_seen IS NOT OLD.first_seen AND NEW.first_seen IS NOT NULL AND datetime(NEW.first_seen) IS NULL)
   OR (NEW.last_seen IS NOT OLD.last_seen AND NEW.last_seen IS NOT NULL AND datetime(NEW.last_seen) IS NULL)
BEGIN SELECT RAISE(ABORT, 'eqaime_portal: not a time'); END;

CREATE TRIGGER eqaime_portal_changes_times_insert BEFORE INSERT ON eqaime_portal_changes
WHEN (NEW.seen_at IS NOT NULL AND datetime(NEW.seen_at) IS NULL)
BEGIN SELECT RAISE(ABORT, 'eqaime_portal_changes: not a time'); END;
CREATE TRIGGER eqaime_portal_changes_times_update BEFORE UPDATE ON eqaime_portal_changes
WHEN (NEW.seen_at IS NOT OLD.seen_at AND NEW.seen_at IS NOT NULL AND datetime(NEW.seen_at) IS NULL)
BEGIN SELECT RAISE(ABORT, 'eqaime_portal_changes: not a time'); END;

CREATE TRIGGER eqaime_reconciled_times_insert BEFORE INSERT ON eqaime_reconciled
WHEN (NEW.reconciled_at IS NOT NULL AND datetime(NEW.reconciled_at) IS NULL)
BEGIN SELECT RAISE(ABORT, 'eqaime_reconciled: not a time'); END;
CREATE TRIGGER eqaime_reconciled_times_update BEFORE UPDATE ON eqaime_reconciled
WHEN (NEW.reconciled_at IS NOT OLD.reconciled_at AND NEW.reconciled_at IS NOT NULL AND datetime(NEW.reconciled_at) IS NULL)
BEGIN SELECT RAISE(ABORT, 'eqaime_reconciled: not a time'); END;

CREATE TRIGGER inventory_documents_times_insert BEFORE INSERT ON inventory_documents
WHEN (NEW.created_at IS NOT NULL AND datetime(NEW.created_at) IS NULL)
   OR (NEW.posted_at IS NOT NULL AND datetime(NEW.posted_at) IS NULL)
BEGIN SELECT RAISE(ABORT, 'inventory_documents: not a time'); END;
CREATE TRIGGER inventory_documents_times_update BEFORE UPDATE ON inventory_documents
WHEN (NEW.created_at IS NOT OLD.created_at AND NEW.created_at IS NOT NULL AND datetime(NEW.created_at) IS NULL)
   OR (NEW.posted_at IS NOT OLD.posted_at AND NEW.posted_at IS NOT NULL AND datetime(NEW.posted_at) IS NULL)
BEGIN SELECT RAISE(ABORT, 'inventory_documents: not a time'); END;


-- 3. flags and codes -------------------------------------------------------------

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

CREATE TRIGGER currencies_flags_insert BEFORE INSERT ON currencies
WHEN NEW.active NOT IN (0, 1)
BEGIN SELECT RAISE(ABORT, 'currencies: a flag is 0 or 1'); END;
CREATE TRIGGER currencies_flags_update BEFORE UPDATE ON currencies
WHEN (NEW.active IS NOT OLD.active AND NEW.active NOT IN (0, 1))
BEGIN SELECT RAISE(ABORT, 'currencies: a flag is 0 or 1'); END;

CREATE TRIGGER inventory_units_flags_insert BEFORE INSERT ON inventory_units
WHEN NEW.active NOT IN (0, 1)
BEGIN SELECT RAISE(ABORT, 'inventory_units: a flag is 0 or 1'); END;
CREATE TRIGGER inventory_units_flags_update BEFORE UPDATE ON inventory_units
WHEN (NEW.active IS NOT OLD.active AND NEW.active NOT IN (0, 1))
BEGIN SELECT RAISE(ABORT, 'inventory_units: a flag is 0 or 1'); END;

CREATE TRIGGER landed_cost_types_flags_insert BEFORE INSERT ON landed_cost_types
WHEN NEW.active NOT IN (0, 1)
BEGIN SELECT RAISE(ABORT, 'landed_cost_types: a flag is 0 or 1'); END;
CREATE TRIGGER landed_cost_types_flags_update BEFORE UPDATE ON landed_cost_types
WHEN (NEW.active IS NOT OLD.active AND NEW.active NOT IN (0, 1))
BEGIN SELECT RAISE(ABORT, 'landed_cost_types: a flag is 0 or 1'); END;

CREATE TRIGGER subconto_values_flags_insert BEFORE INSERT ON subconto_values
WHEN NEW.active NOT IN (0, 1)
BEGIN SELECT RAISE(ABORT, 'subconto_values: a flag is 0 or 1'); END;
CREATE TRIGGER subconto_values_flags_update BEFORE UPDATE ON subconto_values
WHEN (NEW.active IS NOT OLD.active AND NEW.active NOT IN (0, 1))
BEGIN SELECT RAISE(ABORT, 'subconto_values: a flag is 0 or 1'); END;

CREATE TRIGGER companies_currency_insert BEFORE INSERT ON companies
WHEN NEW.base_currency NOT GLOB '[A-Z][A-Z][A-Z]'
BEGIN SELECT RAISE(ABORT, 'companies: base_currency is a currency code'); END;
CREATE TRIGGER companies_currency_update BEFORE UPDATE OF base_currency ON companies
WHEN NEW.base_currency NOT GLOB '[A-Z][A-Z][A-Z]'
BEGIN SELECT RAISE(ABORT, 'companies: base_currency is a currency code'); END;


-- 4. an account's class is its type's ---------------------------------------------

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
