-- Account types (D34): what an account means, whatever its code. The class follows from
-- the type; an account may still have a class without a type (NULL: not set).

ALTER TABLE accounts ADD COLUMN account_type TEXT CHECK (account_type IN (
    'cash', 'bank', 'receivable', 'advance_paid', 'other_receivable', 'input_vat',
    'inventory', 'fixed_asset', 'intangible', 'investment', 'other_asset',
    'payable', 'advance_received', 'tax_payable', 'payroll', 'short_term_loan',
    'long_term_loan', 'other_liability',
    'share_capital', 'retained_earnings', 'profit_loss', 'other_equity',
    'sales', 'other_income',
    'cost_of_sales', 'operating_expense', 'other_expense', 'income_tax'
));

-- Existing companies: accounts of the chart templates ("classic" and "1c77") get the type
-- of the template where the code and the class still match it (46 is sales in "classic"
-- but an asset in "1c77"; 80 is profit and loss in "classic", two-sided, but share capital
-- in "1c77").
CREATE TEMP TABLE template_types (code TEXT, account_class TEXT, two_sided INTEGER, t TEXT);
INSERT INTO template_types VALUES
    ('01', 'asset', NULL, 'fixed_asset'), ('02', 'asset', NULL, 'fixed_asset'),
    ('03', 'asset', NULL, 'fixed_asset'), ('07', 'asset', NULL, 'fixed_asset'),
    ('08', 'asset', NULL, 'fixed_asset'),
    ('04', 'asset', NULL, 'intangible'), ('05', 'asset', NULL, 'intangible'),
    ('09', 'asset', NULL, 'other_asset'),
    ('10', 'asset', NULL, 'inventory'), ('10.1', 'asset', NULL, 'inventory'),
    ('10.3', 'asset', NULL, 'inventory'), ('10.5', 'asset', NULL, 'inventory'),
    ('10.9', 'asset', NULL, 'inventory'), ('14', 'asset', NULL, 'inventory'),
    ('15', 'asset', NULL, 'inventory'), ('16', 'asset', NULL, 'inventory'),
    ('19', 'asset', NULL, 'input_vat'), ('19.1', 'asset', NULL, 'input_vat'),
    ('19.3', 'asset', NULL, 'input_vat'), ('19.4', 'asset', NULL, 'input_vat'),
    ('20', 'asset', NULL, 'inventory'), ('21', 'asset', NULL, 'inventory'),
    ('23', 'asset', NULL, 'inventory'), ('29', 'asset', NULL, 'inventory'),
    ('25', 'expense', NULL, 'operating_expense'), ('26', 'expense', NULL, 'operating_expense'),
    ('44', 'expense', NULL, 'operating_expense'),
    ('28', 'expense', NULL, 'other_expense'),
    ('31', 'asset', NULL, 'other_asset'),
    ('40', 'asset', NULL, 'inventory'), ('40', 'expense', NULL, 'cost_of_sales'),
    ('41', 'asset', NULL, 'inventory'), ('41.1', 'asset', NULL, 'inventory'),
    ('41.2', 'asset', NULL, 'inventory'), ('42', 'asset', NULL, 'inventory'),
    ('43', 'asset', NULL, 'inventory'), ('45', 'asset', NULL, 'inventory'),
    ('46', 'asset', NULL, 'inventory'), ('46', 'revenue', NULL, 'sales'),
    ('47', 'revenue', NULL, 'other_income'), ('48', 'revenue', NULL, 'other_income'),
    ('50', 'asset', NULL, 'cash'),
    ('51', 'asset', NULL, 'bank'), ('52', 'asset', NULL, 'bank'), ('55', 'asset', NULL, 'bank'),
    ('57', 'asset', NULL, 'other_asset'),
    ('58', 'asset', NULL, 'investment'), ('59', 'asset', NULL, 'investment'),
    ('60', 'liability', NULL, 'payable'), ('60.1', 'liability', NULL, 'payable'),
    ('60.2', 'asset', NULL, 'advance_paid'), ('61', 'asset', NULL, 'advance_paid'),
    ('62', 'asset', NULL, 'receivable'), ('62.1', 'asset', NULL, 'receivable'),
    ('62.2', 'liability', NULL, 'advance_received'),
    ('63', 'asset', NULL, 'receivable'),
    ('64', 'liability', NULL, 'advance_received'),
    ('66', 'liability', NULL, 'short_term_loan'), ('67', 'liability', NULL, 'long_term_loan'),
    ('90', 'liability', NULL, 'short_term_loan'),
    ('68', 'liability', NULL, 'tax_payable'), ('68.1', 'liability', NULL, 'tax_payable'),
    ('68.2', 'liability', NULL, 'tax_payable'), ('68.3', 'liability', NULL, 'tax_payable'),
    ('68.4', 'liability', NULL, 'tax_payable'), ('68.8', 'liability', NULL, 'tax_payable'),
    ('68.9', 'liability', NULL, 'tax_payable'), ('69', 'liability', NULL, 'tax_payable'),
    ('70', 'liability', NULL, 'payroll'),
    ('71', 'asset', NULL, 'other_receivable'), ('73', 'asset', NULL, 'other_receivable'),
    ('75', 'liability', NULL, 'other_liability'), ('75.1', 'asset', NULL, 'other_receivable'),
    ('75.2', 'liability', NULL, 'other_liability'),
    ('76', 'liability', NULL, 'other_liability'), ('76.1', 'liability', NULL, 'other_liability'),
    ('76.2', 'asset', NULL, 'other_receivable'), ('76.3', 'asset', NULL, 'other_receivable'),
    ('76.4', 'liability', NULL, 'other_liability'), ('76.5', 'liability', NULL, 'other_liability'),
    ('77', 'liability', NULL, 'other_liability'), ('79', 'liability', NULL, 'other_liability'),
    ('80', 'equity', 1, 'profit_loss'), ('80', 'equity', 0, 'share_capital'),
    ('85', 'equity', NULL, 'share_capital'),
    ('81', 'equity', NULL, 'other_equity'), ('82', 'equity', NULL, 'other_equity'),
    ('83', 'equity', NULL, 'other_equity'),
    ('84', 'equity', NULL, 'retained_earnings'), ('88', 'equity', NULL, 'retained_earnings'),
    ('86', 'liability', NULL, 'other_liability'),
    ('90', 'revenue', NULL, 'sales'), ('90.1', 'revenue', NULL, 'sales'),
    ('90.2', 'expense', NULL, 'cost_of_sales'), ('90.3', 'revenue', NULL, 'sales'),
    ('90.9', 'equity', NULL, 'profit_loss'),
    ('91', 'revenue', NULL, 'other_income'), ('91.1', 'revenue', NULL, 'other_income'),
    ('91.2', 'expense', NULL, 'other_expense'), ('91.9', 'equity', NULL, 'profit_loss'),
    ('94', 'asset', NULL, 'other_asset'), ('96', 'liability', NULL, 'other_liability'),
    ('97', 'asset', NULL, 'other_asset'), ('98', 'liability', NULL, 'other_liability'),
    ('99', 'equity', NULL, 'profit_loss');

UPDATE accounts SET account_type = (
    SELECT t FROM template_types tt
    WHERE tt.code = accounts.code AND tt.account_class = accounts.account_class
      AND (tt.two_sided IS NULL OR tt.two_sided = accounts.two_sided)
);

-- The user's own subaccounts (51.1, 62.5…) take their parent's type where the class is
-- the same; three levels are more than the charts have.
UPDATE accounts SET account_type = (
    SELECT p.account_type FROM accounts p
    WHERE p.company_id = accounts.company_id AND p.id = accounts.parent_id
      AND p.account_class = accounts.account_class
) WHERE account_type IS NULL AND parent_id IS NOT NULL;
UPDATE accounts SET account_type = (
    SELECT p.account_type FROM accounts p
    WHERE p.company_id = accounts.company_id AND p.id = accounts.parent_id
      AND p.account_class = accounts.account_class
) WHERE account_type IS NULL AND parent_id IS NOT NULL;
UPDATE accounts SET account_type = (
    SELECT p.account_type FROM accounts p
    WHERE p.company_id = accounts.company_id AND p.id = accounts.parent_id
      AND p.account_class = accounts.account_class
) WHERE account_type IS NULL AND parent_id IS NOT NULL;

DROP TABLE template_types;
